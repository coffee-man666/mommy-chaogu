"""Web 测试公共 fixtures。

核心思路：
- 用 Mock adapter / in-memory store / fake service 替换依赖
- 不走真实网络、不依赖 DB 文件
- TestClient 启动时不触发 lifespan（避免真实 polling）
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    OrderBookLevel,
    Quote,
    QuoteType,
)
from mommy_chaogu.monitor import Snapshot, SnapshotRow
from mommy_chaogu.signals.types import Signal, SignalSeverity
from mommy_chaogu.watchlist.models import StockEntry

# ---------- 数据工厂 ----------


def make_quote(
    code: str = "600519",
    name: str = "贵州茅台",
    price: str = "1680.50",
    change_pct: str = "1.85",
    market: MarketType = MarketType.SH,
    **kwargs: Any,
) -> Quote:
    """造一个测试用 Quote。"""
    price_d = Decimal(price)
    change_d = (Decimal(change_pct) * price_d / 100).quantize(Decimal("0.01"))
    return Quote(
        code=code,
        name=name,
        market=market,
        quote_type=QuoteType.STOCK,
        price=price_d,
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        prev_close=price_d - change_d,
        change=change_d,
        change_pct=Decimal(change_pct),
        volume=12345678,
        turnover=Money(Decimal("2000000000"), "CNY"),
        turnover_rate=Decimal("0.98"),
        volume_ratio=Decimal("1.23"),
        pe_dynamic=Decimal("25.6"),
        total_market_cap=Money(Decimal("2100000000000"), "CNY"),
        circulating_market_cap=Money(Decimal("2100000000000"), "CNY"),
        timestamp=datetime.now(UTC),
        **kwargs,
    )


def make_flow(
    code: str = "600519",
    main_net: str = "120000000",
) -> MoneyFlow:
    """造一个测试用 MoneyFlow。"""
    return MoneyFlow(
        code=code,
        name="贵州茅台",
        timestamp=datetime.now(UTC),
        main_net=Money(Decimal(main_net), "CNY"),
        small_net=Money(Decimal("-30000000"), "CNY"),
        medium_net=Money(Decimal("-20000000"), "CNY"),
        large_net=Money(Decimal("50000000"), "CNY"),
        super_large_net=Money(Decimal("70000000"), "CNY"),
        main_net_ratio=Decimal("6.0"),
    )


def make_bar(code: str = "600519") -> Bar:
    """造一个测试用 Bar。"""
    return Bar(
        code=code,
        name="贵州茅台",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 6, 27, tzinfo=UTC),
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        close=Decimal("1680.00"),
        volume=10000000,
        turnover=Money(Decimal("16800000000"), "CNY"),
    )


def make_orderbook(code: str = "600519") -> OrderBook:
    """造一个测试用 5 档盘口。"""
    bids = tuple(
        OrderBookLevel(price=Decimal(f"168{i}.00"), volume=100 * (5 - i)) for i in range(5)
    )
    asks = tuple(
        OrderBookLevel(price=Decimal(f"168{i + 5}.00"), volume=80 * (5 - i)) for i in range(5)
    )
    return OrderBook(
        code=code,
        name="贵州茅台",
        timestamp=datetime.now(UTC),
        bids=bids,
        asks=asks,
        last_price=Decimal("1680.50"),
        last_volume=100,
    )


def make_stock_entry(
    code: str = "600519",
    name: str = "贵州茅台",
    group_id: int = 1,
) -> StockEntry:
    """造一个测试用 StockEntry。"""
    return StockEntry(
        code=code,
        name=name,
        group_id=group_id,
        note="测试",
        created_at=datetime.now(UTC),
    )


def make_snapshot() -> Snapshot:
    """造一个 2 只股票的 snapshot。"""
    entry1 = make_stock_entry("600519", "贵州茅台", group_id=1)
    entry2 = make_stock_entry("000858", "五粮液", group_id=1)
    row1 = SnapshotRow(
        entry=entry1,
        group_name="持仓",
        quote=make_quote("600519", "贵州茅台", "1680.50", "1.85"),
        latest_flow=make_flow("600519", "120000000"),
    )
    row2 = SnapshotRow(
        entry=entry2,
        group_name="持仓",
        quote=make_quote("000858", "五粮液", "155.20", "-0.65", market=MarketType.SZ),
        latest_flow=make_flow("000858", "-50000000"),
    )
    return Snapshot.build([row1, row2], snapshot_id=1)


def make_signal(
    code: str = "600519",
    rule_id: str = "price_change_threshold",
    severity: SignalSeverity = SignalSeverity.CRITICAL,
) -> Signal:
    """造一个测试用 Signal。"""
    return Signal(
        timestamp=datetime.now(UTC),
        code=code,
        name="贵州茅台",
        rule_id=rule_id,
        severity=severity,
        title="主力净流入警告",
        detail="主力净额：1.2 亿（阈值 8000 万）",
        trigger_value=Decimal("120000000"),
        threshold_value=Decimal("80000000"),
    )


# ---------- Mock 依赖 ----------


def make_mock_adapter() -> MagicMock:
    """造一个 Mock MarketDataAdapter，预填返回值。"""
    adapter = MagicMock()
    adapter.name = "MockAdapter"
    adapter.get_quote.return_value = make_quote()
    adapter.get_bars.return_value = [make_bar(), make_bar(), make_bar()]
    adapter.get_order_book.return_value = make_orderbook()
    adapter.get_today_money_flow.return_value = [
        make_flow(),
    ]
    adapter.get_all_quotes.return_value = [make_quote()]
    adapter.stats_counters = {"hits": 10, "fetches": 5, "fetch_ok": 4, "fetch_fail": 1, "miss": 5}
    adapter.data_freshness_report.return_value = [
        {"code": "600519", "age_seconds": 3, "fresh": True},
    ]
    return adapter


def make_mock_service() -> MagicMock:
    """造一个 Mock BackgroundService。"""
    svc = MagicMock()
    svc.latest_snapshot = make_snapshot()
    svc.latest_signals = [make_signal()]
    svc.uptime_seconds.return_value = 42.5
    svc.last_poll_at.return_value = datetime.now(UTC)
    svc.pushed_signals = []
    return svc


# ---------- FastAPI test client ----------


@pytest.fixture()
def mock_adapter() -> MagicMock:
    return make_mock_adapter()


@pytest.fixture()
def mock_service() -> MagicMock:
    return make_mock_service()


@pytest.fixture()
def client(mock_adapter: MagicMock, mock_service: MagicMock) -> TestClient:
    """带 mock 依赖的 FastAPI TestClient（不走 lifespan）。"""
    from mommy_chaogu.web.app import create_app
    from mommy_chaogu.web.background import set_service
    from mommy_chaogu.web.deps import get_adapter, get_alerter, get_watchlist_store

    set_service(mock_service)

    app = create_app()
    app.dependency_overrides[get_adapter] = lambda: mock_adapter
    app.dependency_overrides[get_alerter] = MagicMock()
    app.dependency_overrides[get_watchlist_store] = MagicMock()

    # 不触发 lifespan（避免真实 polling）
    return TestClient(app, raise_server_exceptions=False)
