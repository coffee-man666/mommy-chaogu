"""板块工具 handler 单测（mock rankings / sector_api）。

覆盖 agent/tools/sector.py 的三个 handler：
- get_sector_ranking: 板块涨跌排行
- search_sector: 板块搜索
- get_sector_stocks: 板块成分股行情
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    ctx = ToolContext(adapter=MagicMock(), watchlist_store=None, portfolio_store=None)
    return ToolRegistry(ctx)


# ---------- get_sector_ranking ----------


class TestGetSectorRanking:
    def test_returns_ranking(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_fetch(limit: int = 30) -> list[dict[str, Any]]:
            captured["limit"] = limit
            return [
                {
                    "code": "BK0475",
                    "name": "半导体",
                    "change_pct": Decimal("3.5"),
                    "price": Decimal("1000"),
                },
                {
                    "code": "BK1106",
                    "name": "创新药",
                    "change_pct": Decimal("2.1"),
                    "price": Decimal("800"),
                },
            ]

        monkeypatch.setattr("mommy_chaogu.agent.tools.sector.fetch_sector_ranking", fake_fetch)

        result = registry.call("get_sector_ranking", {"limit": 10})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["code"] == "BK0475"
        assert data[0]["name"] == "半导体"
        # Decimal → float
        assert data[0]["change_pct"] == 3.5
        assert captured["limit"] == 10

    def test_default_limit(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_fetch(limit: int = 30) -> list[dict[str, Any]]:
            captured["limit"] = limit
            return []

        monkeypatch.setattr("mommy_chaogu.agent.tools.sector.fetch_sector_ranking", fake_fetch)

        registry.call("get_sector_ranking", {})
        assert captured["limit"] == 30

    def test_empty_ranking(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.fetch_sector_ranking",
            lambda limit=30: [],
        )
        result = registry.call("get_sector_ranking", {})
        assert json.loads(result) == []


# ---------- search_sector ----------


class TestSearchSector:
    def test_returns_matches(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_search(keyword: str) -> list[dict[str, str]]:
            captured["keyword"] = keyword
            return [
                {"code": "BK1106", "name": "创新药", "secid": "90.BK1106"},
                {"code": "BK1107", "name": "创新药械", "secid": "90.BK1107"},
            ]

        monkeypatch.setattr("mommy_chaogu.agent.tools.sector.search_sector", fake_search)

        result = registry.call("search_sector", {"keyword": "创新药"})
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["code"] == "BK1106"
        assert data[0]["name"] == "创新药"
        assert captured["keyword"] == "创新药"

    def test_no_matches(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.search_sector",
            lambda keyword: [],
        )
        result = registry.call("search_sector", {"keyword": "不存在的板块"})
        assert json.loads(result) == []


# ---------- get_sector_stocks ----------


class TestGetSectorStocks:
    def test_returns_stocks(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_fetch_stocks(
            board_code: str,
            sort_by: str = "change_pct",
            limit: int = 30,
        ) -> list[dict[str, Any]]:
            captured["board_code"] = board_code
            captured["sort_by"] = sort_by
            captured["limit"] = limit
            return [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "price": 1680.0,
                    "change_pct": 1.82,
                }
            ]

        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.fetch_sector_stocks", fake_fetch_stocks
        )

        result = registry.call(
            "get_sector_stocks",
            {"board_code": "BK1106", "sort_by": "main_net", "limit": 15},
        )
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["code"] == "600519"
        assert data[0]["price"] == 1680.0
        assert captured["board_code"] == "BK1106"
        assert captured["sort_by"] == "main_net"
        assert captured["limit"] == 15

    def test_defaults(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_fetch_stocks(
            board_code: str,
            sort_by: str = "change_pct",
            limit: int = 30,
        ) -> list[dict[str, Any]]:
            captured["sort_by"] = sort_by
            captured["limit"] = limit
            return []

        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.fetch_sector_stocks", fake_fetch_stocks
        )

        registry.call("get_sector_stocks", {"board_code": "BK0475"})
        assert captured["sort_by"] == "change_pct"
        assert captured["limit"] == 30

    def test_empty_stocks(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.fetch_sector_stocks",
            lambda board_code, sort_by="change_pct", limit=30: [],
        )
        result = registry.call("get_sector_stocks", {"board_code": "BK9999"})
        assert json.loads(result) == []
