"""Agent tools alerts + holdings handler 测试（PLAN 三档 #12）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools.alerts import HANDLERS as ALERTS_HANDLERS
from mommy_chaogu.agent.tools.base import ToolContext
from mommy_chaogu.agent.tools.holdings import HANDLERS as HOLDINGS_HANDLERS

# ---------------------------------------------------------------------------
# manage_alert handler
# ---------------------------------------------------------------------------


class TestManageAlert:
    def test_add_alert(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](
            ctx,
            {
                "action": "add",
                "code": "600519",
                "condition": "price_above",
                "threshold": 1700,
                "name": "贵州茅台",
            },
        )
        import json

        data = json.loads(result)
        assert "id" in data
        assert data["code"] == "600519"
        assert data["threshold"] == 1700.0

    def test_add_missing_code(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "add"})
        import json

        assert "error" in json.loads(result)

    def test_add_missing_condition(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "add", "code": "600519"})
        import json

        assert "error" in json.loads(result)

    def test_add_missing_threshold(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](
            ctx, {"action": "add", "code": "600519", "condition": "price_above"}
        )
        import json

        assert "error" in json.loads(result)

    def test_add_invalid_condition(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](
            ctx,
            {
                "action": "add",
                "code": "600519",
                "condition": "invalid_condition",
                "threshold": 100,
            },
        )
        import json

        assert "error" in json.loads(result)

    def test_list_all(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        # 先加一条
        ALERTS_HANDLERS["manage_alert"](
            ctx,
            {"action": "add", "code": "600519", "condition": "price_above", "threshold": 1700},
        )
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "list"})
        import json

        data = json.loads(result)
        assert data["count"] == 1
        assert data["alerts"][0]["code"] == "600519"

    def test_list_by_code(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        ALERTS_HANDLERS["manage_alert"](
            ctx,
            {"action": "add", "code": "600519", "condition": "price_above", "threshold": 1700},
        )
        ALERTS_HANDLERS["manage_alert"](
            ctx,
            {"action": "add", "code": "000001", "condition": "price_below", "threshold": 15},
        )
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "list", "code": "600519"})
        import json

        data = json.loads(result)
        assert data["count"] == 1

    def test_remove_alert(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        add_result = ALERTS_HANDLERS["manage_alert"](
            ctx,
            {"action": "add", "code": "600519", "condition": "price_above", "threshold": 1700},
        )
        import json

        alert_id = json.loads(add_result)["id"]
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "remove", "alert_id": alert_id})
        assert "已删除" in json.loads(result)["message"]

    def test_remove_missing_id(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "remove"})
        import json

        assert "error" in json.loads(result)

    def test_remove_nonexistent(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "remove", "alert_id": 9999})
        import json

        assert "error" in json.loads(result)

    def test_unknown_action(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "test.db")
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "unknown"})
        import json

        assert "error" in json.loads(result)

    def test_db_path_none(self) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=None)
        result = ALERTS_HANDLERS["manage_alert"](ctx, {"action": "list"})
        import json

        assert "error" in json.loads(result)


# ---------------------------------------------------------------------------
# holdings handlers (get_watchlist, get_portfolio, get_portfolio_analysis)
# ---------------------------------------------------------------------------


class TestGetWatchlist:
    def test_no_store_configured(self) -> None:
        ctx = ToolContext(adapter=MagicMock(), watchlist_store=None)
        result = HOLDINGS_HANDLERS["get_watchlist"](ctx, {})
        import json

        assert json.loads(result)["error"] == "自选股未配置"

    def test_returns_entries(self) -> None:
        from mommy_chaogu.watchlist.models import StockEntry

        group = MagicMock()
        group.name = "默认"
        entry = StockEntry(code="600519", name="贵州茅台", group=group, note="测试")
        store = MagicMock()
        store.list_entries.return_value = [entry]
        ctx = ToolContext(adapter=MagicMock(), watchlist_store=store)
        result = HOLDINGS_HANDLERS["get_watchlist"](ctx, {})
        import json

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["code"] == "600519"


class TestGetPortfolio:
    def test_no_store_configured(self) -> None:
        ctx = ToolContext(adapter=MagicMock(), portfolio_store=None)
        result = HOLDINGS_HANDLERS["get_portfolio"](ctx, {})
        import json

        assert json.loads(result)["error"] == "持仓未配置"

    def test_empty_positions(self) -> None:
        store = MagicMock()
        store.list_positions.return_value = []
        ctx = ToolContext(adapter=MagicMock(), portfolio_store=store)
        result = HOLDINGS_HANDLERS["get_portfolio"](ctx, {})
        import json

        data = json.loads(result)
        assert data["positions"] == []
