"""ToolContext 数据库字段拆分测试（EVALUATION-2026-07-18 T1）。

修复前所有入口统一传 ``db_path=AGENT_DB``，导致：
- agent 对话里设的自定义告警写进 agent.db，监控进程读 portfolio.db → 告警失效
- backfill_history 回填进 agent.db，缓存层读 market.db → 回填无效

拆分后：manage_alert → portfolio_db，backfill_history → market_db，
记忆工具 → agent_db；仅传旧 db_path 时回退行为与修复前一致。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools.alerts import HANDLERS as ALERTS_HANDLERS
from mommy_chaogu.agent.tools.bars import HANDLERS as BARS_HANDLERS
from mommy_chaogu.agent.tools.base import ToolContext
from mommy_chaogu.agent.tools.memory import HANDLERS as MEMORY_HANDLERS
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Money,
)


def _make_bar(code: str = "600519") -> Bar:
    return Bar(
        code=code,
        name="贵州茅台",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 6, 1, 15, 0, 0),
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        close=Decimal("1680.00"),
        volume=12345678,
        turnover=Money.from_yuan("9999999999"),
        change_pct=Decimal("1.82"),
    )


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


@pytest.fixture
def three_dbs(tmp_path: Path) -> dict[str, Path]:
    return {
        "agent": tmp_path / "agent.db",
        "market": tmp_path / "market.db",
        "portfolio": tmp_path / "portfolio.db",
    }


@pytest.fixture
def split_ctx(three_dbs: dict[str, Path]) -> ToolContext:
    """按生产装配方式拆分三个数据库的 ctx。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = [_make_bar()]
    adapter.get_history_money_flow.return_value = []
    return ToolContext(
        adapter=adapter,
        agent_db=three_dbs["agent"],
        market_db=three_dbs["market"],
        portfolio_db=three_dbs["portfolio"],
    )


class TestResolvedProperties:
    def test_dedicated_fields_win(self, three_dbs: dict[str, Path]) -> None:
        ctx = ToolContext(
            adapter=MagicMock(),
            db_path=three_dbs["agent"],
            agent_db=three_dbs["agent"],
            market_db=three_dbs["market"],
            portfolio_db=three_dbs["portfolio"],
        )
        assert ctx.resolved_agent_db == three_dbs["agent"]
        assert ctx.resolved_market_db == three_dbs["market"]
        assert ctx.resolved_portfolio_db == three_dbs["portfolio"]

    def test_fallback_to_db_path(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.db"
        ctx = ToolContext(adapter=MagicMock(), db_path=legacy)
        assert ctx.resolved_agent_db == legacy
        assert ctx.resolved_market_db == legacy
        assert ctx.resolved_portfolio_db == legacy


class TestAlertUsesPortfolioDb:
    def test_alert_lands_in_portfolio_db(
        self, split_ctx: ToolContext, three_dbs: dict[str, Path]
    ) -> None:
        """agent 设的告警落在 portfolio.db（与监控进程读取一致），不写 agent.db。"""
        result = ALERTS_HANDLERS["manage_alert"](
            split_ctx,
            {"action": "add", "code": "600519", "condition": "price_above", "threshold": 1700},
        )
        assert "error" not in json.loads(result)

        from mommy_chaogu.signals.custom_alerts import CustomAlertStore

        assert len(CustomAlertStore(three_dbs["portfolio"]).list_all()) == 1
        # agent.db 里不应出现告警表
        assert "custom_alerts" not in _tables(three_dbs["agent"])


class TestBackfillUsesMarketDb:
    def test_backfill_writes_to_market_db(
        self, split_ctx: ToolContext, three_dbs: dict[str, Path]
    ) -> None:
        """backfill_history 写进 market.db（与缓存层读取一致），不写 agent.db。"""
        result = BARS_HANDLERS["backfill_history"](split_ctx, {"code": "600519", "days": 5})
        data = json.loads(result)
        assert data["bars_written"] == 1

        from mommy_chaogu.cache.store import CacheStore

        bars = CacheStore(three_dbs["market"]).get_bars("600519", "1d", "forward")
        assert bars is not None and len(bars) == 1
        # agent.db 里不应出现缓存表
        assert "bar_cache" not in _tables(three_dbs["agent"])


class TestMemoryToolsUseAgentDb:
    def test_prediction_history_reads_agent_db(
        self, split_ctx: ToolContext, three_dbs: dict[str, Path]
    ) -> None:
        """记忆工具读 agent.db。"""
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(three_dbs["agent"])
        tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
        )

        result = MEMORY_HANDLERS["get_prediction_history"](split_ctx, {})
        preds = json.loads(result)
        assert len(preds) == 1
        assert preds[0]["code"] == "600519"


class TestLegacyDbPathFallback:
    def test_only_db_path_behaves_as_before(self, tmp_path: Path) -> None:
        """仅传旧 db_path（不传新字段）时，各工具行为与修复前一致。"""
        legacy = tmp_path / "legacy.db"
        adapter = MagicMock()
        adapter.get_bars.return_value = [_make_bar()]
        adapter.get_history_money_flow.return_value = []
        ctx = ToolContext(adapter=adapter, db_path=legacy)

        # 告警 → db_path
        result = ALERTS_HANDLERS["manage_alert"](
            ctx,
            {"action": "add", "code": "600519", "condition": "price_above", "threshold": 1700},
        )
        assert "error" not in json.loads(result)

        # 回填 → db_path
        result = BARS_HANDLERS["backfill_history"](ctx, {"code": "600519", "days": 5})
        assert json.loads(result)["bars_written"] == 1

        # 记忆 → db_path
        result = MEMORY_HANDLERS["get_prediction_history"](ctx, {})
        assert isinstance(json.loads(result), list)

        tables = _tables(legacy)
        assert "custom_alerts" in tables
        assert "bar_cache" in tables

    def test_none_db_still_errors(self) -> None:
        """三个字段都为空时，工具返回明确错误而非崩溃。"""
        ctx = ToolContext(adapter=MagicMock())
        assert "error" in json.loads(ALERTS_HANDLERS["manage_alert"](ctx, {"action": "list"}))
        assert "error" in json.loads(BARS_HANDLERS["backfill_history"](ctx, {"code": "600519"}))
        assert "error" in json.loads(MEMORY_HANDLERS["get_prediction_history"](ctx, {}))
