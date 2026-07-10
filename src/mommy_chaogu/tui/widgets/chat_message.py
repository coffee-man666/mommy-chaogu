"""单条对话消息（Markdown 渲染）。

左侧角色图标（🤖 assistant / 🧑 user），右侧 Markdown 渲染内容。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Markdown, Static


class ChatMessage(Horizontal):
    """一条对话消息，Markdown 渲染。

    用 Markdown widget 渲染 assistant 回复（不是 RichLog）。
    """

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        min-height: 3;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    ChatMessage > .msg-icon {
        width: 3;
        height: 1;
        color: $accent;
    }
    ChatMessage > .msg-content {
        width: 1fr;
    }
    """

    def __init__(self, role: str, content: str = "", id: str | None = None) -> None:
        super().__init__(id=id)
        self.role = role
        self.content = content

    def compose(self) -> ComposeResult:
        icon = "🤖" if self.role == "assistant" else "🧑"
        yield Static(icon, classes="msg-icon")
        yield Markdown(self.content, classes="msg-content")

    async def update_content(self, content: str) -> None:
        """更新消息内容（Markdown 重新渲染）。"""
        self.content = content
        md = self.query_one(Markdown)
        await md.update(content)
