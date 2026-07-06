"""backfill_history 单测：CacheStore.backfill_history + ToolRegistry handler。"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Money,
    MoneyFlow,
)

# ---------- helpers ----------


def _make_bar(code: str = "600519", day: int = 1) -> Bar:
    return Bar(
        code=code,
        name="贵州茅台",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 6, day, 15, 0, 0),
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        close=Decimal("1680.00"),
        volume=12345678,
        turnover=Money.from_yuan("9999999999"),
        change_pct=Decimal("1.82"),
    )


def _make_money_flow(code: str = "600519", day: int = 1) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name="贵州茅台",
        timestamp=datetime(2026, 6, day, 15, 0, 0),
        main_net=Money.from_yuan("50000000"),
        small_net=Money.from_yuan("-10000000"),
        medium_net=Money.from_yuan("-5000000"),
        large_net=Money.from_yuan("20000000"),
        super_large_net=Money.from_yuan("30000000"),
        main_net_ratio=Decimal("2.5"),
    )


# ---------- CacheStore.backfill_history ----------


class TestBackfillHistory:
    def test_writes_bars_and_flows(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        db = tmp_path / "test.db"
        store = CacheStore(db)

        adapter = MagicMock()
        adapter.get_bars.return_value = [
            _make_bar("600519", day=1),
            _make_bar("600519", day=2),
        ]
        adapter.get_history_money_flow.return_value = [
            _make_money_flow("600519", day=1),
            _make_money_flow("600519", day=2),
        ]

        result = store.backfill_history(adapter, "600519", days=7)

        assert result["bars_written"] == 2
        assert result["flows_written"] == 2
        assert result["errors"] == []

        # Verify data persisted
        bars = store.get_bars("600519", "1d", "forward")
        assert bars is not None and len(bars) == 2
        flows = store.get_money_flow_history("600519")
        assert flows is not None and len(flows) == 2

    def test_collects_errors_on_adapter_failure(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        db = tmp_path / "test.db"
        store = CacheStore(db)

        adapter = MagicMock()
        adapter.get_bars.side_effect = RuntimeError("network error")
        adapter.get_history_money_flow.side_effect = RuntimeError("network error")

        result = store.backfill_history(adapter, "600519", days=7)

        assert result["bars_written"] == 0
        assert result["flows_written"] == 0
        assert len(result["errors"]) == 2
        assert any("bars fetch" in e for e in result["errors"])
        assert any("money_flow fetch" in e for e in result["errors"])


# ---------- ToolRegistry backfill_history handler ----------


class TestBackfillTool:
    def test_tool_returns_error_without_db_path(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        adapter = MagicMock()
        ctx = ToolContext(adapter=adapter, db_path=None)
        registry = ToolRegistry(ctx)

        result = registry.call("backfill_history", {"code": "600519"})
        data = json.loads(result)
        assert "error" in data

    def test_tool_writes_and_returns_counts(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        db = tmp_path / "tool_test.db"
        adapter = MagicMock()
        adapter.get_bars.return_value = [_make_bar("000001", day=1)]
        adapter.get_history_money_flow.return_value = [_make_money_flow("000001", day=1)]

        ctx = ToolContext(adapter=adapter, db_path=db)
        registry = ToolRegistry(ctx)

        result = registry.call("backfill_history", {"code": "000001", "days": 5})
        data = json.loads(result)
        assert data["code"] == "000001"
        assert data["bars_written"] == 1
        assert data["flows_written"] == 1
        assert data["errors"] == []
