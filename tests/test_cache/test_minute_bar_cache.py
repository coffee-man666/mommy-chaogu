"""bar_cache 分钟同日坍缩修复的离线单测（阶段六任务 1，方案 A）。

坍缩复现用例：Fake 分钟源同日多根 5m K 落库后完整读回——修复前同日
多根共用主键 (code, interval, adj_type, trade_date)，最后一根胜出，第二次
（缓存命中路径）只回 1 根；修复后按日打包为单行 JSON，完整读回。

同时覆盖：日线缓存路径零回归、部分日写入合并不丢早段、存量坍缩行
（dict 形态）读取兼容、backfill 分钟周期支持、口径标签诚实性（不复权
数据经缓存层不得被改标为请求口径——阶段六评审意见）。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from mommy_chaogu.cache import CacheConfig, CachedMarketDataAdapter, CacheStore
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money

CODE = "600519"
ADJ = AdjustmentType.FORWARD


def _m5_bar(
    ts: datetime, close: str = "100.00", volume: int = 1000, adj: AdjustmentType = ADJ
) -> Bar:
    """北京 09:30-15:05 之间的 5m K（aware UTC 表达，与生产路径一致）。"""
    return Bar(
        code=CODE,
        name="贵州茅台",
        interval=BarInterval.M5,
        adjustment=adj,
        timestamp=ts,
        open=Decimal("100.00"),
        high=Decimal(close) + Decimal("1"),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=volume,
        turnover=Money.from_yuan(100_000),
    )


class FakeMinuteAdapter:
    """可预设 5m K 返回值的假分钟源（零网络）。"""

    name = "fake-minute"

    def __init__(self) -> None:
        self.bars: list[Bar] = []
        self.bars_calls: list[dict[str, Any]] = []
        self.flow_calls: list[dict[str, Any]] = []

    def get_quote(self, code: str) -> None:
        return None

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        self.bars_calls.append(
            {"code": code, "interval": interval, "start": start, "end": end, "limit": limit}
        )
        return list(self.bars)

    def get_history_money_flow(self, code: str, days: int = 30) -> list[Any]:
        self.flow_calls.append({"code": code, "days": days})
        return []


@pytest.fixture
def store(tmp_path: Path) -> CacheStore:
    return CacheStore(tmp_path / "test.db")


@pytest.fixture
def fake() -> FakeMinuteAdapter:
    return FakeMinuteAdapter()


@pytest.fixture
def cached(store: CacheStore, fake: FakeMinuteAdapter) -> CachedMarketDataAdapter:
    # bar 默认节流 1 天：第二次调用走纯缓存路径，正是坍缩暴露的路径
    return CachedMarketDataAdapter(fake, store, config=CacheConfig())


def _same_day_4_bars() -> list[Bar]:
    """2026-09-30 同日 4 根 5m（北京 09:30/09:35/09:40/09:45 → UTC 01:30..）。"""
    base = datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
    return [
        _m5_bar(base, "10.01"),
        _m5_bar(base + timedelta(minutes=5), "10.02"),
        _m5_bar(base + timedelta(minutes=10), "10.03"),
        _m5_bar(base + timedelta(minutes=15), "10.04"),
    ]


# ---------- 坍缩复现用例（阶段六验收的直接复现）----------


def test_minute_bars_same_day_roundtrip_after_throttle(
    cached: CachedMarketDataAdapter, fake: FakeMinuteAdapter
) -> None:
    """同日 4 根 5m 落库后，节流窗口内读缓存必须完整回 4 根。

    修复前：4 根共用同一 trade_date 主键，最后一根胜出，第二次只回 1 根。
    """
    fake.bars = _same_day_4_bars()

    first = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert len(first) == 4  # 无缓存路径直接返回 fresh

    # 节流窗口内二次调用 → 纯缓存路径（坍缩暴露点）
    second = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert len(second) == 4
    assert [b.close for b in second] == [
        Decimal("10.01"),
        Decimal("10.02"),
        Decimal("10.03"),
        Decimal("10.04"),
    ]
    assert [b.timestamp for b in second] == sorted(b.timestamp for b in second)
    assert fake.bars_calls[-1]["interval"] == BarInterval.M5


def test_minute_day_packed_into_single_row(
    store: CacheStore, cached: CachedMarketDataAdapter, fake: FakeMinuteAdapter
) -> None:
    """方案 A：同日整段序列打包为单行（bar_cache 只有一行，bar_json 是 list）。"""
    fake.bars = _same_day_4_bars()
    cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)

    assert store.stats()["bars"] == 1
    with store.session() as s:
        row = s.execute(
            text("SELECT bar_json FROM bar_cache WHERE code = :c"),
            {"c": CODE},
        ).first()
    assert row is not None

    packed = json.loads(row[0])
    assert isinstance(packed, list)
    assert len(packed) == 4


def test_minute_partial_refetch_merges_not_truncates(
    store: CacheStore, cached: CachedMarketDataAdapter, fake: FakeMinuteAdapter
) -> None:
    """节流到期增量拉新只回当日尾段（limit 截断）时，已缓存的早段不丢。"""
    fake.bars = _same_day_4_bars()
    cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)

    # 模拟下一次拉新只拿到最后 2 根（部分日写入）
    fake.bars = _same_day_4_bars()[2:]
    key = f"bar:{CODE}:{BarInterval.M5.value}:{ADJ.value}"
    cached._last_fetch_attempt[key] = datetime.now(UTC) - timedelta(seconds=90_000)

    bars = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert len(bars) == 4  # 合并：早段 2 根 + 新尾段 2 根
    assert [b.close for b in bars][-2:] == [Decimal("10.03"), Decimal("10.04")]


def test_minute_throttle_window_is_minutes_not_days(
    store: CacheStore, fake: FakeMinuteAdapter
) -> None:
    """分钟节流窗口独立（默认 5 分钟）：盘中重复询问能拿到当日最新段。

    日线窗口（86400s）会把上午的部分日快照冻结到收盘——分钟必须更短。
    """
    cached = CachedMarketDataAdapter(fake, store, config=CacheConfig())
    fake.bars = _same_day_4_bars()[:2]
    cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    calls_after_first = len(fake.bars_calls)

    key = f"bar:{CODE}:{BarInterval.M5.value}:{ADJ.value}"
    # 400 秒前：超过分钟窗口（300s）→ 重拉新（盘中演进，拿到完整 4 根）
    fake.bars = _same_day_4_bars()
    cached._last_fetch_attempt[key] = datetime.now(UTC) - timedelta(seconds=400)
    bars = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert len(fake.bars_calls) == calls_after_first + 1
    assert len(bars) == 4

    # 对照：日线同 400 秒仍在 86400s 窗口内 → 不重拉
    fake.bars = [
        Bar(
            code=CODE,
            name="贵州茅台",
            interval=BarInterval.D1,
            adjustment=ADJ,
            timestamp=datetime(2026, 1, 5, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            turnover=Money.from_yuan(100_000),
        )
    ]
    cached.get_bars(CODE, interval=BarInterval.D1, adjustment=ADJ)
    d1_calls = len(fake.bars_calls)
    d1_key = f"bar:{CODE}:{BarInterval.D1.value}:{ADJ.value}"
    cached._last_fetch_attempt[d1_key] = datetime.now(UTC) - timedelta(seconds=400)
    cached.get_bars(CODE, interval=BarInterval.D1, adjustment=ADJ)
    assert len(fake.bars_calls) == d1_calls  # 日线不重拉（既有语义不变）


def test_minute_hit_path_never_shrinks_below_fresh(
    store: CacheStore,
    cached: CachedMarketDataAdapter,
    fake: FakeMinuteAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缓存命中路径的防坍缩兜底：持久化失败时不得用残缺缓存覆盖 fresh。"""
    fake.bars = _same_day_4_bars()[:2]  # 先只落 2 根
    cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)

    fake.bars = _same_day_4_bars()  # 拉新拿到完整 4 根
    key = f"bar:{CODE}:{BarInterval.M5.value}:{ADJ.value}"
    cached._last_fetch_attempt[key] = datetime.now(UTC) - timedelta(seconds=90_000)
    # 模拟写入失败（数据库异常）：重读缓存仍是旧的 2 根
    monkeypatch.setattr(
        cached.store,
        "set_minute_bars",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated store failure")),
    )

    bars = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert len(bars) == 4  # 用 fresh，绝不用残缺缓存覆盖


