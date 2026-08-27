"""ThinkingBlock — 推理模型思考过程的折叠展示块。

    ✻ 思考中…                          ← 活动态（回答输出前）
    ✻ 思考完成 · 231 字（Enter 展开）   ← 首个正文/工具调用到达后自动收起
      （展开时：暗色思考全文，限 60 行，截断可见）

思考文本只用于展示，来自流式 ``delta.reason_content``，绝不回流对话历史。
活动态的 append 是纯列表追加，零渲染成本；定型后才渲染头部字数。
"""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

_COLOR = "#a371f7"
_COLOR_DIM = "#8a8f98"
_MAX_LINES = 60


class ThinkingBlock(Vertical):
    """单个思考区块：活动 → 完成（可展开）。"""

    can_focus = True

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("enter", "toggle_detail", "展开/收起思考", show=False),
        Binding("space", "toggle_detail", "展开/收起思考", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(classes="thinking-block -active")
        self._parts: list[str] = []
        self._active = True
        self._expanded = False

    def compose(self) -> ComposeResult:
        yield Static(classes="th-header")
        yield Static(classes="th-body")

    def on_mount(self) -> None:
        self._render_header()
        self.query_one(".th-body", Static).display = False

    # ── 数据（廉价追加，活动态无需重渲染）─────────────────────

    @property
    def is_active(self) -> bool:
        return self._active

    def append(self, delta: str) -> None:
        """追加一段思考 delta。"""
        self._parts.append(delta)

    def finish(self) -> None:
        """思考结束（首个正文 chunk / 工具调用 / 中断）：定型收起。

        极端情况下（挂载同帧即定型）子组件尚未 compose，延迟一帧渲染。
        """
        if not self._active:
            return
        self._active = False
        self.set_class(False, "-active")
        self._render_header()

    def _render_header(self) -> None:
        try:
            header = self.query_one(".th-header", Static)
        except Exception:
            self.call_after_refresh(self._render_header)
            return
        if self._active:
            header.update(Text("✻ 思考中…", style=_COLOR))
            return
        n = sum(len(p) for p in self._parts)
        line = Text(f"✻ 思考完成 · {n} 字", style=_COLOR)
        if n > 0:
            line.append("（Enter 展开查看）", style=_COLOR_DIM)
        else:
            line.append("（空）", style=_COLOR_DIM)
        header.update(line)

    # ── 展开 / 收起 ────────────────────────────────────────────

    def on_click(self) -> None:
        self.action_toggle_detail()

    def action_toggle_detail(self) -> None:
        if self._active or not self._parts:
            return
        self._expanded = not self._expanded
        self.set_class(self._expanded, "-expanded")
        body = self.query_one(".th-body", Static)
        if self._expanded:
            text = "".join(self._parts)
            lines = text.splitlines()
            clipped = "\n".join(lines[:_MAX_LINES])
            if len(lines) > _MAX_LINES:
                clipped += f"\n…（已截断，共 {len(lines)} 行）"
            body.update(Text(clipped, style=_COLOR_DIM))
            body.display = True
        else:
            body.update(Text(""))
            body.display = False
        self.scroll_visible(animate=False)
