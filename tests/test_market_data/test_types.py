"""通用行情 dataclass 单测。

不依赖外部数据源，只验证：
- 字段类型 + frozen 不可变
- Decimal 精度
- Protocol 接口契约（runtime_checkable）
- helper 函数行为
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime
from decimal import Decimal

import pytest

from mommy_chaogu.market_data import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketDataAdapter,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    OrderBookLevel,
    Quote,
    QuoteType,
    Tick,
    EfinanceAdapter,
    filter_by_market,
    find_quote,
)


# ---------- Money ----------

def test_money_from_yuan_accepts_float_int_str_decimal() -> None:
    assert Money.from_yuan(10.5).amount == Decimal("10.5")
    assert Money.from_yuan(100).amount == Decimal("100")
    assert Money.from_yuan("3.14").amount == Decimal("3.14")
    assert Money.from_yuan(Decimal("99.99")).amount == Decimal("99.99")


def test_money_str() -> None:
    assert str(Money.from_yuan(100)) == "100 CNY"
    assert str(Money(Decimal("50.5"), "USD")) == "50.5 USD"


# ---------- dataclass frozen 行为 ----------

def _make_quote() -> Quote:
    return Quote(
        code="600519",
        name="XD贵州茅",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("1184.98"),
        open=Decimal("1199.00"),
        high=Decimal("1199.00"),
        low=Decimal("1175.01"),
        prev_close=Decimal("1184.08"),
        change=Decimal("0.90"),
        change_pct=Decimal("0.08"),
        volume=31877,
        turnover=Money.from_yuan(3781470336),
        turnover_rate=Decimal("0.25"),
        volume_ratio=Decimal("1.19"),
        pe_dynamic=Decimal("13.59"),
        total_market_cap=Money.from_yuan(1481321695553),
        circulating_market_cap=Money.from_yuan(1481321695553),
        timestamp=datetime(2026, 6, 26, 11, 34, 8),
        quote_id="1.600519",
    )


def test_quote_is_frozen() -> None:
    q = _make_quote()
    with pytest.raises(FrozenInstanceError):
        q.price = Decimal("999")  # type: ignore[misc]


def test_quote_is_dataclass_and_has_required_fields() -> None:
    q = _make_quote()
    assert is_dataclass(q)
    field_names = {f.name for f in fields(Quote)}
    assert {"code", "name", "market", "price", "change_pct", "timestamp"} <= field_names


def test_quote_str_contains_code_name_change() -> None:
    q = _make_quote()
    s = str(q)
    assert "600519" in s
    assert "XD贵州茅" in s
    assert "+0.08%" in s


def test_bar_default_fields_optional() -> None:
    bar = Bar(
        code="600519",
        name="",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 6, 26),
        open=Decimal("1184"),
        high=Decimal("1199"),
        low=Decimal("1175"),
        close=Decimal("1190"),
        volume=10000,
        turnover=Money.from_yuan(118900000),
    )
    assert bar.change_pct is None
    assert bar.turnover_rate is None
    assert bar.amplitude is None


def test_order_book_spread() -> None:
    ob = OrderBook(
        code="600519",
        name="",
        timestamp=datetime(2026, 6, 26),
        bids=(
            OrderBookLevel(Decimal("100.00"), 10),
            OrderBookLevel(Decimal("99.99"), 20),
        ),
        asks=(
            OrderBookLevel(Decimal("100.02"), 5),
            OrderBookLevel(Decimal("100.05"), 8),
        ),
    )
    assert ob.best_bid.price == Decimal("100.00")
    assert ob.best_ask.price == Decimal("100.02")
    assert ob.spread == Decimal("0.02")


def test_order_book_empty_spread_is_none() -> None:
    ob = OrderBook(code="x", name="y", timestamp=datetime.now(), bids=(), asks=())
    assert ob.spread is None
    assert ob.best_bid is None
    assert ob.best_ask is None


# ---------- helper ----------

def test_filter_by_market_none_returns_all() -> None:
    qs = [
        _make_quote(),
        _make_quote(),
    ]
    qs[1] = Quote(
        code="000001", name="平安", market=MarketType.SZ,
        quote_type=QuoteType.STOCK,
        price=Decimal("10"), open=Decimal("10"), high=Decimal("10"),
        low=Decimal("10"), prev_close=Decimal("10"),
        change=Decimal("0"), change_pct=Decimal("0"),
        volume=0, turnover=Money.from_yuan(0),
        turnover_rate=None, volume_ratio=None,
        pe_dynamic=None, total_market_cap=None,
        circulating_market_cap=None, timestamp=datetime.now(),
    )
    assert len(filter_by_market(qs, None)) == 2


def test_filter_by_market_sh_only() -> None:
    q1 = _make_quote()  # SH
    q2 = Quote(
        code="000001", name="平安", market=MarketType.SZ,
        quote_type=QuoteType.STOCK,
        price=Decimal("10"), open=Decimal("10"), high=Decimal("10"),
        low=Decimal("10"), prev_close=Decimal("10"),
        change=Decimal("0"), change_pct=Decimal("0"),
        volume=0, turnover=Money.from_yuan(0),
        turnover_rate=None, volume_ratio=None,
        pe_dynamic=None, total_market_cap=None,
        circulating_market_cap=None, timestamp=datetime.now(),
    )
    assert filter_by_market([q1, q2], ["SH"]) == [q1]
    assert filter_by_market([q1, q2], ["SZ"]) == [q2]
    assert filter_by_market([q1, q2], ["BJ"]) == []


def test_find_quote() -> None:
    q1 = _make_quote()
    q2 = Quote(
        code="000001", name="平安", market=MarketType.SZ,
        quote_type=QuoteType.STOCK,
        price=Decimal("10"), open=Decimal("10"), high=Decimal("10"),
        low=Decimal("10"), prev_close=Decimal("10"),
        change=Decimal("0"), change_pct=Decimal("0"),
        volume=0, turnover=Money.from_yuan(0),
        turnover_rate=None, volume_ratio=None,
        pe_dynamic=None, total_market_cap=None,
        circulating_market_cap=None, timestamp=datetime.now(),
    )
    assert find_quote([q1, q2], "000001") is q2
    assert find_quote([q1, q2], "999999") is None
    assert find_quote([], "600519") is None


# ---------- Protocol 契约 ----------

def test_efinance_adapter_satisfies_protocol() -> None:
    """EfinanceAdapter 必须实现 MarketDataAdapter 的所有方法。"""
    a = EfinanceAdapter()
    assert isinstance(a, MarketDataAdapter)
    assert a.name == "efinance"


def test_protocol_is_runtime_checkable_with_dummy() -> None:
    """任何 duck-typed 对象只要方法齐全就算合规。"""

    class DummyAdapter:
        name = "dummy"

        def get_quote(self, code): return None
        def get_quotes(self, codes): return []
        def list_market_quotes(self): return []
        def get_order_book(self, code): return None
        def get_bars(self, code, **kw): return []
        def get_ticks(self, code, limit=None): return []
        def get_today_money_flow(self, code): return []
        def get_history_money_flow(self, code, days=30): return []
        def get_belonging_boards(self, code): return []
        def health_check(self): return True

    assert isinstance(DummyAdapter(), MarketDataAdapter)