def test_store_reads_legacy_collapsed_minute_row(store: CacheStore) -> None:
    """存量坍缩行（dict 形态）读取兼容：不炸、按单根返回。"""
    legacy = {
        "code": CODE,
        "name": "贵州茅台",
        "timestamp": "2026-09-29T06:55:00+00:00",
        "interval": "5m",
        "adjustment": "forward",
        "open": "100.00",
        "high": "101.00",
        "low": "99.00",
        "close": "100.50",
        "volume": 1000,
        "turnover": "100000",
    }
    with store.session() as s:
        s.execute(
            text("""
                INSERT INTO bar_cache (code, interval, adj_type, trade_date, bar_json, fetched_at)
                VALUES (:c, :i, :a, :d, :j, :f)
            """),
            {
                "c": CODE,
                "i": "5m",
                "a": "forward",
                "d": "2026-09-29",
                "j": json.dumps(legacy),
                "f": datetime.now(UTC),
            },
        )
    rows = store.get_bars(CODE, "5m", "forward")
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["close"] == "100.50"


def test_store_set_bar_minute_merges_same_day(store: CacheStore) -> None:
    """逐根 set_bar（旧调用方式）在分钟周期下也合并进同一打包行。"""
    bars = _same_day_4_bars()
    for bar in bars:
        d = bar.timestamp.strftime("%Y-%m-%d")
        store.set_bar(
            CODE,
            BarInterval.M5.value,
            ADJ.value,
            d,
            {"timestamp": bar.timestamp.isoformat(), "close": str(bar.close)},
        )
    rows = store.get_bars(CODE, BarInterval.M5.value, ADJ.value)
    assert rows is not None
    assert len(rows) == 4
    assert store.stats()["bars"] == 1


