"""TUI 消息协议（§5.4）。

跨 widget 通信一律走 Textual Message，禁止 widget 间直接方法调用。
"""

from __future__ import annotations

from typing import Any

from textual.message import Message


class QuotesUpdated(Message):
    """自选股报价更新。"""

    def __init__(self, rows: list[dict[str, Any]], source_label: str, ts: float) -> None:
        super().__init__()
        self.rows = rows
        self.source_label = source_label
        self.ts = ts


class PortfolioUpdated(Message):
    """持仓更新。"""

    def __init__(self, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self.summary = summary
        self.rows = rows


class SectorsUpdated(Message):
    """板块排行更新。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self.rows = rows


class SignalFired(Message):
    """信号触发。"""

    def __init__(
        self,
        code: str,
        name: str,
        rule: str,
        value: str,
        severity: str,
        ts: str,
    ) -> None:
        super().__init__()
        self.code = code
        self.name = name
        self.rule = rule
        self.value = value
        self.severity = severity
        self.ts = ts


class WorkflowMatched(Message):
    """工作流匹配成功。"""

    def __init__(self, workflow_id: str, title: str, steps: list[str]) -> None:
        super().__init__()
        self.workflow_id = workflow_id
        self.title = title
        self.steps = steps


class StepStatus(Message):
    """工作流步骤状态变更。"""

    def __init__(self, idx: int, state: str, detail: str = "") -> None:
        super().__init__()
        self.idx = idx
        self.state = state  # running | ok | fail
        self.detail = detail


class AgentChunk(Message):
    """Agent 流式输出片段。"""

    def __init__(self, delta: str) -> None:
        super().__init__()
        self.delta = delta


class ToolCallStarted(Message):
    """工具调用开始。"""

    def __init__(self, call_id: int, name: str, args: dict[str, Any]) -> None:
        super().__init__()
        self.call_id = call_id
        self.name = name
        self.args = args


class ToolCallFinished(Message):
    """工具调用完成。"""

    def __init__(self, call_id: int, ok: bool, elapsed_ms: int, result_digest: str) -> None:
        super().__init__()
        self.call_id = call_id
        self.ok = ok
        self.elapsed_ms = elapsed_ms
        self.result_digest = result_digest


class AgentDone(Message):
    """Agent 回复完成。"""

    def __init__(self, tools_used: int, interrupted: bool = False) -> None:
        super().__init__()
        self.tools_used = tools_used
        self.interrupted = interrupted


class ConnectionChanged(Message):
    """连接状态变更。"""

    def __init__(self, level: str, source_label: str) -> None:
        super().__init__()
        self.level = level  # live | degraded | offline
        self.source_label = source_label
