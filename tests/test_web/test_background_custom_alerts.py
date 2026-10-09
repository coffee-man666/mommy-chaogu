"""阶段五：BackgroundService._tick 的自定义告警旁挂 + earnings 日频派发。

核心验收用例（docs/plans/trading-method-landing.md 阶段五）：
- 空自选股不失效：watchlist 为空但存在告警时，评估循环仍进入（_tick 并集判空）
- 非自选股告警代码会评估：Snapshot 行外的代码经 adapter.get_quote 补拉
- 命中走既有 SignalNotifier（严重度过滤 + Deduper 一码一规一天）
- 环境变量 MOMMY_ALERTS_BUILTIN_ONLY 一键停用
- earnings 任务收盘后当日派发一次，信号进同一 notifier
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)
from mommy_chaogu.push import SignalNotifier
from mommy_chaogu.push.deduper import JsonFileDeduper
from mommy_chaogu.signals import Alerter
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.signals.custom_evaluation import MOMMY_ALERTS_BUILTIN_ONLY_ENV
from mommy_chaogu.signals.types import Signal, SignalSeverity
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.background import BackgroundService

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeAdapter:
    """离线 adapter：按预设返回报价，记录 get_quote 调用。"""

    def __init__(self, quotes: dict[str, Quote]) -> None:
        self.name = "fake"
        self._quotes = quotes
        self.get_quote_calls: list[str] = []

    def get_quote(self, code: str) -> Quote | None:
        self.get_quote_calls.append(code)
        return self._quotes.get(code)

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        return [q for c in codes if (q := self._quotes.get(c)) is not None]

    def list_market_quotes(self) -> list[Quote]:
        # 模拟全市场快照只含自选股（000001 不在全市场返回里也行）
        return list(self._quotes.values())

    def get_order_book(self, code: str) -> Any:
        return None

    def get_bars(self, code: str, **kw: Any) -> list[Any]:
        return []

    def get_ticks(self, code: str, limit: int | None = None) -> list[Any]:
        return []

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        return []

    def get_belonging_boards(self, code: str) -> list[Any]:
        return []

    def health_check(self) -> bool:
        return True


class RecordingPusher:
    def __init__(self) -> None:
        self.pushed: list[Signal] = []

    def push(self, signal: Signal) -> bool:
        self.pushed.append(signal)
        return True


def _make_quote(code: str, price: str, pct: str = "0") -> Quote:
    return Quote(
        code=code,
        name=f"名称{code}",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal(price),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        prev_close=Decimal(price),
        change=Decimal("0"),
        change_pct=Decimal(pct),
        volume=100000,
        turnover=Money.from_yuan(100000000),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime.now(UTC),
    )


def _make_earnings_signal() -> Signal:
    return Signal(
        timestamp=datetime.now(UTC),
        code="603662",
        name="柯力传感",
        rule_id="earnings_beat",
        severity=SignalSeverity.CRITICAL,
        title="柯力传感 超预期",
        detail="earnings daily test signal",
    )


def _make_service(
    tmp_path: Path,
    *,
    adapter: FakeAdapter,
    watchlist_entries: list[str],
    alerts: list[tuple[str, str, Decimal]],
    notifier: SignalNotifier | None,
    earnings_job: Callable[[], list[Signal]] | None = None,
) -> BackgroundService:
    wl = WatchlistStore(tmp_path / "portfolio.db")
    wl.get_or_create_group("默认")
    for code in watchlist_entries:
        wl.add_entry(code, "默认")
    alert_store = CustomAlertStore(tmp_path / "portfolio.db")
    for code, condition, threshold in alerts:
        alert_store.add(code, f"名称{code}", condition, threshold)
    return BackgroundService(
        adapter=adapter,
        watchlist=wl,
        alerter=Alerter.default(),
        notifier=notifier,
        custom_alerts=alert_store,
        earnings_job=earnings_job,
    )


def _notifier(tmp_path: Path, pusher: RecordingPusher) -> SignalNotifier:
    return SignalNotifier(pusher, JsonFileDeduper(tmp_path / "pushed.json"))


# ---------- 用例 1：空自选股不失效 ----------


def test_tick_empty_watchlist_still_evaluates_alerts(tmp_path: Path) -> None:
    """自选股为空 + 一条告警 → 评估循环进入，命中走 notifier 推送。"""

    async def scenario() -> None:
        pusher = RecordingPusher()
        adapter = FakeAdapter({"600519": _make_quote("600519", "1700.00")})
        svc = _make_service(
            tmp_path / "s1",
            adapter=adapter,
            watchlist_entries=[],
            alerts=[("600519", "price_above", Decimal("1600"))],
            notifier=_notifier(tmp_path / "s1", pusher),
        )
        await svc._tick()

        # 旧实现：codes 为空直接 return，last_poll_at 保持 None
        assert svc.last_poll_at() is not None
        assert [s.code for s in pusher.pushed] == ["600519"]
        assert svc._latest_signals, "custom signal should land in latest_signals"
        assert svc._latest_signals[0].rule_id.startswith("custom_alert_")
        assert adapter.get_quote_calls == ["600519"]

    asyncio.run(scenario())


# ---------- 用例 2：非自选股告警代码会评估 ----------


def test_tick_alert_code_outside_watchlist_evaluated(tmp_path: Path) -> None:
    """告警代码 000001 不在自选股 → Snapshot 行外，经 get_quote 补拉后评估。"""

    async def scenario() -> None:
        pusher = RecordingPusher()
        adapter = FakeAdapter(
            {
                "600519": _make_quote("600519", "100"),
                "000001": _make_quote("000001", "10.27"),
            }
        )
        svc = _make_service(
            tmp_path / "s2",
            adapter=adapter,
            watchlist_entries=["600519"],
            alerts=[("000001", "price_above", Decimal("10"))],
            notifier=_notifier(tmp_path / "s2", pusher),
        )
        await svc._tick()

        # Snapshot 只含自选股 600519；000001 是经补拉评估出来的
        assert svc._latest_snapshot is not None
        assert [r.quote.code for r in svc._latest_snapshot.rows] == ["600519"]
        assert [s.code for s in pusher.pushed] == ["000001"]

    asyncio.run(scenario())


def test_tick_alert_not_triggered_no_push(tmp_path: Path) -> None:
    async def scenario() -> None:
        pusher = RecordingPusher()
        adapter = FakeAdapter(
            {"600519": _make_quote("600519", "100"), "000001": _make_quote("000001", "9.00")}
        )
        svc = _make_service(
            tmp_path / "s3",
            adapter=adapter,
            watchlist_entries=["600519"],
            alerts=[("000001", "price_above", Decimal("10"))],
            notifier=_notifier(tmp_path / "s3", pusher),
        )
        await svc._tick()
        assert pusher.pushed == []

    asyncio.run(scenario())


# ---------- Deduper：一码一规一天 ----------


def test_tick_deduper_suppresses_same_day_repush(tmp_path: Path) -> None:
    """条件持续满足的第二个 tick 不再推（当天限流继承既有 Deduper）。"""

    async def scenario() -> None:
        pusher = RecordingPusher()
        adapter = FakeAdapter({"600519": _make_quote("600519", "1700.00")})
        svc = _make_service(
            tmp_path / "s4",
            adapter=adapter,
            watchlist_entries=[],
            alerts=[("600519", "price_above", Decimal("1600"))],
            notifier=_notifier(tmp_path / "s4", pusher),
        )
        await svc._tick()
        await svc._tick()
        assert len(pusher.pushed) == 1
        # latest_signals 每 tick 都反映命中（推送被限流，评估不限）
        assert len(svc._latest_signals) == 1

    asyncio.run(scenario())


# ---------- 环境变量开关 ----------


def test_tick_env_switch_disables_custom_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "1")
        pusher = RecordingPusher()
        adapter = FakeAdapter({"600519": _make_quote("600519", "1700.00")})
        svc = _make_service(
            tmp_path / "s5",
            adapter=adapter,
            watchlist_entries=[],
            alerts=[("600519", "price_above", Decimal("1600"))],
            notifier=_notifier(tmp_path / "s5", pusher),
        )
        await svc._tick()
        # 开关停用 → 并集为空 → _tick 直接 return，报价都没拉
        assert pusher.pushed == []
        assert adapter.get_quote_calls == []
        assert svc.last_poll_at() is None

    asyncio.run(scenario())


# ---------- earnings 日频派发 ----------


def test_earnings_dispatched_after_close_once_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """收盘后（Asia/Shanghai ≥ 15:35）派发一次；当日第二次不重复派发。"""
    from mommy_chaogu.web import background as bg

    # 08:00 UTC = 16:00 Shanghai（收盘后）
    monkeypatch.setattr(bg, "_utcnow", lambda: datetime(2026, 10, 1, 8, 0, tzinfo=UTC))

    async def scenario() -> None:
        pusher = RecordingPusher()
        calls: list[int] = []

        def job() -> list[Signal]:
            calls.append(1)
            return [_make_earnings_signal()]

        svc = _make_service(
            tmp_path / "s6",
            adapter=FakeAdapter({}),
            watchlist_entries=["600519"],
            alerts=[],
            notifier=_notifier(tmp_path / "s6", pusher),
            earnings_job=job,
        )
        svc.weixin_sender = lambda _signals: 0
        svc._weixin_queue = asyncio.Queue(maxsize=1)

        svc._maybe_dispatch_earnings()
        assert svc._earnings_task is not None
        await svc._earnings_task

        # 信号走同一 notifier + 微信队列
        assert [s.rule_id for s in pusher.pushed] == ["earnings_beat"]
        assert svc._pushed_signals[-1].rule_id == "earnings_beat"
        assert svc._weixin_queue.qsize() == 1
        assert svc._last_earnings_run == date(2026, 10, 1)

        # 当日第二次 tick 不再派发
        svc._maybe_dispatch_earnings()
        await asyncio.sleep(0)
        assert len(calls) == 1

    asyncio.run(scenario())


def test_earnings_not_dispatched_before_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """15:35 前不派发。"""
    from mommy_chaogu.web import background as bg

    monkeypatch.setattr(bg, "_utcnow", lambda: datetime(2026, 10, 1, 1, 0, tzinfo=UTC))

    async def scenario() -> None:
        calls: list[int] = []

        def job() -> list[Signal]:
            calls.append(1)
            return []

        svc = _make_service(
            tmp_path / "s7",
            adapter=FakeAdapter({}),
            watchlist_entries=["600519"],
            alerts=[],
            notifier=None,
            earnings_job=job,
        )
        svc._maybe_dispatch_earnings()
        assert svc._earnings_task is None
        assert calls == []
        assert svc._last_earnings_run is None

    asyncio.run(scenario())


def test_earnings_job_failure_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mommy_chaogu.web import background as bg

    monkeypatch.setattr(bg, "_utcnow", lambda: datetime(2026, 10, 1, 8, 0, tzinfo=UTC))

    async def scenario() -> None:
        def job() -> list[Signal]:
            raise RuntimeError("simulated earnings failure")

        svc = _make_service(
            tmp_path / "s8",
            adapter=FakeAdapter({}),
            watchlist_entries=["600519"],
            alerts=[],
            notifier=None,
            earnings_job=job,
        )
        svc._maybe_dispatch_earnings()
        assert svc._earnings_task is not None
        await svc._earnings_task  # 异常被捕获，任务正常结束

    asyncio.run(scenario())


def test_earnings_signals_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """earnings 信号经 alerter.write_signals_log 落 signals.log。"""
    from mommy_chaogu.web import background as bg

    monkeypatch.setattr(bg, "_utcnow", lambda: datetime(2026, 10, 1, 8, 0, tzinfo=UTC))

    async def scenario() -> None:
        signals_log = tmp_path / "s9" / "signals.log"
        wl = WatchlistStore(tmp_path / "s9" / "portfolio.db")
        wl.get_or_create_group("默认")
        wl.add_entry("600519", "默认")
        svc = BackgroundService(
            adapter=FakeAdapter({}),
            watchlist=wl,
            alerter=Alerter.default(log_path=signals_log),
            earnings_job=lambda: [_make_earnings_signal()],
        )
        svc._maybe_dispatch_earnings()
        assert svc._earnings_task is not None
        await svc._earnings_task
        assert "603662" in signals_log.read_text(encoding="utf-8")

    asyncio.run(scenario())


# ---------- should_run 纯函数（时间门控） ----------


def test_should_run_gating() -> None:
    from mommy_chaogu.earnings.daily import should_run

    before_close = datetime(2026, 10, 1, 15, 0, tzinfo=_SHANGHAI)
    after_close = datetime(2026, 10, 1, 15, 35, tzinfo=_SHANGHAI)
    evening = datetime(2026, 10, 1, 23, 0, tzinfo=_SHANGHAI)

    assert should_run(before_close, None) is False
    assert should_run(after_close, None) is True
    assert should_run(evening, None) is True
    # 当日已跑过 → 不再跑
    assert should_run(evening, date(2026, 10, 1)) is False
    # 次日再跑
    next_day = datetime(2026, 10, 2, 16, 0, tzinfo=_SHANGHAI)
    assert should_run(next_day, date(2026, 10, 1)) is True
    # UTC 输入也能正确换算（07:00 UTC = 15:00 Shanghai → 未到；07:01 UTC 之后到）
    assert should_run(datetime(2026, 10, 1, 7, 0, tzinfo=UTC), None) is False
    assert should_run(datetime(2026, 10, 1, 7, 36, tzinfo=UTC), None) is True


def test_run_at_constant_is_after_market_close() -> None:
    from mommy_chaogu.earnings.daily import RUN_AT

    assert time(15, 0) < RUN_AT


# ---------- Bark 推送接线（阶段五评审修复：生产 web 入口此前从未构造 notifier） ----------


def test_bark_notifier_built_when_device_key_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mommy_chaogu.push import BarkPusher, SignalNotifier
    from mommy_chaogu.web.app import _bark_notifier_if_configured

    monkeypatch.setenv("BARK_DEVICE_KEY", "test-device-key")
    notifier = _bark_notifier_if_configured(tmp_path / "p.db", "http://127.0.0.1:8000")

    assert isinstance(notifier, SignalNotifier)
    assert isinstance(notifier.pusher, BarkPusher)
    assert notifier.pusher.device_key == "test-device-key"
    assert notifier.pusher.web_base_url == "http://127.0.0.1:8000"


def test_bark_notifier_none_without_device_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mommy_chaogu.web.app import _bark_notifier_if_configured

    monkeypatch.delenv("BARK_DEVICE_KEY", raising=False)
    assert _bark_notifier_if_configured(tmp_path / "p.db", "") is None

    # 纯空白同样视为未配置
    monkeypatch.setenv("BARK_DEVICE_KEY", "   ")
    assert _bark_notifier_if_configured(tmp_path / "p.db", "") is None


def test_bark_notifier_dedup_file_lives_next_to_user_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """去重状态文件落用户库同目录 pushed.json（一码一规一天，不碰仓库 data/）。"""
    from mommy_chaogu.web.app import _bark_notifier_if_configured

    monkeypatch.setenv("BARK_DEVICE_KEY", "test-device-key")
    notifier = _bark_notifier_if_configured(tmp_path / "p.db", "")

    assert notifier is not None
    dedup_path = getattr(notifier.deduper, "db_path", None)
    assert dedup_path == tmp_path / "pushed.json"


# ---------- 信号持久化（边沿触发） ----------


def test_tick_persists_new_signals_on_edge_only(tmp_path: Path) -> None:
    """_tick 的信号必须落库（SignalStore + 文本日志），且只在「新增」时写。

    修复前 _tick 从不调 write_signals_log：信号只活在内存 latest_signals，
    web 历史页与 TUI /signals 永远为空（2026-10-09 实测 signal_events 0 行）。
    条件持续满足的第二个 tick 不得重复写（5s 一轮会一天万行）。
    """

    async def scenario() -> None:
        adapter = FakeAdapter({"600519": _make_quote("600519", "1700.00")})
        svc = _make_service(
            tmp_path / "s9",
            adapter=adapter,
            watchlist_entries=[],
            alerts=[("600519", "price_above", Decimal("1600"))],
            notifier=None,
        )
        written: list[Signal] = []
        svc.alerter.write_signals_log = lambda signals: written.extend(signals)  # type: ignore[method-assign]
        await svc._tick()
        assert len(written) == 1  # 首次触发 → 落库
        await svc._tick()
        assert len(written) == 1  # 条件持续满足 → 不重复写

    asyncio.run(scenario())