# ---------- 日线路径零回归 ----------


def test_daily_cache_path_unchanged(
    store: CacheStore, cached: CachedMarketDataAdapter, fake: FakeMinuteAdapter
) -> None:
    """日线：同日单根、一行一 K 的既有语义不变（最后一根覆盖）。"""
    day = datetime(2026, 1, 5, tzinfo=UTC)
    fake.bars = [
        Bar(
            code=CODE,
            name="贵州茅台",
            interval=BarInterval.D1,
            adjustment=ADJ,
            timestamp=day,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            turnover=Money.from_yuan(100_000),
        )
    ]
    bars = cached.get_bars(CODE, interval=BarInterval.D1, adjustment=ADJ)
    assert len(bars) == 1
    second = cached.get_bars(CODE, interval=BarInterval.D1, adjustment=ADJ)
    assert len(second) == 1
    # 日线口径语义不变：源兑现请求复权（bar.adjustment == 请求）→ 两次调用
    # 标签均为请求口径；行键 = 请求口径（不并集、不分键）
    assert {b.adjustment for b in bars} == {b.adjustment for b in second} == {ADJ}
    with store.session() as s:
        row = s.execute(text("SELECT bar_json FROM bar_cache")).first()

    assert not isinstance(json.loads(row[0]), list)  # 日线仍为 dict 单行


# ---------- backfill 分钟周期支持 ----------


