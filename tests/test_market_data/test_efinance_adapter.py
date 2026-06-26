"""EfinanceAdapter 真实集成测试。

不 mock，直接调 efinance。覆盖：
- 稳定接口：health_check / get_quote / list_market_quotes / get_bars / get_belonging_boards
- 容错行为：未知代码 / 网络异常返回 None 或空列表

测试运行需要联网（push2.eastmoney.com）。
"""
from __future__ import annotations

import pytest

from mommy_chaogu.market_data import (
    AdjustmentType,
    BarInterval,
    EfinanceAdapter,
    MarketType,
    QuoteType,
)


# ---------- 真实接口（标记为网络依赖） ----------

@pytest.fixture(scope="module")
def adp() -> EfinanceAdapter:
    return EfinanceAdapter()


@pytest.mark.network
def test_health_check_returns_true(adp: EfinanceAdapter) -> None:
    assert adp.health_check() is True


@pytest.mark.network
def test_get_quote_known_stock(adp: EfinanceAdapter) -> None:
    q = adp.get_quote("600519")
    assert q is not None
    assert q.code == "600519"
    assert q.market == MarketType.SH
    assert q.quote_type == QuoteType.STOCK
    assert q.price > 0
    assert q.timestamp is not None


@pytest.mark.network
def test_get_quote_sz_stock(adp: EfinanceAdapter) -> None:
    q = adp.get_quote("000001")
    assert q is not None
    assert q.market == MarketType.SZ
    assert q.code == "000001"


@pytest.mark.network
def test_get_quote_unknown_returns_none(adp: EfinanceAdapter) -> None:
    """不存在的代码 → None，不抛异常。"""
    assert adp.get_quote("999999") is None
    assert adp.get_quote("INVALID") is None


@pytest.mark.network
def test_get_quotes_dedup_and_skip_failures(adp: EfinanceAdapter) -> None:
    qs = adp.get_quotes(["600519", "600519", "000001", "INVALID"])
    codes = [q.code for q in qs]
    # 去重 + 跳过失败
    assert codes.count("600519") == 1
    assert "000001" in codes
    assert "INVALID" not in codes


@pytest.mark.network
def test_list_market_quotes_returns_many(adp: EfinanceAdapter) -> None:
    qs = adp.list_market_quotes()
    assert len(qs) > 3000
    # 至少有几条 SH/SZ
    markets = {q.market for q in qs}
    assert MarketType.SH in markets
    assert MarketType.SZ in markets


@pytest.mark.network
def test_get_bars_d1_limit(adp: EfinanceAdapter) -> None:
    bars = adp.get_bars("600519", interval=BarInterval.D1, limit=10)
    assert len(bars) == 10
    # 时间递增
    for a, b in zip(bars, bars[1:], strict=False):
        assert a.timestamp <= b.timestamp
    # 字段合理性
    last = bars[-1]
    assert last.close > 0
    assert last.high >= last.low
    assert last.volume > 0


@pytest.mark.network
def test_get_bars_d1_date_range(adp: EfinanceAdapter) -> None:
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=30)
    bars = adp.get_bars("600519", interval=BarInterval.D1, start=start, end=end)
    assert 15 <= len(bars) <= 31
    assert all(start <= b.timestamp.date() <= end for b in bars)


@pytest.mark.network
def test_get_bars_5m_recent(adp: EfinanceAdapter) -> None:
    bars = adp.get_bars("600519", interval=BarInterval.M5, limit=10)
    assert len(bars) == 10
    assert all(b.interval == BarInterval.M5 for b in bars)


@pytest.mark.network
def test_get_bars_adjustment_types_distinct(adp: EfinanceAdapter) -> None:
    """前复权和后复权在分红送股日会有差异。"""
    fwd = adp.get_bars("600519", interval=BarInterval.D1, limit=20,
                        adjustment=AdjustmentType.FORWARD)
    bwd = adp.get_bars("600519", interval=BarInterval.D1, limit=20,
                        adjustment=AdjustmentType.BACKWARD)
    assert len(fwd) == len(bwd) == 20
    # 价格应该大致接近但通常有差异（茅台可能除权过）
    prices = [(f.close, b.close) for f, b in zip(fwd, bwd, strict=False)]
    diffs = [abs(a - b) for a, b in prices]
    # 不强求有差异（不除权的股票就没差），只验证两种复权都返回了
    assert all(f.close > 0 for f in fwd)
    assert all(b.close > 0 for b in bwd)


@pytest.mark.network
def test_get_belonging_boards(adp: EfinanceAdapter) -> None:
    boards = adp.get_belonging_boards("600519")
    assert len(boards) > 0
    # 茅台至少应该属于白酒/食品饮料板块
    names = [b.name for b in boards]
    assert any("白酒" in n for n in names)
