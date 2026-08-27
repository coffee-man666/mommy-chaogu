"""ConfirmBar — 内联写操作确认条（Kimi Code / Claude Code 风格）。

Agent 要执行敏感操作（存策略卡 / 启用监控 / 改告警 / 改自选股）时，
在对话流内挂载确认条并抢焦点，用户按：

    y  允许本次
    n / Esc  拒绝
    a  允许，且本会话该工具不再询问

决定后确认条原地定格成一行审计记录（⏸ 工具 · 决定），焦点交回输入框。
决定回调在主线程同步触发；等待方（agent worker 线程）通过 threading.Event
感知，不阻塞 UI。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

_COLOR_PROMPT = "#f5a524"
_COLOR_ALLOW = "#2f9e6e"
_COLOR_DENY = "#e5484d"
_COLOR_SESSION = "#79b8ff"

Decision = str  # "allow" | "deny" | "always"


class ConfirmBar(Vertical):
    """一次写操作的确认请求；只允许被决定一次（重复决定被忽略）。"""

    can_focus = True

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("y", "allow", "允许", show=False),
        Binding("n", "deny", "拒绝", show=False),
        Binding("escape", "deny", "拒绝", show=False),
        Binding("a", "always", "本会话不再询问", show=False),
    ]

    def __init__(
        self,
        display_name: str,
        args_summary: str,
        args_pretty: str,
        on_decision: Callable[[Decision], None],
        focus_back: Callable[[], None],
    ) -> None:
        super().__init__(classes="confirm-bar -pending")
        self._display_name = display_name
        self._args_summary = args_summary
        self._args_pretty = args_pretty
        self._on_decision = on_decision
        self._focus_back = focus_back
        self._resolved = False

    def compose(self) -> ComposeResult:
        yield Static(classes="cb-body")
        yield Static(classes="cb-args")

    def on_mount(self) -> None:
        title = (
            f"{self._display_name}({self._args_summary})"
            if self._args_summary
            else (self._display_name)
        )
        # 用户数据（参数 JSON）一律走 Text 分段，不走 console markup——
        # Textual Content 解析器对「行尾 \\[ 转义 + 闭合标签」有吞标签的
        # 怪癖，且任意参数内容不该被当标记解析（防注入）。
        body = Text("⏸ 允许执行写操作？  ", style=_COLOR_PROMPT)
        body.append(title, style="bold")
        body.append("\n")
        body.append("[y]", style=_COLOR_PROMPT)
        body.append(" 允许   ")
        body.append("[n]", style=_COLOR_DENY)
        body.append(" 拒绝   ")
        body.append("[a]", style=_COLOR_SESSION)
        body.append(" 本会话不再询问")
        self.query_one(".cb-body", Static).update(body)
        args_widget = self.query_one(".cb-args", Static)
        if self._args_pretty:
            args_widget.update(Text(self._args_pretty, style="dim"))
        else:
            args_widget.display = False
        self.focus()

    # ── 决定 ────────────────────────────────────────────────────

    def action_allow(self) -> None:
        self._resolve("allow")

    def action_deny(self) -> None:
        self._resolve("deny")

    def action_always(self) -> None:
        self._resolve("always")

    def _resolve(self, decision: Decision) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._render_resolved(decision)
        self._on_decision(decision)
        # 焦点交回输入框（确认条保留在对话流里作为审计记录）
        self._focus_back()

    def _render_resolved(self, decision: Decision) -> None:
        label, color = {
            "allow": ("✓ 已允许", _COLOR_ALLOW),
            "deny": ("✗ 已拒绝", _COLOR_DENY),
            "always": ("✓ 已允许（本会话不再询问）", _COLOR_ALLOW),
        }[decision]
        title = (
            f"{self._display_name}({self._args_summary})"
            if self._args_summary
            else (self._display_name)
        )
        body = Text("⏸ ", style=_COLOR_PROMPT)
        body.append(title)
        body.append(f"  {label}", style=color)
        self.query_one(".cb-body", Static).update(body)
        with contextlib.suppress(Exception):
            self.query_one(".cb-args", Static).display = False
        self.set_class(False, "-pending")
        self.can_focus = False

    def resolve_external(self, decision: Decision) -> None:
        """外部强制落定（如 /clear、Esc 取消整轮时）：等价 deny。"""
        if self._resolved:
            return
        self._resolved = True
        self._render_resolved(decision)
