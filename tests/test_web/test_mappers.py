"""mappers.py 单测：dataclass → Pydantic 转换。

这是 bug 高发区（Decimal vs Money、naive vs aware datetime）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from mommy_chaogu.monitor import SnapshotRow
from mommy_chaogu.watchlist.models import Group, StockEntry
from mommy_chaogu.web.mappers import (
    _quote_to_out,
    bar_to_out,
    group_to_out,
    orderbook_to_out,
    signal_to_out,
    snapshot_to_out,
    stock_entry_to_out,
)
from tests.test_web.conftest import (
    make_bar,
    make_flow,
    make_orderbook,
    make_quote,
    make_signal,
    make_snapshot,
    make_stock_entry,
)


class TestQuoteToOut:
    """_quote_to_out：SnapshotRow → QuoteOut。"""

    def test_basic_conversion(self) -> None:

        row = SnapshotRow(
            entry=make_stock_entry(),
            group_name="持仓",
            quote=make_quote(),
            latest_flow=make_flow(),
        )
        out = _quote_to_out(row)
        assert out.code == "600519"
        assert out.name == "贵州茅台"
        assert out.price == Decimal("1680.50")
        assert out.change_pct == Decimal("1.85")
        assert out.market == "SH"

    def test_main_net_inflow_from_flow(self) -> None:

        row = SnapshotRow(
            entry=make_stock_entry(),
            group_name="持仓",
            quote=make_quote(),
            latest_flow=make_flow(main_net="999999"),
        )
        out = _quote_to_out(row)
        assert out.main_net_inflow == Decimal("999999")

    def test_main_net_inflow_none_when_no_flow(self) -> None:

        row = SnapshotRow(
            entry=make_stock_entry(),
            group_name="持仓",
            quote=make_quote(),
            latest_flow=None,
        )
        out = _quote_to_out(row)
        assert out.main_net_inflow is None

    def test_naive_datetime_gets_utc(self) -> None:
        """timestamp 没 tzinfo 时 mappers 应补 UTC。"""
        import dataclasses

        base_quote = make_quote()
        # 替换 timestamp 为 naive datetime
        naive_ts = datetime(2026, 6, 27, 15, 0, 0)
        naive_quote = dataclasses.replace(base_quote, timestamp=naive_ts)
        row = SnapshotRow(
            entry=make_stock_entry(),
            group_name="持仓",
            quote=naive_quote,
        )
        out = _quote_to_out(row)
        assert out.timestamp.tzinfo is not None
        assert out.data_age_seconds >= 0

    def test_volume_to_int(self) -> None:

        row = SnapshotRow(
            entry=make_stock_entry(),
            group_name="持仓",
            quote=make_quote(),
        )
        out = _quote_to_out(row)
        assert isinstance(out.volume, int)
        assert out.volume == 12345678

    def test_turnover_from_money(self) -> None:

        row = SnapshotRow(
            entry=make_stock_entry(),
            group_name="持仓",
            quote=make_quote(),
        )
        out = _quote_to_out(row)
        assert out.turnover == Decimal("2000000000")


class TestSnapshotToOut:
    """snapshot_to_out：Snapshot → SnapshotOut。"""

    def test_basic(self) -> None:
        snap = make_snapshot()
        out = snapshot_to_out(snap)
        assert out.n_codes == 2
        assert len(out.quotes) == 2
        assert out.n_up == 1  # 600519 +1.85%
        assert out.n_down == 1  # 000858 -0.65%
        assert out.n_flat == 0

    def test_total_main_net_summed(self) -> None:
        snap = make_snapshot()
        out = snapshot_to_out(snap)
        # 120M + (-50M) = 70M
        assert out.total_main_net == Decimal("70000000")


class TestBarToOut:
    """bar_to_out：Bar → BarOut。"""

    def test_basic(self) -> None:
        bar = make_bar()
        out = bar_to_out(bar)
        assert out.open == Decimal("1660.00")
        assert out.close == Decimal("1680.00")
        assert out.volume == 10000000
        assert isinstance(out.volume, int)

    def test_turnover_from_money(self) -> None:
        bar = make_bar()
        out = bar_to_out(bar)
        assert out.turnover == Decimal("16800000000")


class TestOrderbookToOut:
    """orderbook_to_out：OrderBook → OrderBookOut。"""

    def test_basic(self) -> None:
        ob = make_orderbook()
        out = orderbook_to_out("600519", ob)
        assert out.code == "600519"
        assert len(out.bids) == 5
        assert len(out.asks) == 5

    def test_bid_price_is_decimal(self) -> None:
        ob = make_orderbook()
        out = orderbook_to_out("600519", ob)
        assert isinstance(out.bids[0].price, Decimal)

    def test_volume_is_int(self) -> None:
        ob = make_orderbook()
        out = orderbook_to_out("600519", ob)
        assert isinstance(out.bids[0].volume, int)


class TestStockEntryToOut:
    """stock_entry_to_out：StockEntry → WatchlistStockOut。"""

    def test_basic(self) -> None:
        entry = make_stock_entry("000858", "五粮液")
        out = stock_entry_to_out(entry, "持仓")
        assert out.code == "000858"
        assert out.name == "五粮液"
        assert out.group == "持仓"

    def test_naive_created_at_gets_utc(self) -> None:
        entry = StockEntry(
            code="600519",
            name="茅台",
            group_id=1,
            created_at=datetime(2026, 6, 27, 10, 0, 0),
        )
        out = stock_entry_to_out(entry, "持仓")
        assert out.added_at is not None
        assert out.added_at.tzinfo is not None


class TestGroupToOut:
    def test_basic(self) -> None:
        group = Group(name="持仓", description="核心持仓")
        out = group_to_out(group, n_stocks=3)
        assert out.name == "持仓"
        assert out.n_stocks == 3
        assert out.description == "核心持仓"


class TestSignalToOut:
    def test_basic(self) -> None:
        sig = make_signal()
        out = signal_to_out(sig)
        assert out.code == "600519"
        assert out.severity == "critical"
        assert out.trigger_value == Decimal("120000000")
        assert out.threshold_value == Decimal("80000000")

    def test_severity_warning(self) -> None:
        from mommy_chaogu.signals.types import SignalSeverity

        sig = make_signal(severity=SignalSeverity.WARNING)
        out = signal_to_out(sig)
        assert out.severity == "warning"
