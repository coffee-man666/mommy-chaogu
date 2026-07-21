"""缓存层单测 — MockMarketDataAdapter + tmp_path db。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.cache import (
    CacheConfig,
    CachedMarketDataAdapter,
    CacheStore,
)
from mommy_chaogu.market_data import (
    MarketDataAdapter,
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)

# ---------- Mock Adapter ----------


class MockAdapter:
    """可预设行为：quote 返回值 + fetch 异常次数。"""

    def __init__(self, quotes: dict[str, Quote] | None = None) -> None:
        self.name = "mock"
        self._quotes = quotes or {}
        self.fetch_count = 0
        self.fail_count = 0
        self.fail_until_attempt = 0  # 拉新前 N 次失败
        self._attempt = 0

    def get_quote(self, code: str) -> Quote | None:
        self._attempt += 1
        self.fetch_count += 1
        if self._attempt <= self.fail_until_attempt:
            self.fail_count += 1
            raise ConnectionError(f"simulated fetch fail #{self._attempt}")
        return self._quotes.get(code)

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        return [q for c in codes if (q := self._quotes.get(c)) is not None]

    def list_market_quotes(self) -> list[Quote]:
        self.fetch_count += 1
        return list(self._quotes.values())

    def get_order_book(self, code: str):
        return None

    def get_bars(self, code: str, **kw):
        return []

    def get_ticks(self, code: str, limit=None):
        return []

    def get_today_money_flow(self, code: str):
        self.fetch_count += 1
        return []

    def get_history_money_flow(self, code: str, days: int = 30):
        return []

    def get_belonging_boards(self, code: str):
        return []

    def health_check(self) -> bool:
        return len(self._quotes) > 0


def _make_quote(code: str = "600519", price: str = "1184.98", pct: str = "0.08") -> Quote:
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
        volume=31877,
        turnover=Money.from_yuan(3781470336),
        turnover_rate=Decimal("0.25"),
        volume_ratio=Decimal("1.19"),
        pe_dynamic=Decimal("13.59"),
        total_market_cap=Money.from_yuan(1481321695553),
        circulating_market_cap=Money.from_yuan(1481321695553),
        timestamp=datetime.now(UTC),
    )


# ---------- Fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> CacheStore:
    return CacheStore(tmp_path / "test.db")


@pytest.fixture
def mock_adp() -> MockAdapter:
    return MockAdapter(quotes={"600519": _make_quote("600519")})


@pytest.fixture
def cached(store: CacheStore, mock_adp: MockAdapter) -> CachedMarketDataAdapter:
    # 短间隔方便测试
    cfg = CacheConfig(
        quote_fetch_interval_seconds=60,
        today_money_flow_fetch_interval_seconds=60,
        market_snapshot_fetch_interval_seconds=60,
    )
    return CachedMarketDataAdapter(mock_adp, store, config=cfg)


# ---------- Protocol & basic ----------


def test_cached_satisfies_protocol(cached: CachedMarketDataAdapter) -> None:
    assert isinstance(cached, MarketDataAdapter)
    assert cached.name.startswith("cached(")


def test_get_quote_first_call_fetches(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    q = cached.get_quote("600519")
    assert q is not None
    assert q.code == "600519"
    assert mock_adp.fetch_count == 1
    assert cached.stats_counters["fetch_ok"] == 1


def test_get_quote_second_call_within_interval_hits_cache(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    cached.get_quote("600519")  # 拉新
    q = cached.get_quote("600519")  # 应该命中缓存
    assert q is not None
    assert mock_adp.fetch_count == 1  # 没有再次 fetch
    assert cached.stats_counters["hits"] == 1


def test_get_quote_after_interval_fetches_again(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter, store: CacheStore
) -> None:
    cached.get_quote("600519")
    assert mock_adp.fetch_count == 1
    # 强制让 fetch 节流过期（绕过 interval 检查）
    cached._last_fetch_attempt["quote:600519"] = datetime.now(UTC) - timedelta(seconds=120)
    q = cached.get_quote("600519")
    assert q is not None
    assert mock_adp.fetch_count == 2


def test_get_quote_failure_falls_back_to_cached(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    cached.get_quote("600519")  # 拉新成功
    assert mock_adp.fetch_count == 1

    # 让下一次 fetch 失败
    mock_adp.fail_until_attempt = 2  # 第 2 次会失败
    cached._last_fetch_attempt["quote:600519"] = datetime.now(UTC) - timedelta(seconds=120)

    q = cached.get_quote("600519")
    # 失败 → 返回旧缓存
    assert q is not None
    assert q.code == "600519"
    assert mock_adp.fetch_count == 2
    assert cached.stats_counters["fetch_fail"] == 1
    assert cached.stats_counters["hits"] == 1  # fallback 也算 hit


def test_get_quote_no_cache_no_fetch_returns_none(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    mock_adp.fail_until_attempt = 99
    q = cached.get_quote("000000")  # 不存在的 code + fetch 失败
    assert q is None
    assert cached.stats_counters["miss"] == 1


def test_get_quote_unknown_code_no_cache_attempts_fetch(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    q = cached.get_quote("INVALID")  # mock 返回 None
    assert q is None
    assert mock_adp.fetch_count == 1


# ---------- 全市场快照 ----------


def test_list_market_quotes_first_call_fetches(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    quotes = cached.list_market_quotes()
    assert len(quotes) >= 1
    assert mock_adp.fetch_count == 1


def test_list_market_quotes_cached_hit(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    cached.list_market_quotes()
    cached.list_market_quotes()
    # 第二次应该命中缓存
    assert mock_adp.fetch_count == 1


def test_list_market_quotes_history_kept(store: CacheStore, mock_adp: MockAdapter) -> None:
    """多次拉新应保留多份历史快照。"""
    cfg = CacheConfig(market_snapshot_fetch_interval_seconds=0)
    cached = CachedMarketDataAdapter(mock_adp, store, config=cfg)
    cached.list_market_quotes()
    cached.list_market_quotes()
    cached.list_market_quotes()
    snaps = store.list_market_snapshots()
    assert len(snaps) == 3


def test_list_market_quotes_trim_history(store: CacheStore, mock_adp: MockAdapter) -> None:
    """保留最近 N 份。"""
    cfg = CacheConfig(market_snapshot_fetch_interval_seconds=0, market_snapshot_history_keep=2)
    cached = CachedMarketDataAdapter(mock_adp, store, config=cfg)
    for _ in range(5):
        cached.list_market_quotes()
    snaps = store.list_market_snapshots(limit=10)
    assert len(snaps) == 2  # 只保留最新 2 份


def test_list_market_quotes_failure_uses_cached(store: CacheStore, mock_adp: MockAdapter) -> None:
    cfg = CacheConfig(market_snapshot_fetch_interval_seconds=60)
    cached = CachedMarketDataAdapter(mock_adp, store, config=cfg)
    cached.list_market_quotes()  # 成功

    # 让下一次 fetch 失败
    mock_adp.fail_until_attempt = 2
    cached._last_fetch_attempt["market_snapshot:all"] = datetime.now(UTC) - timedelta(seconds=120)
    quotes = cached.list_market_quotes()
    assert len(quotes) >= 1  # 用旧快照


# ---------- 持久化 ----------


def test_data_persists_across_instances(tmp_path: Path, mock_adp: MockAdapter) -> None:
    """新实例化 CachedMarketDataAdapter 后能读旧数据。"""
    store = CacheStore(tmp_path / "test.db")
    cfg = CacheConfig(quote_fetch_interval_seconds=60)
    c1 = CachedMarketDataAdapter(mock_adp, store, config=cfg)
    c1.get_quote("600519")

    # 新实例（mock 不含该 quote）
    new_mock = MockAdapter(quotes={})
    c2 = CachedMarketDataAdapter(new_mock, store, config=cfg)
    # 在拉新间隔内，间隔内读缓存（不会调底层），返回旧数据
    q = c2.get_quote("600519")
    assert q is not None
    assert q.code == "600519"


def test_stats_counters_increment(cached: CachedMarketDataAdapter, mock_adp: MockAdapter) -> None:
    cached.get_quote("600519")  # fetch
    cached.get_quote("600519")  # hit
    cached.get_quote("INVALID")  # fetch + None
    st = cached.stats_counters
    assert st["fetch_ok"] >= 1
    assert st["hits"] >= 1


def test_data_freshness_report(cached: CachedMarketDataAdapter) -> None:
    cached.get_quote("600519")
    report = cached.data_freshness_report()
    assert len(report) == 1
    assert report[0]["code"] == "600519"
    assert "age_seconds" in report[0]


# ---------- 当日资金流 ----------


def test_get_today_money_flow_caches(store: CacheStore, mock_adp: MockAdapter) -> None:
    flow = MoneyFlow(
        code="600519",
        name="茅台",
        timestamp=datetime.now(UTC),
        main_net=Money.from_yuan(100_000_000),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(0),
        super_large_net=Money.from_yuan(0),
    )
    mock_adp.get_today_money_flow = lambda code: [flow]  # type: ignore[assignment]
    cfg = CacheConfig(today_money_flow_fetch_interval_seconds=60)
    cached = CachedMarketDataAdapter(mock_adp, store, config=cfg)

    flows1 = cached.get_today_money_flow("600519")
    initial_count = mock_adp.fetch_count
    flows2 = cached.get_today_money_flow("600519")
    assert len(flows1) == 1
    assert len(flows2) == 1
    # 第二次命中缓存，没调底层（fetch_count 不变）
    assert mock_adp.fetch_count == initial_count
    cached_data = store.get_today_money_flow("600519")
    assert cached_data is not None


# ---------- Store 基础 ----------


def test_store_stats_empty(store: CacheStore) -> None:
    st = store.stats()
    assert st == {
        "quotes": 0,
        "bars": 0,
        "flows_today": 0,
        "flows_history": 0,
        "snapshots": 0,
    }


def test_store_clear(store: CacheStore) -> None:
    store.set_quote("600519", _make_quote())
    assert store.get_quote("600519") is not None
    store.clear_quotes()
    assert store.get_quote("600519") is None


def test_store_clear_all(store: CacheStore) -> None:
    store.set_quote("600519", _make_quote())
    store.save_market_snapshot([{"code": "x"}])
    store.clear_all()
    st = store.stats()
    assert st["quotes"] == 0
    assert st["snapshots"] == 0


def test_store_get_set_quote_roundtrip(store: CacheStore) -> None:
    q = _make_quote("000001", "10.27", "-1.44")
    store.set_quote("000001", q)
    entry = store.get_quote("000001")
    assert entry is not None
    assert entry.code == "000001"
    assert entry.quote.price == q.price
    assert entry.quote.change_pct == q.change_pct
    # time-aware
    assert entry.fetched_at.tzinfo is not None
    assert entry.quote_ts.tzinfo is not None


def test_store_set_quote_overwrites(store: CacheStore) -> None:
    store.set_quote("600519", _make_quote("600519", "100"))
    store.set_quote("600519", _make_quote("600519", "200"))
    entry = store.get_quote("600519")
    assert entry is not None
    assert entry.quote.price == Decimal("200")


def test_store_market_snapshot_roundtrip(store: CacheStore) -> None:
    quotes = [{"code": "1"}, {"code": "2"}, {"code": "3"}]
    snap_id = store.save_market_snapshot(quotes, quote_ts=datetime.now(UTC))
    snap = store.get_latest_market_snapshot()
    assert snap is not None
    assert snap[0] == snap_id
    assert len(snap[3]) == 3


def test_store_get_all_quote_entries_sorted(store: CacheStore) -> None:
    store.set_quote("600519", _make_quote("600519", "100"))
    import time

    time.sleep(0.01)
    store.set_quote("000001", _make_quote("000001", "10"))
    entries = store.get_all_quote_entries()
    assert len(entries) == 2
    codes = [e.code for e in entries]
    # 按 fetched_at DESC，最近的在最前
    assert codes[0] == "000001"
    assert codes[1] == "600519"


def test_store_quote_cache_quote_ts_distinct_from_fetched_at(store: CacheStore) -> None:
    """quote_ts 是数据自身时间，fetched_at 是拉取时间。"""
    # 行情时间在 5 分钟前（模拟“东财接口 5 分钟前返回的数据”）
    past_ts = datetime.now(UTC) - timedelta(minutes=5)
    q = Quote(
        code="600519",
        name="茅台",
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
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=past_ts,
    )
    store.set_quote("600519", q)
    entry = store.get_quote("600519")
    assert entry is not None
    assert entry.quote_ts == past_ts
    # fetched_at 应该是现在（刚刚抓的）
    now = datetime.now(UTC)
    assert entry.fetched_at <= now
    assert (now - entry.fetched_at).total_seconds() < 5


# ---------- CacheManager ----------


def test_cache_manager_format_freshness(cached: CachedMarketDataAdapter) -> None:
    from mommy_chaogu.cache import CacheManager

    cached.get_quote("600519")
    mgr = CacheManager(store=cached.store, adapter=cached)
    out = mgr.format_freshness()
    assert "600519" in out
    assert "🟢" in out  # 新鲜数据应该是绿色


def test_cache_manager_stats(cached: CachedMarketDataAdapter) -> None:
    from mommy_chaogu.cache import CacheManager

    cached.get_quote("600519")
    cached.get_quote("600519")
    mgr = CacheManager(store=cached.store, adapter=cached)
    st = mgr.stats()
    assert st["quotes"] == 1
    assert st["fetch_ok"] == 1
    assert st["hits"] == 1
    assert "freshness" in st


# ---------- last_source 数据来源追踪 ----------


def test_last_source_network_on_fresh_fetch(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """首次拉新成功 → last_source == 'network'。"""
    cached.get_quote("600519")
    assert cached.last_source == "network"


def test_last_source_cache_on_throttle_hit(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """间隔内二次调用命中缓存 → last_source == 'cache'。"""
    cached.get_quote("600519")  # 拉新
    cached.get_quote("600519")  # 命中缓存
    assert cached.last_source == "cache"


def test_last_source_stale_cache_on_fetch_failure(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """拉新失败但缓存有旧数据 → last_source == 'stale_cache'。"""
    cached.get_quote("600519")  # 先拉新成功
    mock_adp.fail_until_attempt = 2
    cached._last_fetch_attempt["quote:600519"] = datetime.now(UTC) - timedelta(seconds=120)
    cached.get_quote("600519")  # 拉新失败 → fallback 到旧缓存
    assert cached.last_source == "stale_cache"


def test_last_source_snapshot_on_market_quotes(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """全市场快照首次拉新 → last_source == 'snapshot'。"""
    cached.list_market_quotes()
    assert cached.last_source == "snapshot"


def test_format_source_label_realtime(cached: CachedMarketDataAdapter) -> None:
    """network 来源 → 返回带适配器名的实时标注。"""
    cached.get_quote("600519")
    label = cached.format_source_label()
    assert label  # 非空


def test_format_source_label_cache(cached: CachedMarketDataAdapter, mock_adp: MockAdapter) -> None:
    """cache 来源 → 返回 '本地缓存'。"""
    cached.get_quote("600519")
    cached.get_quote("600519")  # 命中缓存
    assert cached.format_source_label() == "本地缓存"


def test_format_source_label_empty(cached: CachedMarketDataAdapter) -> None:
    """无数据 → 空字符串。"""
    assert cached.format_source_label() == ""


# ---------- get_quotes 批量拉取（#11 新增的批量路径）----------


def test_get_quotes_empty_input(cached: CachedMarketDataAdapter) -> None:
    """空 codes → 空列表，不调底层。"""
    result = cached.get_quotes([])
    assert result == []


def test_get_quotes_all_fresh(cached: CachedMarketDataAdapter, mock_adp: MockAdapter) -> None:
    """全部未缓存 → 一次性批量拉，inner.get_quotes 只调 1 次。"""
    # 补充第二个 code 到 mock
    mock_adp._quotes["000001"] = _make_quote("000001")
    result = cached.get_quotes(["600519", "000001"])
    assert len(result) == 2
    codes = {q.code for q in result}
    assert codes == {"600519", "000001"}
    assert cached.last_source == "network"


def test_get_quotes_dedup_codes(cached: CachedMarketDataAdapter) -> None:
    """重复 code 去重。"""
    result = cached.get_quotes(["600519", "600519", "600519"])
    assert len(result) == 1
    assert result[0].code == "600519"


def test_get_quotes_cache_hit_skips_network(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """缓存命中（节流窗口内）→ 不走网络。"""
    # 第一次：拉新 + 写缓存
    cached.get_quote("600519")

    # 第二次：批量查，应命中缓存（节流窗口 60s 内）
    result = cached.get_quotes(["600519"])
    assert len(result) == 1
    assert cached.last_source == "cache"


def test_get_quotes_partial_cache_partial_fresh(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """部分缓存命中、部分未命中 → 混合来源。"""
    # 补充第二个 code
    mock_adp._quotes["000001"] = _make_quote("000001")
    # 先缓存 600519
    cached.get_quote("600519")
    # 批量查 600519（缓存）+ 000001（新）
    result = cached.get_quotes(["600519", "000001"])
    assert len(result) == 2
    codes = {q.code for q in result}
    assert codes == {"600519", "000001"}


def test_get_quotes_inner_failure_falls_back_to_cache(
    cached: CachedMarketDataAdapter, mock_adp: MockAdapter
) -> None:
    """底层批量拉失败 → 回退旧缓存。"""
    # 先缓存（含旧数据）
    cached.get_quote("600519")

    # 让 inner.get_quotes 抛异常
    original = mock_adp.get_quotes

    def failing_get_quotes(codes: list[str]) -> list:
        raise ConnectionError("batch failed")

    mock_adp.get_quotes = failing_get_quotes  # type: ignore[method-assign]

    # 等节流窗口过期后重试
    from datetime import UTC, datetime, timedelta

    cached._last_fetch_attempt["quote:600519"] = datetime.now(UTC) - timedelta(seconds=120)
    result = cached.get_quotes(["600519"])

    # 底层失败了，但旧缓存兜底
    assert len(result) == 1
    assert result[0].code == "600519"
    assert cached.stats_counters["fetch_fail"] >= 1

    # 恢复
    mock_adp.get_quotes = original  # type: ignore[method-assign]


def test_get_quotes_unknown_code_returns_empty(cached: CachedMarketDataAdapter) -> None:
    """底层不认识的 code → 结果不含它。"""
    result = cached.get_quotes(["999999"])
    assert len(result) == 0
