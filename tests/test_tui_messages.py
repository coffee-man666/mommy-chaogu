"""TUI 消息协议单测。

覆盖 tui/messages.py 的所有 Message 子类：
验证构造 + 属性赋值（不依赖 Textual app 运行时）。
"""

from __future__ import annotations

from typing import Any

import pytest

from mommy_chaogu.tui.messages import (
    AgentChunk,
    AgentDone,
    ConnectionChanged,
    PortfolioUpdated,
    QuotesUpdated,
    SectorsUpdated,
    SignalFired,
    StepStatus,
    ToolCallFinished,
    ToolCallStarted,
    WorkflowMatched,
)


class TestQuotesUpdated:
    def test_fields_assigned(self) -> None:
        rows: list[dict[str, Any]] = [{"code": "600519", "price": 1680}]
        msg = QuotesUpdated(rows, "MockAdapter", 1234567890.0)
        assert msg.rows == rows
        assert msg.source_label == "MockAdapter"
        assert msg.ts == 1234567890.0


class TestPortfolioUpdated:
    def test_fields_assigned(self) -> None:
        summary = {"total_cost": "150000"}
        rows = [{"code": "600519", "shares": 100}]
        msg = PortfolioUpdated(summary, rows)
        assert msg.summary == summary
        assert msg.rows == rows


class TestSectorsUpdated:
    def test_fields_assigned(self) -> None:
        rows = [{"code": "BK0475", "name": "半导体"}]
        msg = SectorsUpdated(rows)
        assert msg.rows == rows


class TestSignalFired:
    def test_fields_assigned(self) -> None:
        msg = SignalFired(
            code="600519",
            name="贵州茅台",
            rule="price_above",
            value="1680",
            severity="critical",
            ts="15:00:00",
        )
        assert msg.code == "600519"
        assert msg.name == "贵州茅台"
        assert msg.rule == "price_above"
        assert msg.value == "1680"
        assert msg.severity == "critical"
        assert msg.ts == "15:00:00"


class TestWorkflowMatched:
    def test_fields_assigned(self) -> None:
        steps = ["正在获取大盘指数", "正在获取板块排行"]
        msg = WorkflowMatched("morning_brief", "今日行情概览", steps)
        assert msg.workflow_id == "morning_brief"
        assert msg.title == "今日行情概览"
        assert msg.steps == steps


class TestStepStatus:
    @pytest.mark.parametrize(
        "state",
        ["running", "ok", "fail"],
    )
    def test_fields_assigned(self, state: str) -> None:
        msg = StepStatus(idx=2, state=state, detail="获取行情成功")
        assert msg.idx == 2
        assert msg.state == state
        assert msg.detail == "获取行情成功"

    def test_default_detail_empty(self) -> None:
        msg = StepStatus(idx=0, state="running")
        assert msg.detail == ""


class TestAgentChunk:
    def test_fields_assigned(self) -> None:
        msg = AgentChunk(delta="你好")
        assert msg.delta == "你好"


class TestToolCallStarted:
    def test_fields_assigned(self) -> None:
        args = {"code": "600519"}
        msg = ToolCallStarted(call_id=1, name="get_quote", args=args)
        assert msg.call_id == 1
        assert msg.name == "get_quote"
        assert msg.args == args


class TestToolCallFinished:
    @pytest.mark.parametrize("ok", [True, False])
    def test_fields_assigned(self, ok: bool) -> None:
        msg = ToolCallFinished(call_id=1, ok=ok, elapsed_ms=150, result_digest="...")
        assert msg.call_id == 1
        assert msg.ok is ok
        assert msg.elapsed_ms == 150
        assert msg.result_digest == "..."


class TestAgentDone:
    def test_default_not_interrupted(self) -> None:
        msg = AgentDone(tools_used=3)
        assert msg.tools_used == 3
        assert msg.interrupted is False

    def test_interrupted(self) -> None:
        msg = AgentDone(tools_used=2, interrupted=True)
        assert msg.interrupted is True


class TestConnectionChanged:
    @pytest.mark.parametrize("level", ["live", "degraded", "offline"])
    def test_fields_assigned(self, level: str) -> None:
        msg = ConnectionChanged(level=level, source_label="MockAdapter")
        assert msg.level == level
        assert msg.source_label == "MockAdapter"
