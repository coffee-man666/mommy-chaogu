"""TUI 消息协议（§5.4）。

跨 widget 通信一律走 Textual Message，禁止 widget 间直接方法调用。

注：原设计中还有 AgentChunk / ToolCallStarted / ToolCallFinished / AgentDone
等消息，但实际实现走 app.call_from_thread → ChatView 直接方法调用（worker
线程 → 主线程），这些消息从未被发送。清理见 PLAN.md 三档 #9。
实际使用的只剩 StepStatus（工作流步骤进度，由 _post_step 发送）。
"""

from __future__ import annotations

from textual.message import Message


class StepStatus(Message):
    """工作流步骤状态变更。"""

    def __init__(self, idx: int, state: str, detail: str = "") -> None:
        super().__init__()
        self.idx = idx
        self.state = state  # running | ok | fail
        self.detail = detail
