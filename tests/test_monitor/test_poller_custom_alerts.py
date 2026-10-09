"""阶段五：Monitor.run / monitor snapshot 的自定义告警旁挂评估。

覆盖：
- 告警代码不在自选股（Snapshot 行外）→ 经 adapter 补拉报价后评估
- 命中信号走 alerter.format_signals / write_signals_log 既有输出路径
- 环境变量 MOMMY_ALERTS_BUILTIN_ONLY 一键停用
- cmd_monitor_snapshot --with-signals 分支（第三处 alerter.evaluate 调用点）
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)
from mommy_chaogu.monitor import Monitor
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.signals.custom_evaluation import MOMMY_ALERTS_BUILTIN_ONLY_ENV
from mommy_chaogu.watchlist import WatchlistStore


class MockMarketDataAdapter:
    """测试用 mock adapter（与 test_poller.py 同构，可预设报价）。"""

    def __init__(self, quotes: dict[str, Quote] | None = None) -> None:
        self.name = "mock"
        self._quotes = quotes or {}

    def get_quote(self, code: str) -> Quote | None:
        return self._quotes.get(code)

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        return [q for c in codes if (q := self._quotes.get(c)) is not None]

    def list_market_quotes(self) -> list[Quote]:
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
        timestamp=datetime.now(),
    )


def _setup(
    tmp_path: Path, alert_code: str, threshold: str
) -> tuple[WatchlistStore, CustomAlertStore]:
    wl = WatchlistStore(tmp_path / "portfolio.db")
    wl.get_or_create_group("默认")
    wl.add_entry("600519", "默认")
    alerts = CustomAlertStore(tmp_path / "portfolio.db")
    alerts.add(alert_code, f"名称{alert_code}", "price_above", Decimal(threshold))
    return wl, alerts


# ---------- Monitor.run 循环 ----------


def test_run_evaluates_custom_alert_outside_watchlist(tmp_path: Path) -> None:
    """告警代码 000001 不在自选股 → 仍被评估并出现在信号输出里。"""
    from mommy_chaogu.signals import Alerter

    wl, alerts = _setup(tmp_path, alert_code="000001", threshold="10")
    adapter = MockMarketDataAdapter(
        quotes={
            "600519": _make_quote("600519", "100"),
            "000001": _make_quote("000001", "10.27"),
        }
    )
    stream = io.StringIO()
    signals_log = tmp_path / "signals.log"
    m = Monitor(
        wl,
        adapter,
        stream=stream,
        alerter=Alerter.default(log_path=signals_log),
        custom_alerts=alerts,
    )
    m.run(interval_seconds=0, max_iterations=1, clear_screen=False)

    out = stream.getvalue()
    assert "000001" in out
    assert "价格上穿" in out
    # 信号日志同样落了自定义告警
    log_text = signals_log.read_text(encoding="utf-8")
    assert "000001" in log_text
    assert "自定义告警" in log_text


def test_run_custom_alert_not_triggered(tmp_path: Path) -> None:
    from mommy_chaogu.signals import Alerter

    wl, alerts = _setup(tmp_path, alert_code="000001", threshold="99")
    adapter = MockMarketDataAdapter(
        quotes={
            "600519": _make_quote("600519", "100"),
            "000001": _make_quote("000001", "10.27"),
        }
    )
    stream = io.StringIO()
    m = Monitor(
        wl,
        adapter,
        stream=stream,
        alerter=Alerter.default(),
        custom_alerts=alerts,
    )
    m.run(interval_seconds=0, max_iterations=1, clear_screen=False)

    out = stream.getvalue()
    assert "价格上穿" not in out


def test_run_env_switch_disables_custom_alerts(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from mommy_chaogu.signals import Alerter

    monkeypatch.setenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "1")
    wl, alerts = _setup(tmp_path, alert_code="000001", threshold="10")
    adapter = MockMarketDataAdapter(
        quotes={
            "600519": _make_quote("600519", "100"),
            "000001": _make_quote("000001", "10.27"),
        }
    )
    stream = io.StringIO()
    m = Monitor(
        wl,
        adapter,
        stream=stream,
        alerter=Alerter.default(),
        custom_alerts=alerts,
    )
    m.run(interval_seconds=0, max_iterations=1, clear_screen=False)

    assert "价格上穿" not in stream.getvalue()


def test_run_without_custom_alerts_store_unchanged(tmp_path: Path) -> None:
    """不注入 custom_alerts（旧用法）→ 行为与从前一致，不报错。"""
    from mommy_chaogu.signals import Alerter

    wl = WatchlistStore(tmp_path / "portfolio.db")
    wl.get_or_create_group("默认")
    wl.add_entry("600519", "默认")
    adapter = MockMarketDataAdapter(quotes={"600519": _make_quote("600519", "100")})
    stream = io.StringIO()
    m = Monitor(wl, adapter, stream=stream, alerter=Alerter.default())
    m.run(interval_seconds=0, max_iterations=1, clear_screen=False)
    assert "600519" in stream.getvalue()


# ---------- cmd_monitor_snapshot --with-signals（第三处调用点） ----------


def test_cmd_monitor_snapshot_with_signals_evaluates_custom_alerts(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from mommy_chaogu.cli_commands import monitor as monitor_cli

    _wl, alerts = _setup(tmp_path, alert_code="000001", threshold="10")
    assert len(alerts.list_all()) == 1

    adapter = MockMarketDataAdapter(
        quotes={
            "600519": _make_quote("600519", "100"),
            "000001": _make_quote("000001", "10.27"),
        }
    )
    monkeypatch.setattr(monitor_cli, "_make_adapter", lambda _args: adapter)

    args = SimpleNamespace(
        db=str(tmp_path / "portfolio.db"),
        log=str(tmp_path / "monitor.log"),
        signals_log=str(tmp_path / "signals.log"),
        with_signals=True,
    )

    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = monitor_cli.cmd_monitor_snapshot(args)  # type: ignore[arg-type]

    assert rc == 0
    out = buf.getvalue()
    assert "000001" in out
    assert "价格上穿" in out
    # 信号日志落库（自定义告警命中写入 signals.log；文本行含 code 与 detail）
    log_text = (tmp_path / "signals.log").read_text(encoding="utf-8")
    assert "000001" in log_text
    assert "自定义告警" in log_text


def test_cmd_monitor_snapshot_env_switch_disables_custom_alerts(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from mommy_chaogu.cli_commands import monitor as monitor_cli

    monkeypatch.setenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "1")
    _wl, alerts = _setup(tmp_path, alert_code="000001", threshold="10")
    assert len(alerts.list_all()) == 1

    adapter = MockMarketDataAdapter(
        quotes={
            "600519": _make_quote("600519", "100"),
            "000001": _make_quote("000001", "10.27"),
        }
    )
    monkeypatch.setattr(monitor_cli, "_make_adapter", lambda _args: adapter)

    args = SimpleNamespace(
        db=str(tmp_path / "portfolio.db"),
        log=str(tmp_path / "monitor.log"),
        signals_log=str(tmp_path / "signals.log"),
        with_signals=True,
    )

    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = monitor_cli.cmd_monitor_snapshot(args)  # type: ignore[arg-type]

    assert rc == 0
    assert "价格上穿" not in buf.getvalue()
