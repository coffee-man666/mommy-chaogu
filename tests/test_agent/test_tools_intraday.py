"""阶段六工具单测（全离线）：日内画像工具 + backfill 分钟周期透传。

覆盖：
- get_intraday_profile：DEFS 注册、三段口径输出、典型价近似标注、
  无分钟数据时 error（不产假指标）
- backfill_history：interval=5m 透传到 store（分钟按日打包、不拉资金流）
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Money,
)

CODE = "600519"
_UTC_OFFSET = timedelta(hours=8)


def _m5_bar(hh: int, mm: int, close: str, vol: int) -> Bar:
    ts = datetime(2026, 9, 30, hh, mm).replace(tzinfo=UTC) - _UTC_OFFSET  # 北京墙时间 → aware UTC
    return Bar(
        code=CODE,
        name="测试股",
        interval=BarInterval.M5,
        adjustment=AdjustmentType.NONE,
        timestamp=ts,
        open=Decimal(close),
        high=Decimal(close) + Decimal("1"),
        low=Decimal(close) - Decimal("1"),
        close=Decimal(close),
        volume=vol,
        turnover=Money(Decimal("0")),
    )


class FakeAdapter:
    name = "fake"

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars
        self.calls: list[dict[str, Any]] = []

    def get_quote(self, code: str) -> None:
        return None

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: Any = None,
        end: Any = None,
        limit: int | None = None,
    ) -> list[Bar]:
        self.calls.append({"code": code, "interval": interval, "limit": limit})
        return list(self._bars)

    def get_history_money_flow(self, code: str, days: int = 30) -> list[Any]:
        raise AssertionError("分钟回填不应触发资金流拉取")


# ---------- get_intraday_profile ----------


class TestGetIntradayProfile:
    def test_tool_registered_in_definitions(self) -> None:
        defs = ToolRegistry(ToolContext(adapter=MagicMock())).definitions()
        names = {d["function"]["name"] for d in defs}
        assert "get_intraday_profile" in names

    def test_returns_three_sections_with_typical_price_note(self) -> None:
        bars = [
            _m5_bar(9, 30, "101", 100),
            _m5_bar(9, 55, "104", 50),
            _m5_bar(14, 30, "104", 200),
            _m5_bar(14, 35, "105", 200),
        ]
        adapter = FakeAdapter(bars)
        registry = ToolRegistry(ToolContext(adapter=adapter))

        result = registry.call("get_intraday_profile", {"code": CODE})
        data = json.loads(result)

        assert data["code"] == CODE
        assert data["trade_date"] == "2026-09-30"
        # 5 分钟 K 数据入口（M5、有限根数）
        assert adapter.calls[-1]["interval"] == BarInterval.M5
        # 三段齐备
        for section in ("open_half_hour", "vwap", "tail"):
            assert section in data
        # 典型价近似标注（阶段六验收硬要求）
        assert "典型价近似" in data["vwap"]["note"]
        assert any("典型价近似" in n for n in data["notes"])
        # 数值经 _floatify 后是 float（工具层 Decimal→float 约定）
        assert isinstance(data["vwap"]["value"], float)

    def test_no_minute_data_returns_error(self) -> None:
        registry = ToolRegistry(ToolContext(adapter=FakeAdapter([])))
        data = json.loads(registry.call("get_intraday_profile", {"code": "300750"}))
        assert "error" in data
        assert "vwap" not in data


# ---------- backfill_history interval 透传 ----------


class TestBackfillMinuteInterval:
    def test_tool_passes_interval_and_skips_flows(self, tmp_path: Path) -> None:
        db = tmp_path / "tool_test.db"
        adapter = FakeAdapter(
            [
                _m5_bar(1, 30, "10.00", 100),  # 北京 09:30
                _m5_bar(1, 35, "10.01", 100),  # 北京 09:35
            ]
        )
        ctx = ToolContext(adapter=adapter, db_path=db)
        registry = ToolRegistry(ctx)

        data = json.loads(
            registry.call("backfill_history", {"code": CODE, "days": 10, "interval": "5m"})
        )

        assert data["interval"] == "5m"
        assert data["bars_written"] == 2
        assert data["flows_written"] == 0
        assert adapter.calls[-1]["interval"] == BarInterval.M5

        # 落库为按日打包单行，可完整读回；行键 = bar 自身口径（本 Fake 源
        # 返回不复权数据 → none 键，请求默认 forward 不改标——口径诚实）
        from mommy_chaogu.cache.store import CacheStore

        store = CacheStore(db)
        rows = store.get_bars(CODE, BarInterval.M5.value, AdjustmentType.NONE.value)
        assert rows is not None
        assert len(rows) == 2
        assert {r["adjustment"] for r in rows} == {"none"}
        assert store.get_bars(CODE, BarInterval.M5.value, AdjustmentType.FORWARD.value) is None
        assert store.stats()["bars"] == 1
