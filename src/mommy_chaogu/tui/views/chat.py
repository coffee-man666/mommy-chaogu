"""ChatView — AI 对话视图（§6.6）。

模式 A：对话流 + 输入框。Tab 键切换到看板。
"""

from __future__ import annotations

import contextlib
import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Static

_log = logging.getLogger(__name__)

# 预设问题（与 Web 快速提问药丸共用配置源）
PRESET_QUESTIONS = [
    "今天大盘怎么样？",
    "分析一下比亚迪",
    "半导体板块怎么样？",
    "主力在买什么？",
    "持仓怎么样？",
    "中报怎么样？",
    "收盘报告",
]

_WELCOME = """\
[dim]╭───────────────────────────────────╮
│  mommy-chaogu · AI 对话            │
│                                   │
│  输入消息开始对话                  │
│  Tab 切换看板 · Ctrl+Q 退出        │
╰───────────────────────────────────╯[/]

"""


class ChatInput(Input):
    """聊天输入框。"""


class ChatView(Vertical):
    """对话视图：对话流 + 输入框。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("ctrl+l", "clear_log", "清屏", show=False),
    ]

    def __init__(self, id: str = "chat") -> None:
        super().__init__(id=id)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat-log"):
            yield Static(_WELCOME, id="chat-welcome")
        yield ChatInput(placeholder="输入消息... (Tab→看板, Ctrl+Q退出)", id="prompt")

    def on_mount(self) -> None:
        self.query_one("#prompt", ChatInput).focus()

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """发送消息。"""
        text = event.value.strip()
        if not text:
            return
        # 委托给 app 处理（app 有 services 上下文）
        self.app.handle_chat_message(text)  # type: ignore[attr-defined]
        event.input.value = ""

    def append_user(self, text: str) -> None:
        """追加用户消息。"""
        log = self.query_one("#chat-log", VerticalScroll)
        # 移除欢迎语
        with contextlib.suppress(Exception):
            log.query_one("#chat-welcome").remove()
        log.mount(Static(f"[bold]你 ›[/] {text}", classes="user-msg"))
        log.scroll_end(animate=False)

    def append_assistant(self, text: str) -> None:
        """追加 Agent 回复。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(f"[bold]mommy ›[/] {text}", classes="assistant-msg"))
        log.scroll_end(animate=False)

    def append_workflow_match(self, title: str, steps: list[str]) -> None:
        """追加工作流匹配卡片。"""
        log = self.query_one("#chat-log", VerticalScroll)
        steps_str = "  ".join(f"⠹ {s}" for s in steps)
        log.mount(Static(
            f"[yellow]⚡ 匹配工作流：{title}[/]\n{steps_str}",
            classes="workflow-card",
        ))
        log.scroll_end(animate=False)

    def append_hint(self, text: str) -> None:
        """追加提示卡片。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(f"[yellow]⚠[/] {text}", classes="hint-card"))
        log.scroll_end(animate=False)

    def update_step_status(self, idx: int, state: str, detail: str = "") -> None:
        """更新步骤状态（简化版：在日志中追加状态行）。"""
        mark = {"ok": "✓", "fail": "✗", "running": "⠹"}.get(state, "?")
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(f"  {mark} {detail}", classes="step-status"))
        log.scroll_end(animate=False)

    def clear_messages(self) -> None:
        """清空对话区。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.query("*").remove()
        log.mount(Static(_WELCOME, id="chat-welcome"))

    def action_clear_log(self) -> None:
        """Ctrl+L 清屏。"""
        self.clear_messages()

    # ------------------------------------------------------------------
    # 流式消息接收（P2 实现）
    # ------------------------------------------------------------------

    # def on_agent_chunk(self, msg: AgentChunk) -> None: ...
    # def on_agent_done(self, msg: AgentDone) -> None: ...
