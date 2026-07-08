"""工具调用展示（可折叠）。

显示 🔧 工具名(参数摘要)，回车展开/折叠结果。
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

# 匹配 Textual DOMNode.BINDINGS 的类型
_Bindings = list[Binding | tuple[str, str] | tuple[str, str, str]]


class ToolIndicator(Widget):
    """工具调用展示（可折叠）。

    头部显示 🔧 tool_name(args_summary)，回车切换展开结果。
    """

    DEFAULT_CSS = """
    ToolIndicator {
        height: auto;
        min-height: 1;
        padding: 0 1;
        margin: 0 0 0 3;
    }
    ToolIndicator > .tool-header {
        height: 1;
        color: $text-muted;
    }
    ToolIndicator > .tool-result {
        height: auto;
        padding: 0 1;
        color: $text;
        display: none;
    }
    ToolIndicator.expanded > .tool-result {
        display: block;
    }
    """

    BINDINGS: ClassVar[_Bindings] = [
        Binding("enter", "toggle_expand", "展开/折叠", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        args_summary: str = "",
        result: str = "",
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.tool_name = tool_name
        self.args_summary = args_summary
        self.result = result

    def compose(self) -> ComposeResult:
        yield Static(f"🔧 {self.tool_name}({self.args_summary})", classes="tool-header")
        yield Static(self.result, classes="tool-result")

    def action_toggle_expand(self) -> None:
        """展开/折叠结果。"""
        if self.has_class("expanded"):
            self.remove_class("expanded")
        else:
            self.add_class("expanded")