def test_backfill_minute_interval_packs_by_day(store: CacheStore, fake: FakeMinuteAdapter) -> None:
    day1 = [  # 2026-09-29 全日 2 根
        _m5_bar(datetime(2026, 9, 29, 1, 30, tzinfo=UTC), "10.00"),
        _m5_bar(datetime(2026, 9, 29, 1, 35, tzinfo=UTC), "10.01"),
    ]
    day2 = [  # 2026-09-30 全日 3 根
        _m5_bar(datetime(2026, 9, 30, 1, 30, tzinfo=UTC), "10.02"),
        _m5_bar(datetime(2026, 9, 30, 1, 35, tzinfo=UTC), "10.03"),
        _m5_bar(datetime(2026, 9, 30, 1, 40, tzinfo=UTC), "10.04"),
    ]
    fake.bars = day1 + day2

    result = store.backfill_history(fake, CODE, days=5, interval=BarInterval.M5)

    assert result["interval"] == "5m"
    assert result["bars_written"] == 5
    assert result["flows_written"] == 0
    assert fake.flow_calls == []  # 分钟回填不拉资金流（天级数据）
    # 两个交易日各打包一行
    assert store.stats()["bars"] == 2
    rows = store.get_bars(CODE, BarInterval.M5.value, ADJ.value)
    assert rows is not None
    assert len(rows) == 5


def test_backfill_daily_still_fetches_flows(store: CacheStore, fake: FakeMinuteAdapter) -> None:
    """日线回填仍拉历史资金流（既有行为零回归）。"""

    class FlowFake(FakeMinuteAdapter):
        def get_history_money_flow(self, code: str, days: int = 30) -> list[Any]:
            super().get_history_money_flow(code, days=days)
            from mommy_chaogu.market_data.types import MoneyFlow

            return [
                MoneyFlow(
                    code=code,
                    name="贵州茅台",
                    timestamp=datetime(2026, 1, 5, tzinfo=UTC),
                    main_net=Money.from_yuan(1),
                    small_net=Money.from_yuan(0),
                    medium_net=Money.from_yuan(0),
                    large_net=Money.from_yuan(0),
                    super_large_net=Money.from_yuan(0),
                )
            ]

    flow_fake = FlowFake()
    flow_fake.bars = [
        Bar(
            code=CODE,
            name="贵州茅台",
            interval=BarInterval.D1,
            adjustment=ADJ,
            timestamp=datetime(2026, 1, 5, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            turnover=Money.from_yuan(100_000),
        )
    ]
    result = store.backfill_history(flow_fake, CODE, days=30)
    assert result["interval"] == "1d"
    assert result["bars_written"] == 1
    assert result["flows_written"] == 1
    assert flow_fake.flow_calls == [{"code": CODE, "days": 30}]


# ---------- 口径标签诚实性（阶段六评审意见：不复权数据不得改标请求口径）----------


def test_unadjusted_minute_bars_keep_none_label_and_key(
    store: CacheStore, fake: FakeMinuteAdapter
) -> None:
    """腾讯式源（无视请求复权、返回 NONE）经缓存层不改标。

    修复前：_bar_to_cache_dict 无条件用请求口径覆盖，fresh 返回 none、
    缓存读回变 forward，且行键落在 (code,5m,forward)——东财前复权数据
    会与腾讯不复权数据合并进同一打包行。
    """
    cached = CachedMarketDataAdapter(fake, store, config=CacheConfig())
    base = datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
    fake.bars = [
        _m5_bar(base + timedelta(minutes=5 * i), f"10.0{i}", adj=AdjustmentType.NONE)
        for i in range(4)
    ]

    first = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)  # 请求 forward
    second = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)  # 节流内读缓存

    assert len(first) == len(second) == 4
    assert {b.adjustment for b in first} == {AdjustmentType.NONE}
    assert {b.adjustment for b in second} == {AdjustmentType.NONE}  # 不再改标 forward

    with store.session() as s:
        keys = [r[0] for r in s.execute(text("SELECT DISTINCT adj_type FROM bar_cache")).all()]
        rows = s.execute(text("SELECT bar_json FROM bar_cache")).all()
    assert keys == ["none"]  # 落库键 = bar 自身口径，与东财 forward 键分键互不覆盖
    for (bar_json,) in rows:
        assert {b["adjustment"] for b in json.loads(bar_json)} == {"none"}


