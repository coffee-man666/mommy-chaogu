"""search_stock 工具 + get_quote 名称兜底单测（mock 搜索，不碰网络）。"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.agent.tools import quote as quote_tools
from mommy_chaogu.market_data.stock_search import StockSearchHit
from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType


def _make_quote(code: str = "002594", name: str = "比亚迪") -> Quote:
    return Quote(
        code=code,
        name=name,
        market=MarketType.SZ,
        quote_type=QuoteType.STOCK,
        price=Decimal("83.35"),
        open=Decimal("83.61"),
        high=Decimal("84.28"),
        low=Decimal("83.18"),
        prev_close=Decimal("84.34"),
        change=Decimal("-0.99"),
        change_pct=Decimal("-1.17"),
        volume=182365,
        turnover=Money.from_yuan("1524934515"),
        turnover_rate=Decimal("0.52"),
        volume_ratio=Decimal("0.74"),
        pe_dynamic=Decimal("30.83"),
        total_market_cap=Money.from_yuan("759918417043"),
        circulating_market_cap=Money.from_yuan("290647177979"),
        timestamp=datetime(2026, 9, 27, 15, 0, 0),
    )


_BYD_HITS = [StockSearchHit(code="002594", name="比亚迪", market="A股")]


def _mock_search(
    monkeypatch: pytest.MonkeyPatch,
    hits: list[StockSearchHit] | None = None,
) -> list[str]:
    """替换 quote 工具里的搜索函数；返回调用记录列表。"""
    calls: list[str] = []
    default = hits if hits is not None else _BYD_HITS

    def fake(query: str, limit: int = 8) -> list[StockSearchHit]:
        calls.append(query)
        return default

    monkeypatch.setattr(quote_tools, "search_stocks_by_name", fake)
    return calls


@pytest.fixture
def mock_adapter() -> MagicMock:
    adp = MagicMock()
    adp.get_quote.return_value = _make_quote()
    return adp


@pytest.fixture
def registry(mock_adapter: MagicMock) -> ToolRegistry:
    return ToolRegistry(ToolContext(adapter=mock_adapter))


class TestSearchStockTool:
    def test_registered(self) -> None:
        assert "search_stock" in ToolRegistry.tool_names()

    def test_returns_hits(self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_search(monkeypatch)
        data = json.loads(registry.call("search_stock", {"query": "比亚迪"}))
        assert data["count"] == 1
        assert data["results"][0] == {
            "code": "002594",
            "name": "比亚迪",
            "market": "A股",
        }

    def test_empty_query_error(self, registry: ToolRegistry) -> None:
        data = json.loads(registry.call("search_stock", {"query": "  "}))
        assert "error" in data

    def test_no_hit_returns_error_with_hint(
        self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_search(monkeypatch, hits=[])
        data = json.loads(registry.call("search_stock", {"query": "不存在的股票"}))
        assert "未找到" in data["error"]
        assert "hint" in data

    def test_limit_clamped(self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            quote_tools,
            "search_stocks_by_name",
            lambda q, limit=8: seen.update(query=q, limit=limit) or _BYD_HITS,
        )
        registry.call("search_stock", {"query": "比亚迪", "limit": 99})
        assert seen["limit"] == 20


class TestGetQuoteNameFallback:
    def test_code_passthrough_no_search(
        self,
        registry: ToolRegistry,
        mock_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """纯代码输入不触发名称搜索，直接走 adapter。"""
        calls = _mock_search(monkeypatch)
        registry.call("get_quote", {"code": "002594"})
        assert calls == []
        mock_adapter.get_quote.assert_called_once_with("002594")

    def test_index_code_passthrough(
        self,
        registry: ToolRegistry,
        mock_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = _mock_search(monkeypatch)
        registry.call("get_quote", {"code": "^GSPC"})
        assert calls == []
        mock_adapter.get_quote.assert_called_once_with("^GSPC")

    def test_name_resolved_to_code(
        self,
        registry: ToolRegistry,
        mock_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _mock_search(monkeypatch)
        data = json.loads(registry.call("get_quote", {"code": "比亚迪"}))
        assert data["code"] == "002594"
        assert data["name"] == "比亚迪"
        mock_adapter.get_quote.assert_called_once_with("002594")

    def test_unresolvable_name_returns_hint(
        self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_search(monkeypatch, hits=[])
        data = json.loads(registry.call("get_quote", {"code": "不存在的股票"}))
        assert "未找到" in data["error"]
        assert "search_stock" in data["hint"]

    def test_prefers_exact_name_match(
        self,
        registry: ToolRegistry,
        mock_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hits = [
            StockSearchHit(code="300750", name="比亚迪供应商", market="A股"),
            StockSearchHit(code="002594", name="比亚迪", market="A股"),
        ]
        _mock_search(monkeypatch, hits=hits)
        registry.call("get_quote", {"code": "比亚迪"})
        mock_adapter.get_quote.assert_called_once_with("002594")

    def test_uses_top_hit_when_no_exact_match(
        self,
        registry: ToolRegistry,
        mock_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hits = [StockSearchHit(code="AAPL", name="苹果", market="US")]
        _mock_search(monkeypatch, hits=hits)
        registry.call("get_quote", {"code": "apple公司"})
        mock_adapter.get_quote.assert_called_once_with("AAPL")


class TestGetQuoteDef:
    def test_code_param_accepts_names(self) -> None:
        """参数 schema 不再用 pattern 限制为纯代码（名称由 handler 解析）。"""
        defs = {td.name: td for td in quote_tools.DEFS}
        code_prop = defs["get_quote"].parameters["properties"]["code"]
        assert "pattern" not in code_prop
