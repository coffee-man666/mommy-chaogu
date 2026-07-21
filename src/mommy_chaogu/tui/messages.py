"""TUI 消息协议（§5.4）。

现状说明：跨 widget 通信目前实际有两条路径——

1. worker 线程 → 主线程：app.call_from_thread → ChatView 直接方法调用
   （工具指示器、流式 chunk、turn 收尾都走这条，见 app.py）。
2. 主线程内 widget 间：Textual Message。

原设计中 AgentChunk / ToolCallStarted / ToolCallFinished / AgentDone 等
消息从未被实际发送（路径 1 取代了它们），已在 PLAN.md 三档 #9 清理。
目前真正使用的只剩 StepStatus（工作流步骤进度，由 _post_step 发送）。

新增跨 widget 通信时：worker 线程回 UI 用 call_from_thread，主线程内
才用 Message——不要照已被清理的旧设计恢复消息类。
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
