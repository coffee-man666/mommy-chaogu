"""板块工具 handler 单测（mock rankings / sector_api / momentum service）。

覆盖 agent/tools/sector.py 的五个 handler：
- get_sector_ranking: 板块涨跌排行
- search_sector: 板块搜索
- get_sector_stocks: 板块成分股行情
- get_sector_bars: 板块 K 线（BK 代码直通 adapter）
- get_sector_momentum: 板块多日相对强弱排名
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money


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


# ---------- get_sector_bars ----------


def _sector_bar(code: str, day: int, close: str) -> Bar:
    return Bar(
        code=code,
        name="半导体",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 9, 28) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1000,
        turnover=Money.from_yuan("10000"),
        change_pct=Decimal("1.5"),
    )


class TestGetSectorBars:
    def test_bk_code_passes_through_to_adapter(self) -> None:
        """BK 代码直通 adapter（EfinanceAdapter.get_bars 无前缀校验）。"""
        adapter = MagicMock()
        adapter.get_bars.return_value = [_sector_bar("BK1036", 0, "105")]
        registry = ToolRegistry(ToolContext(adapter=adapter))

        result = registry.call("get_sector_bars", {"code": "BK1036", "limit": 10})
        data = json.loads(result)

        adapter.get_bars.assert_called_once_with("BK1036", interval=BarInterval.D1, limit=10)
        assert data[0]["code"] == "BK1036"
        assert data[0]["name"] == "半导体"
        assert data[0]["close"] == 105.0
        assert data[0]["change_pct"] == 1.5

    def test_defaults_and_limit_clamp(self) -> None:
        adapter = MagicMock()
        adapter.get_bars.return_value = []
        registry = ToolRegistry(ToolContext(adapter=adapter))

        registry.call("get_sector_bars", {"code": "BK1036", "limit": 9999})
        kwargs = adapter.get_bars.call_args.kwargs
        assert kwargs["interval"] == BarInterval.D1
        assert kwargs["limit"] == 120  # 超限钳到上限

    def test_empty_bars_returns_empty_list(self) -> None:
        adapter = MagicMock()
        adapter.get_bars.return_value = []
        registry = ToolRegistry(ToolContext(adapter=adapter))
        result = registry.call("get_sector_bars", {"code": "BK9999"})
        assert json.loads(result) == []


# ---------- get_sector_momentum ----------


class TestGetSectorMomentum:
    def _fake_service_class(self, captured: dict[str, Any], result: dict[str, Any]) -> type:
        class FakeService:
            def __init__(self, adapter: Any, *, store: Any = None) -> None:
                captured["adapter"] = adapter
                captured["store"] = store

            def compute(self, days: int = 20, *, include_concept: bool = False) -> dict[str, Any]:
                captured["days"] = days
                captured["include_concept"] = include_concept
                return result

        return FakeService

    def test_returns_top_rows_with_data_cutoff(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}
        ranking = [
            {
                "code": f"BK10{i:02d}",
                "name": f"板块{i}",
                "board_type": "industry",
                "return_pct": Decimal("21.00") - i,
                "return_pct_prev": Decimal("0.00"),
                "rank": i + 1,
                "rank_prev": 25 - i,
                "rank_change": 24 - 2 * i,
                "bars_used": 41,
                "as_of": "2026-09-30",
            }
            for i in range(25)
        ]
        result = {
            "days": 20,
            "pool_source": "clist",
            "pool_complete": True,
            "pool_size": 25,
            "boards_evaluated": 25,
            "boards_missing": 0,
            "data_cutoff": "2026-09-30",
            "ranking": ranking,
            "note": "探索性观察",
        }
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.SectorMomentumService",
            self._fake_service_class(captured, result),
        )

        payload = json.loads(registry.call("get_sector_momentum", {"days": 20, "top": 10}))

        assert captured["days"] == 20
        assert captured["include_concept"] is False
        # top 截断 + 全量计数（防 8KB 截断洪水）
        assert len(payload["ranking"]) == 10
        assert payload["showing_top"] == "10/25"
        assert payload["data_cutoff"] == "2026-09-30"
        assert payload["ranking"][0]["return_pct"] == 21.0  # Decimal → float
        assert payload["ranking"][0]["rank_change"] == 24

    def test_defaults_and_concept_flag(
        self,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.SectorMomentumService",
            self._fake_service_class(captured, {"error": "板块池不可用"}),
        )
        payload = json.loads(registry.call("get_sector_momentum", {}))
        assert captured["days"] == 20
        assert captured["include_concept"] is False
        assert "error" in payload

        registry.call("get_sector_momentum", {"include_concept": True, "days": 5, "top": 3})
        assert captured["days"] == 5
        assert captured["include_concept"] is True

    def test_market_db_provided_to_service_for_cache_fallback(
        self,
        tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """market_db 已配置时服务拿到 CacheStore（板块池失败回退 bar_cache 所需）。"""
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "mommy_chaogu.agent.tools.sector.SectorMomentumService",
            self._fake_service_class(captured, {"days": 20, "ranking": []}),
        )
        ctx = ToolContext(adapter=MagicMock(), market_db=tmp_path / "market.db")
        ToolRegistry(ctx).call("get_sector_momentum", {})
        assert captured["store"] is not None

        # 未配置 market_db → 无回退池（store=None）
        captured.clear()
        ToolRegistry(ToolContext(adapter=MagicMock())).call("get_sector_momentum", {})
        assert captured["store"] is None
