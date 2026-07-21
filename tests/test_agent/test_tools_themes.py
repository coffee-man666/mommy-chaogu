"""主题工具 handler 单测（mock ThemeService + adapter）。

覆盖 agent/tools/themes.py 的两个 handler：
- list_themes: 列出所有主题摘要
- get_theme_stocks: 主题成分股 + 实时行情（处理空 theme_id / 无数据 / 降级 / 有行情 等分支）
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
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
        turnover=Money(Decimal("9999999999"), "CNY"),
        turnover_rate=Decimal("0.98"),
        volume_ratio=Decimal("1.23"),
        pe_dynamic=Decimal("25.5"),
        total_market_cap=Money(Decimal("2100000000000"), "CNY"),
        circulating_market_cap=Money(Decimal("2100000000000"), "CNY"),
        timestamp=datetime(2026, 7, 1, 15, 0, 0, tzinfo=UTC),
        extra={"main_net_inflow": Decimal("50000000")},
    )


class _FakeThemeService:
    """可配置返回值的假 ThemeService。"""

    def __init__(
        self,
        themes: list[dict[str, Any]] | None = None,
        quotes: list[dict[str, Any]] | None = None,
        theme_detail: dict[str, Any] | None = None,
    ) -> None:
        self._themes = themes if themes is not None else []
        self._quotes = quotes if quotes is not None else []
        self._theme_detail = theme_detail
        # 记录构造参数，供断言 adapter 注入
        self.adapter: Any = None

    def __call__(self, adapter: Any = None) -> _FakeThemeService:
        # 拦截 ThemeService(adapter=...) 构造
        self.adapter = adapter
        return self

    def list_themes(self) -> list[dict[str, Any]]:
        return self._themes

    def get_theme(self, theme_id: str) -> dict[str, Any] | None:
        return self._theme_detail

    def get_theme_quotes(self, theme_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._quotes


@pytest.fixture
def ctx() -> ToolContext:
    adapter = MagicMock()
    return ToolContext(adapter=adapter, watchlist_store=None, portfolio_store=None)


@pytest.fixture
def registry(ctx: ToolContext) -> ToolRegistry:
    return ToolRegistry(ctx)


# ---------- list_themes ----------


class TestListThemes:
    def test_returns_theme_summaries(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        long_desc = "半导体全产业链观察 " * 30  # > 120 字
        fake = _FakeThemeService(
            themes=[
                {
                    "id": "semiconductor",
                    "name": "半导体",
                    "total_stocks": 42,
                    "subcategories": ["设计", "制造", "封测"],
                    "description": long_desc,
                    "source": "supply_chain",
                }
            ]
        )
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)

        result = registry.call("list_themes", {})
        data = json.loads(result)
        assert len(data) == 1
        item = data[0]
        assert item["id"] == "semiconductor"
        assert item["name"] == "半导体"
        assert item["total_stocks"] == 42
        assert item["subcategories"] == ["设计", "制造", "封测"]
        # description 截断到 120 字
        assert len(item["description"]) == 120

    def test_empty_themes_returns_empty_list(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.services.theme_service.ThemeService", _FakeThemeService(themes=[])
        )
        result = registry.call("list_themes", {})
        assert json.loads(result) == []


# ---------- get_theme_stocks ----------


class TestGetThemeStocks:
    def test_missing_theme_id_returns_error(self, registry: ToolRegistry) -> None:
        result = registry.call("get_theme_stocks", {})
        data = json.loads(result)
        assert "error" in data
        assert "theme_id" in data["error"]

    def test_no_data_returns_error(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = _FakeThemeService(quotes=[])
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)
        result = registry.call("get_theme_stocks", {"theme_id": "nonexistent"})
        data = json.loads(result)
        assert "error" in data
        assert "nonexistent" in data["error"]

    def test_stocks_with_quotes(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = _FakeThemeService(
            quotes=[
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "subcategory": "白酒",
                    "level": "核心",
                    "role": "龙头",
                    "price": Decimal("1680.00"),
                    "change_pct": Decimal("1.82"),
                    "volume": 12345678,
                    "turnover_rate": Decimal("0.98"),
                    "pe": Decimal("25.5"),
                    "main_net_inflow": Decimal("50000000"),
                    "growth_text": "",
                    "core_driver": "",
                    "error": None,
                }
            ]
        )
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)

        result = registry.call("get_theme_stocks", {"theme_id": "semiconductor"})
        data = json.loads(result)
        assert len(data) == 1
        item = data[0]
        assert item["code"] == "600519"
        assert item["name"] == "贵州茅台"
        assert item["subcategory"] == "白酒"
        assert item["level"] == "核心"
        assert item["role"] == "龙头"
        # 行情字段转 float
        assert item["price"] == 1680.0
        assert item["change_pct"] == 1.82
        assert item["volume"] == 12345678
        assert item["pe"] == 25.5
        assert item["main_net_inflow"] == 50000000.0

    def test_stocks_without_price_skip_quote_fields(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """price 为 None 时不附加行情字段（降级路径）。"""
        fake = _FakeThemeService(
            quotes=[
                {
                    "code": "300001",
                    "name": "某股",
                    "subcategory": "",
                    "level": "",
                    "role": "",
                    "price": None,
                    "change_pct": None,
                    "volume": None,
                    "turnover_rate": None,
                    "pe": None,
                    "main_net_inflow": None,
                    "growth_text": "",
                    "core_driver": "",
                    "error": None,
                }
            ]
        )
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)

        result = registry.call("get_theme_stocks", {"theme_id": "test"})
        data = json.loads(result)
        assert len(data) == 1
        item = data[0]
        assert item["code"] == "300001"
        # price 为 None → 不附加 price/change_pct/volume/pe/main_net_inflow
        assert "price" not in item
        assert "change_pct" not in item

    def test_earnings_watch_growth_fields(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """earnings_watch 主题带 growth_text 和 core_driver。"""
        fake = _FakeThemeService(
            quotes=[
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "subcategory": "白酒",
                    "level": "",
                    "role": "",
                    "price": Decimal("1680"),
                    "change_pct": Decimal("1.82"),
                    "volume": 100,
                    "turnover_rate": None,
                    "pe": None,
                    "main_net_inflow": None,
                    "growth_text": "净利润 +18.5%",
                    "core_driver": "高端白酒提价",
                    "error": None,
                }
            ]
        )
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)

        result = registry.call("get_theme_stocks", {"theme_id": "earnings_watch"})
        data = json.loads(result)
        item = data[0]
        assert item["growth_text"] == "净利润 +18.5%"
        assert item["core_driver"] == "高端白酒提价"

    def test_zero_pe_included_as_none(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pe 为 0（falsy）时转 None。"""
        fake = _FakeThemeService(
            quotes=[
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "subcategory": "",
                    "level": "",
                    "role": "",
                    "price": Decimal("1680"),
                    "change_pct": Decimal("1.82"),
                    "volume": 100,
                    "turnover_rate": None,
                    "pe": Decimal("0"),
                    "main_net_inflow": Decimal("0"),
                    "growth_text": "",
                    "core_driver": "",
                    "error": None,
                }
            ]
        )
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)

        result = registry.call("get_theme_stocks", {"theme_id": "test"})
        data = json.loads(result)
        item = data[0]
        assert item["pe"] is None
        assert item["main_net_inflow"] is None

    def test_adapter_injected_from_ctx(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """handler 应该用 ctx.adapter 构造 ThemeService。"""
        fake = _FakeThemeService(
            quotes=[{"code": "600519", "name": "x", "price": None, "error": None}]
        )
        monkeypatch.setattr("mommy_chaogu.services.theme_service.ThemeService", fake)

        registry.call("get_theme_stocks", {"theme_id": "test"})
        assert fake.adapter is ctx.adapter
