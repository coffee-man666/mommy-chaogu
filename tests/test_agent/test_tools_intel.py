"""资讯/基本面工具 handler 单测（mock news_api / fundamentals_api）。

覆盖 agent/tools/intel.py 的四个 handler：
- search_news: 新闻搜索
- get_announcements: 公告
- get_longhuban: 龙虎榜
- get_fundamentals: 基本面
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    ctx = ToolContext(adapter=MagicMock(), watchlist_store=None, portfolio_store=None)
    return ToolRegistry(ctx)


# ---------- search_news ----------


class TestSearchNews:
    def test_returns_news_list(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_search_news(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
            captured["keyword"] = keyword
            captured["limit"] = limit
            return [
                {
                    "title": "创新药政策利好",
                    "url": "http://example.com/1",
                    "date": "2026-07-01",
                    "source": "财联社",
                    "summary": "摘要",
                }
            ]

        monkeypatch.setattr("mommy_chaogu.agent.tools.intel.search_news", fake_search_news)

        result = registry.call("search_news", {"keyword": "创新药", "limit": 5})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "创新药政策利好"
        assert captured["keyword"] == "创新药"
        assert captured["limit"] == 5

    def test_default_limit(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_search_news(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
            captured["limit"] = limit
            return []

        monkeypatch.setattr("mommy_chaogu.agent.tools.intel.search_news", fake_search_news)

        registry.call("search_news", {"keyword": "半导体"})
        assert captured["limit"] == 10

    def test_empty_result(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.intel.search_news",
            lambda keyword, limit=10: [],
        )
        result = registry.call("search_news", {"keyword": "无结果"})
        assert json.loads(result) == []


# ---------- get_announcements ----------


class TestGetAnnouncements:
    def test_returns_announcements(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get_announcements(code: str, limit: int = 10) -> list[dict[str, Any]]:
            captured["code"] = code
            captured["limit"] = limit
            return [
                {
                    "title": "关于xxx的公告",
                    "date": "2026-07-01",
                    "ann_type": "董事会决议",
                    "url": "http://example.com/ann/1",
                }
            ]

        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.intel.get_announcements", fake_get_announcements
        )

        result = registry.call("get_announcements", {"code": "600519", "limit": 3})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "关于xxx的公告"
        assert captured["code"] == "600519"
        assert captured["limit"] == 3

    def test_default_limit(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get_announcements(code: str, limit: int = 10) -> list[dict[str, Any]]:
            captured["limit"] = limit
            return []

        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.intel.get_announcements", fake_get_announcements
        )

        registry.call("get_announcements", {"code": "000001"})
        assert captured["limit"] == 10


# ---------- get_longhuban ----------


class TestGetLonghuban:
    def test_returns_longhuban(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get_longhuban(date: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
            captured["date"] = date
            captured["limit"] = limit
            return [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "date": "2026-07-01",
                    "change_rate": 3.5,
                    "reason": "日涨幅偏离值达7%",
                    "net_buy_amount": 50000000.0,
                    "rank": 1,
                }
            ]

        monkeypatch.setattr("mommy_chaogu.agent.tools.intel.get_longhuban", fake_get_longhuban)

        result = registry.call("get_longhuban", {"date": "2026-07-01", "limit": 10})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["code"] == "600519"
        assert data[0]["net_buy_amount"] == 50000000.0
        assert captured["date"] == "2026-07-01"
        assert captured["limit"] == 10

    def test_defaults_no_date_no_limit(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get_longhuban(date: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
            captured["date"] = date
            captured["limit"] = limit
            return []

        monkeypatch.setattr("mommy_chaogu.agent.tools.intel.get_longhuban", fake_get_longhuban)

        registry.call("get_longhuban", {})
        assert captured["date"] is None
        assert captured["limit"] == 20


# ---------- get_fundamentals ----------


class TestGetFundamentals:
    def test_returns_fundamentals(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get_fundamentals(code: str) -> dict[str, Any]:
            captured["code"] = code
            return {
                "code": code,
                "name": "贵州茅台",
                "pe": 25.5,
                "pb": 8.2,
                "ps": 15.0,
                "roe": 30.0,
                "gross_margin": 90.0,
                "net_margin": 50.0,
                "total_market_cap": 2100000000000,
                "circulating_market_cap": 2100000000000,
                "industry": "白酒",
            }

        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.intel.get_fundamentals", fake_get_fundamentals
        )

        result = registry.call("get_fundamentals", {"code": "600519"})
        data = json.loads(result)
        assert data["code"] == "600519"
        assert data["name"] == "贵州茅台"
        assert data["pe"] == 25.5
        assert data["industry"] == "白酒"
        assert captured["code"] == "600519"
