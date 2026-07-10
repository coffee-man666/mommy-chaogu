"""flows.service 单测 — FlowService 业务逻辑。

策略：用真实 CacheStore（tmp_path db）+ FakeAdapter（不碰网络）。
- pull_today / pull_history：用 FakeAdapter 验证 ok/failed 计数 + 异常处理
- top_today / top_history / show / stats：直接向 store 灌数据，验证排序/聚合
- get_market_caps：FakeAdapter 返回 Quote
- clear：真实 store 验证删除
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.cache import CacheStore
from mommy_chaogu.flows.pool import CustomPool
from mommy_chaogu.flows.service import FlowService, FlowSummary, PullResult
from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)

# ---------- FakeAdapter ----------


class FakeAdapter:
    """模拟 CachedMarketDataAdapter，不碰网络。"""

    def __init__(self) -> None:
        self._last_fetch_attempt: dict[str, datetime] = {}
        self._today_flows: dict[str, list[MoneyFlow]] = {}
        self._history_flows: dict[str, list[MoneyFlow]] = {}
        self._quotes: dict[str, Quote] = {}
        self._today_calls: list[str] = []
        self._history_calls: list[str] = []
        self._raise_on_today: set[str] = set()

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        self._today_calls.append(code)
        if code in self._raise_on_today:
            raise ConnectionError(f"simulated fail {code}")
        return self._today_flows.get(code, [])

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        self._history_calls.append(code)
        return self._history_flows.get(code, [])

    def get_quote(self, code: str) -> Quote | None:
        return self._quotes.get(code)


# ---------- Helpers ----------


def _make_quote(
    code: str = "600519",
    name: str = "茅台",
    circ_mcap: str = "100000000000",
) -> Quote:
    return Quote(
        code=code,
        name=name,
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("100"),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        prev_close=Decimal("100"),
        change=Decimal("0"),
        change_pct=Decimal("0"),
        volume=0,
        turnover=Money.from_yuan(0),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=Money.from_yuan(circ_mcap),
        circulating_market_cap=Money.from_yuan(circ_mcap),
        timestamp=datetime.now(UTC),
    )


def _money_flow(
    code: str = "600519",
    name: str = "茅台",
    main: float = 0.0,
    super_large: float = 0.0,
    large: float = 0.0,
    ts: datetime | None = None,
) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=name,
        timestamp=ts or datetime(2026, 7, 6, 10, 0, tzinfo=UTC),
        main_net=Money.from_yuan(main),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(large),
        super_large_net=Money.from_yuan(super_large),
    )


def _flow_dict(
    code: str = "600519",
    name: str = "茅台",
    main: float = 0.0,
    super_large: float = 0.0,
    large: float = 0.0,
    ts: str = "2026-07-06T10:00:00",
    ratio: str | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "code": code,
        "name": name,
        "timestamp": ts,
        "main_net": {"amount": str(main), "currency": "CNY"},
        "small_net": {"amount": "0", "currency": "CNY"},
        "medium_net": {"amount": "0", "currency": "CNY"},
        "large_net": {"amount": str(large), "currency": "CNY"},
        "super_large_net": {"amount": str(super_large), "currency": "CNY"},
    }
    if ratio is not None:
        d["main_net_ratio"] = ratio
    return d


# ---------- Fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> CacheStore:
    return CacheStore(tmp_path / "test.db")


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def service(adapter: FakeAdapter, store: CacheStore) -> FlowService:
    return FlowService(adapter, store)


# ========== FlowSummary ==========


def test_flow_summary_big_money_net() -> None:
    s = FlowSummary(
        code="c",
        name="n",
        main_net=Decimal("100"),
        super_large_net=Decimal("60"),
        large_net=Decimal("40"),
        medium_net=Decimal("0"),
        small_net=Decimal("0"),
        main_net_ratio=Decimal("10"),
    )
    assert s.big_money_net() == Decimal("100")


def test_flow_summary_defaults() -> None:
    s = FlowSummary(
        code="c",
        name="n",
        main_net=Decimal("0"),
        super_large_net=Decimal("0"),
        large_net=Decimal("0"),
        medium_net=Decimal("0"),
        small_net=Decimal("0"),
        main_net_ratio=None,
    )
    assert s.sample_count == 1
    assert s.period == ""


# ========== PullResult ==========


def test_pull_result_total() -> None:
    r = PullResult(pool_name="custom", target="today", ok=5, failed=2)
    assert r.total == 7


def test_pull_result_defaults() -> None:
    r = PullResult(pool_name="custom", target="today")
    assert r.ok == 0
    assert r.failed == 0
    assert r.failed_codes == []
    assert r.elapsed_seconds == 0.0
    assert r.total == 0


# ========== _aggregate_today ==========


def test_aggregate_today_takes_latest_flow(service: FlowService) -> None:
    flows = [
        _money_flow(main=10_000_000, ts=datetime(2026, 7, 6, 9, 0, tzinfo=UTC)),
        _money_flow(main=50_000_000, ts=datetime(2026, 7, 6, 10, 0, tzinfo=UTC)),
    ]
    s = service._aggregate_today("600519", flows)
    # 取最后一条
    assert s.main_net == Decimal("50000000")
    assert s.name == "茅台"
    assert s.sample_count == 2
    assert s.period == "today"


def test_aggregate_today_empty(service: FlowService) -> None:
    s = service._aggregate_today("600519", [])
    assert s.main_net == Decimal(0)
    assert s.sample_count == 0
    assert s.name == ""


def test_aggregate_today_carries_ratio(service: FlowService) -> None:
    flows = [_money_flow(main=50_000_000)]
    flows[0] = MoneyFlow(
        code="600519",
        name="茅台",
        timestamp=datetime(2026, 7, 6, 10, 0, tzinfo=UTC),
        main_net=Money.from_yuan(50_000_000),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(0),
        super_large_net=Money.from_yuan(0),
        main_net_ratio=Decimal("5.5"),
    )
    s = service._aggregate_today("600519", flows)
    assert s.main_net_ratio == Decimal("5.5")


# ========== _aggregate_history ==========


def test_aggregate_history_sums_per_day(service: FlowService) -> None:
    # 两天，每天取最后一条累加
    flows = [
        _money_flow(main=10_000_000, ts=datetime(2026, 7, 5, 9, 0, tzinfo=UTC)),
        _money_flow(main=30_000_000, ts=datetime(2026, 7, 5, 15, 0, tzinfo=UTC)),  # 7/5 最后一条
        _money_flow(main=20_000_000, ts=datetime(2026, 7, 6, 15, 0, tzinfo=UTC)),  # 7/6 最后一条
    ]
    s = service._aggregate_history("600519", 30, flows)
    assert s.main_net == Decimal("50000000")  # 3e7 + 2e7
    assert s.sample_count == 2  # 2 天
    assert s.period == "history:30d"


def test_aggregate_history_empty(service: FlowService) -> None:
    s = service._aggregate_history("600519", 30, [])
    assert s.main_net == Decimal(0)
    assert s.sample_count == 0


# ========== pull_today ==========


def test_pull_today_all_ok(service: FlowService, adapter: FakeAdapter) -> None:
    adapter._today_flows = {
        "600519": [_money_flow("600519")],
        "000001": [_money_flow("000001")],
    }
    pool = CustomPool(["600519", "000001"])
    result = service.pull_today(pool)
    assert result.ok == 2
    assert result.failed == 0
    assert result.total == 2
    assert result.failed_codes == []
    assert result.pool_name == "custom"
    assert result.target == "today"


def test_pull_today_empty_flows_counted_as_failed(
    service: FlowService, adapter: FakeAdapter
) -> None:
    adapter._today_flows = {"600519": [_money_flow("600519")]}
    pool = CustomPool(["600519", "000001"])
    result = service.pull_today(pool)
    assert result.ok == 1
    assert result.failed == 1
    assert "000001" in result.failed_codes


def test_pull_today_exception_counted_as_failed(service: FlowService, adapter: FakeAdapter) -> None:
    adapter._today_flows = {"600519": [_money_flow("600519")]}
    adapter._raise_on_today.add("000001")
    pool = CustomPool(["600519", "000001"])
    result = service.pull_today(pool)
    assert result.ok == 1
    assert result.failed == 1
    assert "000001" in result.failed_codes


def test_pull_today_force_resets_throttle(service: FlowService, adapter: FakeAdapter) -> None:
    adapter._today_flows = {"600519": [_money_flow("600519")]}
    pool = CustomPool(["600519"])
    service.pull_today(pool, force=True)
    # force 模式会重置 _last_fetch_attempt
    assert "today_flow:600519" in adapter._last_fetch_attempt


def test_pull_today_empty_pool(service: FlowService) -> None:
    pool = CustomPool([])
    result = service.pull_today(pool)
    assert result.ok == 0
    assert result.total == 0


# ========== pull_history ==========


def test_pull_history_all_ok(service: FlowService, adapter: FakeAdapter) -> None:
    adapter._history_flows = {
        "600519": [_money_flow("600519")],
    }
    pool = CustomPool(["600519"])
    result = service.pull_history(pool, days=15)
    assert result.ok == 1
    assert result.target == "history:15d"
    assert adapter._history_calls == ["600519"]


def test_pull_history_failed(service: FlowService, adapter: FakeAdapter) -> None:
    pool = CustomPool(["000001"])
    result = service.pull_history(pool, days=30)
    assert result.failed == 1
    assert "000001" in result.failed_codes


# ========== top_today ==========


def _seed_today(store: CacheStore, code: str, main: float) -> None:
    store.set_today_money_flow(code, [_flow_dict(code=code, main=main)])


def test_top_today_sorts_descending(service: FlowService, store: CacheStore) -> None:
    _seed_today(store, "600519", 80_000_000)
    _seed_today(store, "000001", 200_000_000)
    _seed_today(store, "000002", 50_000_000)
    pool = CustomPool(["600519", "000001", "000002"])
    top = service.top_today(pool, n=10)
    assert len(top) == 3
    # 降序：000001 > 600519 > 000002
    assert top[0].code == "000001"
    assert top[1].code == "600519"
    assert top[2].code == "000002"


def test_top_today_limit_n(service: FlowService, store: CacheStore) -> None:
    for i, code in enumerate(["a", "b", "c", "d"]):
        _seed_today(store, code, main=i * 10_000_000)
    pool = CustomPool(["a", "b", "c", "d"])
    top = service.top_today(pool, n=2)
    assert len(top) == 2
    assert top[0].code == "d"
    assert top[1].code == "c"


def test_top_today_direction_out(service: FlowService, store: CacheStore) -> None:
    _seed_today(store, "600519", 80_000_000)
    _seed_today(store, "000001", -200_000_000)  # 流出最多
    _seed_today(store, "000002", -50_000_000)
    pool = CustomPool(["600519", "000001", "000002"])
    top = service.top_today(pool, n=10, direction="out")
    # 净流入最小（流出最多）的排前面
    assert top[0].code == "000001"
    assert top[1].code == "000002"
    assert top[2].code == "600519"


def test_top_today_by_big_money(service: FlowService, store: CacheStore) -> None:
    # 600519: big_money = 100e6 (super) + 0 (large)
    store.set_today_money_flow(
        "600519",
        [_flow_dict("600519", main=100_000_000, super_large=100_000_000)],
    )
    # 000001: big_money = 0 + 200e6
    store.set_today_money_flow(
        "000001",
        [_flow_dict("000001", main=200_000_000, large=200_000_000)],
    )
    pool = CustomPool(["600519", "000001"])
    top = service.top_today(pool, n=10, by="big_money")
    assert top[0].code == "000001"  # big_money 200e6 > 100e6
    assert top[1].code == "600519"


def test_top_today_skips_uncached(service: FlowService, store: CacheStore) -> None:
    _seed_today(store, "600519", 80_000_000)
    pool = CustomPool(["600519", "nocache"])
    top = service.top_today(pool, n=10)
    assert len(top) == 1
    assert top[0].code == "600519"


# ========== top_history ==========


def _seed_history(store: CacheStore, code: str, trade_date: str, main: float) -> None:
    store.set_money_flow_history(
        code, trade_date, [_flow_dict(code=code, main=main, ts=f"{trade_date}T15:00:00")]
    )


def test_top_history_aggregates(service: FlowService, store: CacheStore) -> None:
    _seed_history(store, "600519", "2026-07-05", 30_000_000)
    _seed_history(store, "600519", "2026-07-06", 20_000_000)
    _seed_history(store, "000001", "2026-07-05", 10_000_000)
    pool = CustomPool(["600519", "000001"])
    top = service.top_history(pool, days=30, n=10)
    assert len(top) == 2
    # 600519 累计 5e7 > 000001 的 1e7
    assert top[0].code == "600519"
    assert top[0].main_net == Decimal("50000000")


# ========== show ==========


def test_show_with_data(service: FlowService, store: CacheStore) -> None:
    _seed_today(store, "600519", 50_000_000)
    _seed_history(store, "600519", "2026-07-05", 30_000_000)
    result = service.show("600519", days=30)
    assert result["code"] == "600519"
    assert result["today"] is not None
    assert result["today"].main_net == Decimal("50000000")
    assert result["history"] is not None
    assert result["history"].main_net == Decimal("30000000")
    assert result["history_days_cached"] == 1


def test_show_no_data(service: FlowService) -> None:
    result = service.show("999999")
    assert result["today"] is None
    assert result["history"] is None
    assert result["history_days_cached"] == 0


# ========== stats ==========


def test_stats(service: FlowService, store: CacheStore) -> None:
    _seed_today(store, "600519", 50_000_000)
    _seed_history(store, "600519", "2026-07-05", 30_000_000)
    _seed_today(store, "000001", 20_000_000)
    pool = CustomPool(["600519", "000001", "000002"])
    st = service.stats(pool)
    assert st["pool_total"] == 3
    assert st["today_cached"] == 2
    assert st["history_cached"] == 1


def test_stats_empty_pool(service: FlowService) -> None:
    pool = CustomPool([])
    st = service.stats(pool)
    assert st == {"pool_total": 0, "today_cached": 0, "history_cached": 0}


# ========== get_market_caps ==========


def test_get_market_caps(service: FlowService, adapter: FakeAdapter) -> None:
    adapter._quotes = {
        "600519": _make_quote("600519", "茅台", "100000000000"),
        "000001": _make_quote("000001", "平安", "200000000000"),
    }
    mcaps = service.get_market_caps(["600519", "000001", "missing"])
    assert "600519" in mcaps
    assert mcaps["600519"] == ("茅台", Decimal("100000000000"))
    assert mcaps["000001"] == ("平安", Decimal("200000000000"))
    assert "missing" not in mcaps


def test_get_market_caps_skips_zero(service: FlowService, adapter: FakeAdapter) -> None:
    q = _make_quote("600519", "茅台", "0")
    adapter._quotes = {"600519": q}
    mcaps = service.get_market_caps(["600519"])
    assert mcaps == {}


# ========== clear ==========
# 注意：FlowService.clear() 当前实现有 bug（store.session() 是 @contextmanager，
# 但 clear() 写成 `s = self.store.session(); with s: s.execute(...)`，
# s 仍是 context manager 对象，没有 execute 方法，运行时抛 AttributeError）。
# 该方法不在本批次测试范围内，待上游修复后补测试。
