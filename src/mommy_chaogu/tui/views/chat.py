"""ChatView — AI 对话视图（§6.6）。

模式 A：对话流 + 输入框。Tab 键切换到看板。
支持 Claude Code 风格的 /command 斜杠命令（内联补全）。
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.suggester import Suggester
from textual.widgets import Collapsible, Input, Markdown, Static

from mommy_chaogu.tui.messages import StepStatus

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


# ---------------------------------------------------------------------------
# Slash 命令注册表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlashCommand:
    """一条斜杠命令定义。"""

    name: str  # 不含 /，如 "refresh"
    description: str  # 中文说明
    has_args: bool = False  # 是否接受参数


SLASH_COMMANDS: dict[str, SlashCommand] = {
    cmd.name: cmd
    for cmd in [
        SlashCommand("help", "按键速查"),
        SlashCommand("refresh", "刷新行情数据"),
        SlashCommand("clear", "清空对话区"),
        SlashCommand("dashboard", "切换到看板"),
        SlashCommand("chat", "切换到对话"),
        SlashCommand("theme", "切换主题"),
        SlashCommand("watch", "查看个股详情 (如 /watch 688981)", has_args=True),
        SlashCommand("flows", "查看资金流 (如 /flows 688981)", has_args=True),
        SlashCommand("memory", "查看记忆系统"),
        SlashCommand("quit", "退出"),
    ]
}


class SlashSuggester(Suggester):
    """输入 / 时提供内联补全建议（灰色文字）。"""

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        """根据当前输入返回补全建议。"""
        if not value.startswith("/"):
            return None
        # 提取 / 后的命令前缀（casefold 以支持大小写不敏感）
        typed = value[1:].split(None, 1)[0].casefold() if len(value) > 1 else ""
        for name, cmd in SLASH_COMMANDS.items():
            if name.startswith(typed):
                suffix = " " if cmd.has_args else ""
                return f"/{name}{suffix}"
        return None


def _build_welcome() -> str:
    """构建欢迎页文本（含预设问题列表）。"""
    lines = [
        "[bold cyan]mommy-chaogu · AI 对话[/]",
        "",
        "[dim]输入消息开始对话，或按数字键快捷提问：[/]",
        "",
    ]
    for i, q in enumerate(PRESET_QUESTIONS, 1):
        lines.append(f"  [bold]{i}[/]  {q}")
    lines.append("")
    lines.append("[dim]↑↓ 历史记录 · / 命令 · Esc 取消 · Tab 切换看板 · Ctrl+Q 退出[/]")
    lines.append("")
    return "\n".join(lines)


class ChatInput(Input):
    """聊天输入框（支持 ↑↓ 历史导航 + 数字快捷提问 + / 斜杠补全）。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, suggester=SlashSuggester(), **kwargs)  # type: ignore[arg-type]

    def on_key(self, event: events.Key) -> None:
        """拦截 ↑↓（历史导航）和 1-7（预设问题，仅欢迎页可见时）。

        on_key 在 Input._on_key 之前调用（MRO 顺序），
        对需要拦截的按键调用 prevent_default() 阻止 Input._on_key。
        """
        # ↑/↓: 历史导航
        if event.key == "up":
            chat = self._chat_view()
            if chat is not None:
                chat.history_prev()
            event.prevent_default()
            event.stop()
            return
        if event.key == "down":
            chat = self._chat_view()
            if chat is not None:
                chat.history_next()
            event.prevent_default()
            event.stop()
            return
        # 1-7: 预设问题（仅欢迎页可见且输入为空时触发）
        if event.key in ("1", "2", "3", "4", "5", "6", "7") and not self.value:
            chat = self._chat_view()
            if chat is not None and chat.welcome_visible():
                chat.send_preset(int(event.key) - 1)
                event.prevent_default()
                event.stop()
                return

    def _chat_view(self) -> ChatView | None:
        parent = self.parent
        return parent if isinstance(parent, ChatView) else None