def _raw_bar_dict(ts: datetime, close: str, adj: str) -> dict[str, Any]:
    return {
        "code": CODE,
        "name": "贵州茅台",
        "timestamp": ts.isoformat(),
        "interval": "5m",
        "adjustment": adj,
        "open": "100.00",
        "high": "101.00",
        "low": "99.00",
        "close": close,
        "volume": 1000,
        "turnover": "100000",
    }


def test_minute_union_read_merges_adjustment_keys(
    store: CacheStore, cached: CachedMarketDataAdapter, fake: FakeMinuteAdapter
) -> None:
    """分钟读侧并集：请求 forward 时，forward 行 + none 行按时间合并，
    每根保留自身口径标签；同时间戳两键都有时请求口径优先。"""
    ts_fwd = datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
    ts_none = datetime(2026, 9, 30, 1, 35, tzinfo=UTC)
    store.set_minute_bars(
        CODE, "5m", "forward", "2026-09-30", [_raw_bar_dict(ts_fwd, "10.01", "forward")]
    )
    store.set_minute_bars(
        CODE, "5m", "none", "2026-09-30", [_raw_bar_dict(ts_none, "10.02", "none")]
    )
    key = f"bar:{CODE}:5m:{ADJ.value}"
    cached._last_fetch_attempt[key] = datetime.now(UTC)  # 纯缓存路径

    bars = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert [(b.timestamp, b.adjustment) for b in bars] == [
        (ts_fwd, AdjustmentType.FORWARD),
        (ts_none, AdjustmentType.NONE),
    ]

    # 同时间戳两键并存 → 请求口径（forward）优先
    store.set_minute_bars(CODE, "5m", "none", "2026-09-30", [_raw_bar_dict(ts_fwd, "9.99", "none")])
    bars2 = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    fwd_bars = [b for b in bars2 if b.timestamp == ts_fwd]
    assert len(fwd_bars) == 1
    assert fwd_bars[0].adjustment == AdjustmentType.FORWARD
    assert fwd_bars[0].close == Decimal("10.01")


def test_minute_guard_keeps_own_adjustment_labels(
    store: CacheStore,
    cached: CachedMarketDataAdapter,
    fake: FakeMinuteAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防坍缩兜底路径也不改标：持久化失败用 fresh 时，标签保持 bar 自身口径。"""
    base = datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
    fake.bars = [
        _m5_bar(base, "10.00", adj=AdjustmentType.NONE),
        _m5_bar(base + timedelta(minutes=5), "10.01", adj=AdjustmentType.NONE),
    ]
    cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)

    fake.bars = [
        _m5_bar(base + timedelta(minutes=5 * i), f"10.0{i}", adj=AdjustmentType.NONE)
        for i in range(4)
    ]
    key = f"bar:{CODE}:5m:{ADJ.value}"
    cached._last_fetch_attempt[key] = datetime.now(UTC) - timedelta(seconds=90_000)
    monkeypatch.setattr(
        cached.store,
        "set_minute_bars",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated store failure")),
    )

    bars = cached.get_bars(CODE, interval=BarInterval.M5, adjustment=ADJ)
    assert len(bars) == 4
    assert {b.adjustment for b in bars} == {AdjustmentType.NONE}


def test_backfill_minute_keys_by_bar_own_adjustment(
    store: CacheStore, fake: FakeMinuteAdapter
) -> None:
    """backfill 分钟：NONE 口径源落 none 键（与请求的 forward 键无关）。"""
    base = datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
    fake.bars = [
        _m5_bar(base, "10.00", adj=AdjustmentType.NONE),
        _m5_bar(base + timedelta(minutes=5), "10.01", adj=AdjustmentType.NONE),
    ]
    result = store.backfill_history(fake, CODE, days=5, interval=BarInterval.M5)
    assert result["bars_written"] == 2
    rows = store.get_bars(CODE, "5m", "none")
    assert rows is not None
    assert len(rows) == 2
    assert store.get_bars(CODE, "5m", ADJ.value) is None  # forward 键无行
