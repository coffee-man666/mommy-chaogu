"""ToolRegistry 单测：工具定义 + 执行（Mock adapter）。"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)

# ---------- fixtures ----------


def _make_quote(code: str = "600519", name: str = "贵州茅台") -> Quote:
    return Quote(
        code=code,
        name=name,
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("1680.00"),
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        prev_close=Decimal("1650.00"),
        change=Decimal("30.00"),
        change_pct=Decimal("1.82"),
        volume=12345678,
        turnover=Money.from_yuan("9999999999"),
        turnover_rate=Decimal("0.98"),
        volume_ratio=Decimal("1.23"),
        pe_dynamic=Decimal("25.5"),
        total_market_cap=Money.from_yuan("2100000000000"),
        circulating_market_cap=Money.from_yuan("2100000000000"),
        timestamp=datetime(2026, 7, 1, 15, 0, 0),
    )


def _make_money_flow(code: str = "600519") -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name="贵州茅台",
        timestamp=datetime(2026, 7, 1, 15, 0, 0),
        main_net=Money.from_yuan("50000000"),
        small_net=Money.from_yuan("-10000000"),
        medium_net=Money.from_yuan("-5000000"),
        large_net=Money.from_yuan("20000000"),
        super_large_net=Money.from_yuan("30000000"),
        main_net_ratio=Decimal("2.5"),
    )


def _make_bar(code: str = "600519") -> Bar:
    return Bar(
        code=code,
        name="贵州茅台",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 7, 1, 15, 0, 0),
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        close=Decimal("1680.00"),
        volume=12345678,
        turnover=Money.from_yuan("9999999999"),
    )


@pytest.fixture
def mock_adapter() -> MagicMock:
    """Mock adapter with default return values."""
    adp = MagicMock()
    adp.get_quote.return_value = _make_quote()
    adp.get_quotes.return_value = [_make_quote("600519"), _make_quote("000001", "平安银行")]
    adp.get_today_money_flow.return_value = [_make_money_flow()]
    adp.get_history_money_flow.return_value = [_make_money_flow()]
    adp.get_bars.return_value = [_make_bar()]
    adp.get_belonging_boards.return_value = [
        Board(code="BK0477", name="白酒", change_pct=Decimal("1.5"))
    ]
    return adp


@pytest.fixture
def ctx(mock_adapter: MagicMock) -> ToolContext:
    return ToolContext(
        adapter=mock_adapter,
        watchlist_store=None,
        portfolio_store=None,
    )


@pytest.fixture
def registry(ctx: ToolContext) -> ToolRegistry:
    return ToolRegistry(ctx)


# ---------- tests ----------


class TestToolDefinitions:
    def test_all_tools_have_definitions(self, registry: ToolRegistry) -> None:
        defs = registry.definitions()
        assert len(defs) == 16
        names = {d["function"]["name"] for d in defs}
        assert names == set(ToolRegistry.tool_names())

    def test_definitions_are_valid_openai_format(self, registry: ToolRegistry) -> None:
        for d in registry.definitions():
            assert d["type"] == "function"
            fn = d["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert isinstance(fn["parameters"], dict)

    def test_tool_names_contains_key_tools(self) -> None:
        names = ToolRegistry.tool_names()
        for expected in ["get_quote", "get_quotes", "get_money_flow_today",
                         "get_sector_stocks", "search_sector"]:
            assert expected in names


class TestGetQuote:
    def test_returns_quote_json(self, registry: ToolRegistry) -> None:
        result = registry.call("get_quote", {"code": "600519"})
        data = json.loads(result)
        assert data["code"] == "600519"
        assert data["name"] == "贵州茅台"
        assert data["price"] == 1680.0
        assert data["change_pct"] == 1.82

    def test_returns_error_on_none(self, registry: ToolRegistry, mock_adapter: MagicMock) -> None:
        mock_adapter.get_quote.return_value = None
        result = registry.call("get_quote", {"code": "999999"})
        data = json.loads(result)
        assert "error" in data


class TestGetQuotes:
    def test_batch_returns_list(self, registry: ToolRegistry) -> None:
        result = registry.call("get_quotes", {"codes": ["600519", "000001"]})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["code"] == "600519"
        assert data[1]["code"] == "000001"


class TestGetMoneyFlowToday:
    def test_returns_latest_flow(self, registry: ToolRegistry) -> None:
        result = registry.call("get_money_flow_today", {"code": "600519"})
        data = json.loads(result)
        assert data["code"] == "600519"
        assert data["main_net"] == 50000000.0
        assert data["main_net_ratio"] == 2.5

    def test_empty_flows_returns_error(self, registry: ToolRegistry, mock_adapter: MagicMock) -> None:
        mock_adapter.get_today_money_flow.return_value = []
        result = registry.call("get_money_flow_today", {"code": "600519"})
        data = json.loads(result)
        assert "error" in data


class TestGetMoneyFlowHistory:
    def test_returns_list_of_flows(self, registry: ToolRegistry) -> None:
        result = registry.call("get_money_flow_history", {"code": "600519", "days": 7})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["main_net"] == 50000000.0


class TestGetBars:
    def test_returns_kline_data(self, registry: ToolRegistry) -> None:
        result = registry.call("get_bars", {"code": "600519", "interval": "1d", "limit": 5})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["close"] == 1680.0


class TestGetWatchlist:
    def test_no_store_returns_error(self, registry: ToolRegistry) -> None:
        result = registry.call("get_watchlist", {})
        data = json.loads(result)
        assert "error" in data


class TestGetPortfolio:
    def test_no_store_returns_error(self, registry: ToolRegistry) -> None:
        result = registry.call("get_portfolio", {})
        data = json.loads(result)
        assert "error" in data


class TestUnknownTool:
    def test_returns_error(self, registry: ToolRegistry) -> None:
        result = registry.call("nonexistent_tool", {})
        data = json.loads(result)
        assert "error" in data