class ChatView(Vertical):
    """对话视图：对话流 + 输入框。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("ctrl+l", "clear_log", "清屏", show=False),
        Binding("escape", "cancel_chat", "取消", show=False),
    ]

    def __init__(self, id: str = "chat") -> None:
        super().__init__(id=id)
        self._history: list[str] = []
        self._history_idx: int = -1  # -1 表示在"新输入"位置
        self._busy: bool = False
        self._cancelled: bool = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat-log"):
            yield Static(_build_welcome(), id="chat-welcome")
        yield ChatInput(placeholder="输入消息... (Tab→看板, Esc→取消)", id="prompt")

    def on_mount(self) -> None:
        self.query_one("#prompt", ChatInput).focus()

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        """标记是否正在处理消息。"""
        self._busy = busy
        if busy:
            self._cancelled = False

    def is_cancelled(self) -> bool:
        """检查当前对话是否被取消。"""
        return self._cancelled

    def clear_cancelled(self) -> None:
        """重置取消标记。"""
        self._cancelled = False

    def welcome_visible(self) -> bool:
        """欢迎页是否可见。"""
        try:
            self.query_one("#chat-welcome")
        except Exception:
            return False
        return True

    # ------------------------------------------------------------------
    # 输入历史
    # ------------------------------------------------------------------

    def history_prev(self) -> None:
        """导航到上一条历史消息。"""
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        else:
            return
        prompt = self.query_one("#prompt", ChatInput)
        prompt.value = self._history[self._history_idx]
        prompt.cursor_position = len(prompt.value)

    def history_next(self) -> None:
        """导航到下一条历史消息。"""
        if self._history_idx == -1:
            return
        prompt = self.query_one("#prompt", ChatInput)
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            prompt.value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            prompt.value = ""
        prompt.cursor_position = len(prompt.value)

    # ------------------------------------------------------------------
    # 预设问题
    # ------------------------------------------------------------------

    def send_preset(self, idx: int) -> None:
        """发送预设问题。"""
        if idx < 0 or idx >= len(PRESET_QUESTIONS):
            return
        text = PRESET_QUESTIONS[idx]
        self._history.append(text)
        self._history_idx = -1
        self.app.handle_chat_message(text)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """发送消息或执行斜杠命令。"""
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        if not text:
            return
        # 斜杠命令拦截
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            cmd = parts[0].lower() if parts else ""
            args = parts[1].strip() if len(parts) > 1 else ""
            event.input.value = ""
            self._dispatch_slash(cmd, args)
            return
        # 正常 AI 对话
        self._history.append(text)
        self._history_idx = -1
        self.app.handle_chat_message(text)  # type: ignore[attr-defined]
        event.input.value = ""

    # ------------------------------------------------------------------
    # 斜杠命令分发
    # ------------------------------------------------------------------

    def _dispatch_slash(self, cmd: str, args: str) -> None:
        """执行斜杠命令。"""
        app = self.app
        if cmd not in SLASH_COMMANDS:
            available = ", ".join(f"/{name}" for name in SLASH_COMMANDS)
            self.append_hint(f"未知命令 /{cmd}。可用命令: {available}")
            return

        if cmd == "help":
            app.action_help()  # type: ignore[attr-defined]
        elif cmd == "refresh":
            app.action_refresh()  # type: ignore[attr-defined]
            self.append_hint("数据已刷新")
        elif cmd == "clear":
            self.clear_messages()
        elif cmd == "dashboard":
            from textual.widgets import ContentSwitcher

            switcher = app.query_one("#main", ContentSwitcher)
            switcher.current = "dashboard"
        elif cmd == "chat":
            from textual.widgets import ContentSwitcher

            switcher = app.query_one("#main", ContentSwitcher)
            switcher.current = "chat"
        elif cmd == "theme":
            app.action_cycle_theme()  # type: ignore[attr-defined]
        elif cmd == "watch":
            if not args:
                self.append_hint("用法: /watch <股票代码>，如 /watch 688981")
            else:
                app.open_stock_detail(args)  # type: ignore[attr-defined]
        elif cmd == "flows":
            if not args:
                self.append_hint("用法: /flows <股票代码>，如 /flows 688981")
            else:
                self.append_hint(f"查看 {args} 资金流请在终端运行: mommy flows show {args}")
        elif cmd == "memory":
            self.append_hint("查看记忆请在终端运行: mommy memory stats")
        elif cmd == "quit":
            app.quit()  # type: ignore[attr-defined]

    def append_user(self, text: str) -> None:
        """追加用户消息。"""
        log = self.query_one("#chat-log", VerticalScroll)
        with contextlib.suppress(Exception):
            log.query_one("#chat-welcome").remove()
        log.mount(Static(f"[bold]你 ›[/] {text}", classes="user-msg"))
        log.scroll_end(animate=False)

    def append_assistant(self, text: str) -> None:
        """追加 Agent 回复。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Markdown(f"**mommy ›**\n\n{text}", classes="assistant-msg"))
        log.scroll_end(animate=False)

    def append_workflow_match(self, title: str, steps: list[str]) -> None:
        """追加工作流匹配卡片。"""
        log = self.query_one("#chat-log", VerticalScroll)
        steps_str = "  ".join(f"⠹ {s}" for s in steps)
        log.mount(
            Static(
                f"[yellow]⚡ 匹配工作流：{title}[/]\n{steps_str}",
                classes="workflow-card",
            )
        )
        log.scroll_end(animate=False)

    def append_tool_call(self, name: str, args_summary: str) -> None:
        """追加工具调用记录。"""
        log = self.query_one("#chat-log", VerticalScroll)
        suffix = f"({args_summary})" if args_summary else "()"
        details = Static(f"🔧 {name}{suffix}", classes="tool-call")
        log.mount(
            Collapsible(
                details,
                title=f"🔧 {name}({args_summary})",
                classes="tool-call",
            )
        )
        log.scroll_end(animate=False)

    def append_hint(self, text: str) -> None:
        """追加提示卡片。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(f"[yellow]⚠[/] {text}", classes="hint-card"))
        log.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # 工作流步骤进度（StepStatus 消息驱动）
    # ------------------------------------------------------------------

    def on_step_status(self, msg: StepStatus) -> None:
        """接收 StepStatus 消息并显示步骤进度。"""
        mark = {"ok": "✓", "fail": "✗", "running": "⠹"}.get(msg.state, "?")
        color = {"ok": "green", "fail": "red", "running": "yellow"}.get(msg.state, "white")
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(
            Static(
                f"  [{color}]{mark}[/{color}] {msg.detail}",
                classes="step-status",
            )
        )
        log.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # 清屏 / 取消
    # ------------------------------------------------------------------

    def clear_messages(self) -> None:
        """清空对话区。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.query("*").remove()
        log.mount(Static(_build_welcome(), id="chat-welcome"))

    def action_clear_log(self) -> None:
        """Ctrl+L 清屏。"""
        self.clear_messages()

    def action_cancel_chat(self) -> None:
        """Esc 取消当前对话。"""
        if not self._busy:
            return
        self._cancelled = True
        self._busy = False
        self.append_hint("已取消当前对话")
