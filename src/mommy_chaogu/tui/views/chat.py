"""ChatView — 单屏对话即界面（§1.2）。

布局：对话流（VerticalScroll）+ HintBar + ChatInput，无模式切换。
- slash 命令在对话流内渲染富卡片（不跳屏）
- @ 触发股票联想（自选股 + 半导体库 + quote_cache），Tab/Enter 插入代码
- 输入 6 位代码时 Enter 直接出报价卡
- busy 时 Enter 排队（轮次结束自动发出）；Esc 中断当前轮（保留已流部分）
- 工具调用/思考状态采用 dexter 风格的 ⏺/⎿ 实时渲染
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from rich.markup import escape
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.suggester import Suggester
from textual.widgets import Input, Markdown, Static

from mommy_chaogu.tui.messages import StepStatus
from mommy_chaogu.tui.services.errors import friendly_error
from mommy_chaogu.tui.services.renderers import is_truncated, render_tool_result
from mommy_chaogu.tui.widgets import cards
from mommy_chaogu.tui.widgets.hint_bar import HintBar
from mommy_chaogu.tui.widgets.tool_indicator import (
    ToolIndicator,
    format_elapsed,
    format_result_digest,
    format_tool_args,
)
from mommy_chaogu.tui.widgets.working_indicator import WorkingIndicator

_log = logging.getLogger(__name__)

_CODE_RE = re.compile(r"(?:[0-9]{6}|[A-Z]{1,6})")
_AT_TOKEN_RE = re.compile(r"@([^\s@]*)$")


# ---------------------------------------------------------------------------
# Slash 命令注册表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlashCommand:
    """一条斜杠命令定义。"""

    name: str  # 不含 /，如 "today"
    description: str  # 中文说明
    has_args: bool = False  # 是否接受参数


SLASH_COMMANDS: dict[str, SlashCommand] = {
    cmd.name: cmd
    for cmd in [
        SlashCommand("today", "今日总览（指数/自选/信号/预测）"),
        SlashCommand("watch", "自选股列表"),
        SlashCommand("portfolio", "持仓"),
        SlashCommand("flows", "资金流（/flows 600519，无参数看自选榜）", has_args=True),
        SlashCommand("quote", "个股报价（/quote 600519）", has_args=True),
        SlashCommand("predictions", "预测跟踪"),
        SlashCommand("signals", "近期信号"),
        SlashCommand("memory", "记忆系统"),
        SlashCommand("status", "服务状态"),
        SlashCommand("help", "按键速查"),
        SlashCommand("clear", "清空对话"),
        SlashCommand("theme", "切换主题"),
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
        matches = match_slash_commands(value)
        if not matches:
            return None
        cmd = matches[0]
        suffix = " " if cmd.has_args else ""
        return f"/{cmd.name}{suffix}"


def match_slash_commands(value: str) -> list[SlashCommand]:
    """按输入前缀匹配斜杠命令（供补全 + HintBar 候选列表共用）。"""
    if not value.startswith("/"):
        return []
    typed = value[1:].split(None, 1)[0].casefold() if len(value) > 1 else ""
    return [cmd for name, cmd in SLASH_COMMANDS.items() if name.startswith(typed)]


def match_stocks(
    candidates: list[tuple[str, str]], query: str, limit: int = 8
) -> list[tuple[str, str]]:
    """@ 联想匹配：代码前缀 + 名称子串（大小写不敏感）。"""
    q = query.casefold()
    if not q:
        return candidates[:limit]
    return [c for c in candidates if c[0].startswith(q) or q in c[1].casefold()][:limit]


def _format_tokens_compact(n: int) -> str:
    """token 数 → dexter 风格紧凑显示（1.2k / 850）。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class ChatInput(Input):
    """聊天输入框（↑↓ 候选选择 / 历史导航 + / 斜杠补全）。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, suggester=SlashSuggester(), **kwargs)  # type: ignore[arg-type]

    def on_key(self, event: events.Key) -> None:
        """拦截 ↑↓：候选选择态循环候选，否则历史导航。

        on_key 在 Input._on_key 之前调用（MRO 顺序），
        对需要拦截的按键调用 prevent_default() 阻止 Input._on_key。
        """
        if event.key in ("up", "down"):
            chat = self._chat_view()
            if chat is not None:
                if chat.in_selection():
                    chat.cycle_selection(-1 if event.key == "up" else 1)
                elif event.key == "up":
                    chat.history_prev()
                else:
                    chat.history_next()
            event.prevent_default()
            event.stop()

    def _chat_view(self) -> ChatView | None:
        parent = self.parent
        return parent if isinstance(parent, ChatView) else None


class ChatView(Vertical):
    """对话视图：对话流 + HintBar + 输入框（单屏，无模式切换）。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("ctrl+l", "clear_log", "清屏", show=False),
        Binding("escape", "cancel_chat", "中断", show=False),
        Binding("tab", "accept_completion", "补全", show=False, priority=True),
        Binding("pageup", "scroll_page_up", "上翻", show=False),
        Binding("pagedown", "scroll_page_down", "下翻", show=False),
    ]

    def __init__(self, id: str = "chat") -> None:
        super().__init__(id=id)
        self._history: list[str] = []
        self._history_idx: int = -1  # -1 表示在"新输入"位置
        self._busy: bool = False
        self._cancelled: bool = False
        self._working: WorkingIndicator | None = None
        self._tool_widgets: dict[int, ToolIndicator] = {}
        self._tool_names: dict[int, str] = {}
        self._step_widgets: dict[tuple[int, int], Static] = {}
        # slash / @ 候选选择态
        self._slash_matches: list[SlashCommand] = []
        self._slash_sel: int = 0
        self._stock_matches: list[tuple[str, str]] = []
        self._stock_sel: int = 0
        self._stock_token_start: int = 0
        # busy 时 Enter 排队的消息
        self._queue: deque[str] = deque()
        # 流式渲染状态
        self._stream_widget: Markdown | None = None
        self._stream_buffer: str = ""
        self._stream_dirty: bool = False
        # 取消回调（app.py 设置，Esc 触发真取消）
        self._cancel_callback: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat-log"):
            yield Static("", id="chat-welcome", classes="welcome-card")
        yield HintBar()
        yield ChatInput(
            placeholder="输入消息… (/ 命令 · @ 股票 · Esc 中断)",
            id="prompt",
        )

    def on_mount(self) -> None:
        """启动焦点落在输入框；欢迎卡先渲染骨架，数据由 app 的 worker 回填。"""
        self.update_welcome(None, None, 0, 0, self._has_agent())
        prompt = self.query_one("#prompt", ChatInput)
        prompt.cursor_blink = False
        prompt.focus()

    # ------------------------------------------------------------------
    # 服务访问 / 主题
    # ------------------------------------------------------------------

    def _services(self) -> Any:
        return getattr(self.app, "services", None)

    def _theme(self) -> str:
        return str(getattr(self.app, "ui_theme", "dark"))

    def _has_agent(self) -> bool:
        svc = self._services()
        agent = getattr(svc, "agent", None) if svc is not None else None
        return bool(agent is not None and agent.has_agent())

    def _call_service(self, fn: Callable[[], Any] | None) -> Any:
        """安全调用服务数据源（worker 线程内），失败返回 None。"""
        if fn is None:
            return None
        try:
            return fn()
        except Exception as e:
            _log.debug("服务数据拉取失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        """标记是否正在处理消息（驱动 WorkingIndicator + HintBar）。"""
        self._busy = busy
        if busy:
            self._cancelled = False
            if self._working is None:
                self._working = WorkingIndicator()
                self._working.set_queued(len(self._queue))
                self.query_one("#chat-log", VerticalScroll).mount(self._working)
            self.query_one(HintBar).show_busy()
        else:
            if self._working is not None:
                self._working.stop_timer()
                self._working.remove()
                self._working = None
            self._refresh_hint_bar()

    def is_cancelled(self) -> bool:
        """检查当前对话是否被取消。"""
        return self._cancelled

    def clear_cancelled(self) -> None:
        """重置取消标记。"""
        self._cancelled = False

    def _refresh_hint_bar(self) -> None:
        """根据当前输入内容刷新 HintBar（slash/@ 候选、代码提示或默认）。"""
        hint = self.query_one(HintBar)
        if self._busy:
            hint.show_busy()
            return
        if self._slash_matches:
            hint.show_suggestions(
                [(c.name, c.description) for c in self._slash_matches],
                selected=self._slash_sel,
            )
            return
        if self._stock_matches:
            hint.show_stock_suggestions(self._stock_matches, selected=self._stock_sel)
            return
        value = self.query_one("#prompt", ChatInput).value
        if _CODE_RE.fullmatch(value):
            hint.show_code_hint(value)
            return
        hint.show_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        """输入变化时重算 slash / @ 候选并刷新 HintBar。"""
        if event.input.id != "prompt":
            return
        value = event.value
        # slash 选择态：/ 开头且还在输入命令名（无空格）
        if value.startswith("/") and " " not in value:
            self._slash_matches = match_slash_commands(value)
            self._slash_sel = 0
        else:
            self._slash_matches = []
        # @ 联想态：结尾是 @token
        self._stock_matches = []
        if not self._slash_matches:
            m = _AT_TOKEN_RE.search(value)
            if m is not None:
                candidates = self._stock_candidates()
                matches = match_stocks(candidates, m.group(1))
                if matches:
                    self._stock_token_start = m.start()
                    self._stock_matches = matches
                    self._stock_sel = 0
        self._refresh_hint_bar()

    def _stock_candidates(self) -> list[tuple[str, str]]:
        """@ 联想数据源（自选股 + 半导体库 + quote_cache）。"""
        svc = self._services()
        fn = getattr(svc, "stock_candidates", None) if svc is not None else None
        return self._call_service(fn) or []

    # ------------------------------------------------------------------
    # 候选选择（↑↓ 循环 + Tab/Enter 接受）
    # ------------------------------------------------------------------

    def in_selection(self) -> bool:
        """当前是否处于候选选择态（↑↓ 应循环候选而非翻历史）。"""
        return bool(self._slash_matches) or bool(self._stock_matches)

    def cycle_selection(self, delta: int) -> None:
        """↑↓ 在候选间循环移动选中项。"""
        if self._slash_matches:
            self._slash_sel = (self._slash_sel + delta) % len(self._slash_matches)
        elif self._stock_matches:
            self._stock_sel = (self._stock_sel + delta) % len(self._stock_matches)
        else:
            return
        self._refresh_hint_bar()
        self._update_ghost()

    def selected_completion(self) -> str | None:
        """当前选中的补全文本（Tab/Enter 接受的对象）。

        slash → "/cmd "；@ 联想 → 用选中代码替换 @token。
        """
        prompt = self.query_one("#prompt", ChatInput)
        if self._slash_matches:
            cmd = self._slash_matches[self._slash_sel]
            suffix = " " if cmd.has_args else ""
            return f"/{cmd.name}{suffix}"
        if self._stock_matches:
            code, _name = self._stock_matches[self._stock_sel]
            return prompt.value[: self._stock_token_start] + code + " "
        return None

    def action_accept_completion(self) -> None:
        """Tab 接受当前补全（slash 命令或 @ 股票代码）。"""
        completion = self.selected_completion()
        if completion is None:
            return
        prompt = self.query_one("#prompt", ChatInput)
        prompt.value = completion
        prompt.cursor_position = len(completion)

    def _update_ghost(self) -> None:
        """让输入框的灰色 ghost 补全跟随 slash 选中项（@ 无 ghost）。

        直接写 textual 8.2.8 的私有 reactive `_suggestion`（公开 API 只在
        输入变化时重新取建议）；未来 textual 改名时退化为 ghost 不跟随，
        HintBar 高亮仍是选中项的真实来源。
        """
        if not self._slash_matches:
            return
        completion = self.selected_completion()
        if completion is None:
            return
        prompt = self.query_one("#prompt", ChatInput)
        if hasattr(prompt, "_suggestion"):
            prompt._suggestion = completion

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
    # 消息处理
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """发送消息 / 执行斜杠命令 / @ 联想接受 / 6 位代码看报价。"""
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        if not text:
            return
        # @ 联想态：Enter 接受当前选中（插入代码），再次 Enter 才发送
        if self._stock_matches and _AT_TOKEN_RE.search(text):
            completion = self.selected_completion()
            if completion is not None:
                event.input.value = completion
                event.input.cursor_position = len(completion)
                return
        event.input.value = ""
        # 斜杠命令拦截
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            cmd = parts[0].lower() if parts else ""
            args = parts[1].strip() if len(parts) > 1 else ""
            self._dispatch_slash(cmd, args)
            return
        # 6 位代码 → 直接看报价卡（不进 AI 对话）
        if _CODE_RE.fullmatch(text):
            self.append_user(text)
            self._show_quote(text)
            return
        # 正常 AI 对话；busy 时排队，轮次结束自动发出
        self._history.append(text)
        self._history_idx = -1
        if self._busy:
            self.enqueue(text)
            return
        self.app.handle_chat_message(text)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # busy 排队
    # ------------------------------------------------------------------

    def enqueue(self, text: str) -> None:
        """busy 时把消息排队（工作行显示「已排队 N 条」）。"""
        self._queue.append(text)
        if self._working is not None:
            self._working.set_queued(len(self._queue))

    def drain_queue(self) -> str | None:
        """轮次结束取出下一条排队消息（app 负责发给 agent）。"""
        if not self._queue:
            return None
        return self._queue.popleft()

    def queued_count(self) -> int:
        return len(self._queue)

    # ------------------------------------------------------------------
    # 斜杠命令分发（卡片在对话流内渲染，不跳屏）
    # ------------------------------------------------------------------

    def _dispatch_slash(self, cmd: str, args: str) -> None:
        """执行斜杠命令。"""
        if cmd not in SLASH_COMMANDS:
            available = ", ".join(f"/{name}" for name in SLASH_COMMANDS)
            self.append_hint(f"未知命令 /{cmd}。可用命令: {available}")
            return

        if cmd == "help":
            self.app.action_help()  # type: ignore[attr-defined]
        elif cmd == "clear":
            self.clear_messages()
        elif cmd == "theme":
            self.app.action_cycle_theme()  # type: ignore[attr-defined]
        elif cmd == "quit":
            self.app.exit()
        elif cmd == "today":
            self._run_card_worker(self._build_today_card)
        elif cmd == "watch":
            self._run_card_worker(self._build_watch_card)
        elif cmd == "portfolio":
            self._run_card_worker(self._build_portfolio_card)
        elif cmd == "flows":
            self._cmd_flows(args)
        elif cmd == "quote":
            self._cmd_quote(args)
        elif cmd == "predictions":
            self._run_card_worker(self._build_predictions_card)
        elif cmd == "signals":
            self._run_card_worker(self._build_signals_card)
        elif cmd == "memory":
            self._run_card_worker(self._build_memory_card)
        elif cmd == "status":
            self._show_status_card()

    def _run_card_worker(self, builder: Callable[[], Static | None]) -> None:
        """在 worker 线程拉数据构卡片，回主线程挂载（失败显示友好错误）。"""

        def _work() -> None:
            try:
                card = builder()
            except Exception as e:
                _log.warning("卡片数据拉取失败: %s", e)
                self.app.call_from_thread(self.append_hint, friendly_error(e))
                return
            if card is not None:
                self.app.call_from_thread(self.mount_card, card)

        self.run_worker(_work, thread=True)

    def _hint_static(self, text: str) -> Static:
        return Static(f"[yellow]⚠[/] {escape(text)}", classes="hint-card")

    def _build_today_card(self) -> Static | None:
        svc = self._services()
        indexes = self._call_service(getattr(svc, "indexes", None)) or []
        data_svc = getattr(svc, "data", None)
        rows = data_svc.watchlist_quotes() if data_svc is not None else []
        up = sum(1 for r in rows if (r.get("change_pct") or 0) > 0)
        down = sum(1 for r in rows if (r.get("change_pct") or 0) < 0)
        signals = self._call_service(getattr(svc, "signals_recent", None)) or []
        pending = 0
        memory_db = getattr(svc, "memory_db", None)
        if memory_db and callable(memory_db.get("predictions")):
            stats = self._call_service(memory_db["predictions"])
            if stats:
                pending = int(stats.get("pending", 0) or 0)
        return cards.overview_card(
            indexes, len(rows), up, down, len(signals), pending, self._theme()
        )

    def _build_watch_card(self) -> Static | None:
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        rows = data_svc.watchlist_quotes() if data_svc is not None else []
        return cards.watch_card(rows, self._theme())

    def _build_portfolio_card(self) -> Static | None:
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        if data_svc is None:
            return self._hint_static("持仓服务未配置")
        return cards.portfolio_card(data_svc.portfolio_snapshot(), self._theme())

    def _build_predictions_card(self) -> Static | None:
        svc = self._services()
        memory_db = getattr(svc, "memory_db", None)
        if not memory_db:
            return self._hint_static("记忆系统未配置")
        stats = self._call_service(memory_db.get("predictions"))
        recent = self._call_service(memory_db.get("predictions_recent")) or []
        return cards.predictions_card(stats, recent, self._theme())

    def _build_signals_card(self) -> Static | None:
        svc = self._services()
        fn = getattr(svc, "signals_recent", None)
        if fn is None:
            return self._hint_static("信号服务未配置")
        signals = self._call_service(fn) or []
        return cards.signals_card(signals, self._theme())

    def _build_memory_card(self) -> Static | None:
        svc = self._services()
        memory_db = getattr(svc, "memory_db", None)
        if not memory_db:
            return self._hint_static("记忆系统未配置")
        return cards.memory_card(memory_db, self._theme())

    def _show_status_card(self) -> None:
        """/status：无 IO，同步组装直接挂载。"""
        svc = self._services()
        agent = getattr(svc, "agent", None)
        provider = agent.provider_name() if agent is not None else None
        model = agent.model_name() if agent is not None else None
        ai_label = f"AI🟢 {provider}" if provider else "AI⚪ 未配置"
        data_svc = getattr(svc, "data", None)
        source = data_svc.source_label() if data_svc is not None else ""
        counters = getattr(getattr(data_svc, "adapter", None), "stats_counters", None)
        from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB

        paths = {
            "market": str(MARKET_DB),
            "portfolio": str(PORTFOLIO_DB),
            "agent": str(AGENT_DB),
            "reference": str(REFERENCE_DB),
        }
        self.mount_card(cards.status_card(ai_label, model, source, counters, paths, self._theme()))

    def _cmd_quote(self, args: str) -> None:
        code = args.strip()
        if not _CODE_RE.fullmatch(code):
            self.append_hint("用法: /quote <代码>，如 /quote 600519 或 /quote AAPL")
            return
        self._show_quote(code)

    def _show_quote(self, code: str) -> None:
        """报价卡（/quote 与 6 位代码快捷入口共用）。"""

        def _build() -> Static | None:
            svc = self._services()
            data_svc = getattr(svc, "data", None)
            adapter = getattr(data_svc, "adapter", None) if data_svc is not None else None
            if adapter is None:
                return self._hint_static("行情服务未配置")
            quote = adapter.get_quote(code)
            if quote is None:
                return self._hint_static(f"未找到 {code} 的行情")
            data: dict[str, Any] = {
                "code": code,
                "name": getattr(quote, "name", code),
                "price": getattr(quote, "price", None),
                "change_pct": getattr(quote, "change_pct", None),
                "open": getattr(quote, "open", None),
                "high": getattr(quote, "high", None),
                "low": getattr(quote, "low", None),
                "prev_close": getattr(quote, "prev_close", None),
                "volume": getattr(quote, "volume", None),
                "turnover": getattr(getattr(quote, "turnover", None), "amount", None),
                "turnover_rate": getattr(quote, "turnover_rate", None),
                "volume_ratio": getattr(quote, "volume_ratio", None),
            }
            if data_svc is not None:
                flow = data_svc._fetch_flow_safe(code)
                if flow is not None:
                    data["main_flow"] = flow
            return cards.quote_card(data, self._theme())

        self._run_card_worker(_build)

    def _cmd_flows(self, args: str) -> None:
        code = args.strip()
        if code:
            if not _CODE_RE.fullmatch(code):
                self.append_hint("用法: /flows <代码>，如 /flows 688981 或 /flows AAPL")
                return

            def _build() -> Static | None:
                svc = self._services()
                flows_service = getattr(svc, "flows", None)
                if flows_service is None:
                    return self._hint_static("资金流服务未配置")
                info = flows_service.show(code, days=30)
                return cards.flows_command_card(code, info, self._theme())

            self._run_card_worker(_build)
            return

        # 无参数：自选股主力净流入榜
        def _build_watchlist_flows() -> Static | None:
            svc = self._services()
            data_svc = getattr(svc, "data", None)
            rows = data_svc.watchlist_quotes() if data_svc is not None else []
            with_flow = [r for r in rows if r.get("main_flow") is not None]
            with_flow.sort(key=lambda r: abs(float(r["main_flow"])), reverse=True)
            items = [
                {"code": r.get("code", ""), "name": r.get("name", ""), "main_net": r["main_flow"]}
                for r in with_flow[:10]
            ]
            return cards.flow_multi_card(items, self._theme())

        self._run_card_worker(_build_watchlist_flows)

    # ------------------------------------------------------------------
    # 对话流追加（用户 / 助手 / 工作流 / 工具 / 提示 / 卡片）
    # ------------------------------------------------------------------

    def append_user(self, text: str) -> None:
        """追加用户消息（❯ 前缀，dexter user-query 风格）。"""
        log = self.query_one("#chat-log", VerticalScroll)
        with contextlib.suppress(Exception):
            log.query_one("#chat-welcome").remove()
        log.mount(Static(f"[bold]❯ {escape(text)}[/]", classes="user-msg"))
        log.scroll_end(animate=False)

    def append_assistant(self, text: str) -> None:
        """追加 Agent 回复（⏺ 前缀 + Markdown，dexter answer-box 风格）。"""
        log = self.query_one("#chat-log", VerticalScroll)
        normalized = text.lstrip("\n")
        log.mount(Markdown(f"⏺ {normalized}", classes="assistant-msg"))
        log.scroll_end(animate=False)

    def append_workflow_match(self, title: str, steps: list[str]) -> None:
        """追加工作流匹配卡片。"""
        log = self.query_one("#chat-log", VerticalScroll)
        steps_str = "  ".join(f"⠹ {escape(s)}" for s in steps)
        log.mount(
            Static(
                f"[yellow]⚡ 匹配工作流：{escape(title)}[/]\n{steps_str}",
                classes="workflow-card",
            )
        )
        log.scroll_end(animate=False)

    def mount_card(self, widget: Static) -> None:
        """把富卡片挂载到对话流尾部。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(widget)
        log.scroll_end(animate=False)

    def tool_call_started(self, call_id: int, name: str, args: dict[str, Any]) -> None:
        """工具调用开始：挂载呼吸闪烁的 ToolIndicator。"""
        if self._working is not None:
            self._working.clear_retry()
        log = self.query_one("#chat-log", VerticalScroll)
        indicator = ToolIndicator(name, format_tool_args(args))
        self._tool_widgets[call_id] = indicator
        self._tool_names[call_id] = name
        log.mount(indicator)
        log.scroll_end(animate=False)

    def tool_call_finished(self, call_id: int, ok: bool, elapsed_ms: int, result: str) -> None:
        """工具调用完成/失败：更新指示器；可渲染的结果追加富卡片。"""
        indicator = self._tool_widgets.pop(call_id, None)
        name = self._tool_names.pop(call_id, "")
        if indicator is None:
            return
        log = self.query_one("#chat-log", VerticalScroll)
        if ok:
            indicator.set_complete(
                format_result_digest(result), elapsed_ms, truncated=is_truncated(result)
            )
            card = render_tool_result(name, result, self._theme())
            if card is not None:
                log.mount(card)
        else:
            indicator.set_error(result, elapsed_ms)
        log.scroll_end(animate=False)

    def finish_turn(self, elapsed_ms: int, interrupted: bool = False, tokens: int = 0) -> None:
        """一轮对话收尾：✻ 总耗时 + token（dexter performance-stats 风格）。"""
        if interrupted:
            return
        parts = [format_elapsed(elapsed_ms)]
        if tokens:
            parts.append(f"↓ {_format_tokens_compact(tokens)} tokens")
        suffix = " · ".join(parts)
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(f"[#8a8f98]✻ {suffix}[/]", classes="turn-stats"))
        log.scroll_end(animate=False)

    def append_hint(self, text: str) -> None:
        """追加提示卡片。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(f"[yellow]⚠[/] {escape(text)}", classes="hint-card"))
        log.scroll_end(animate=False)

    def append_memory_receipt(self) -> None:
        """记忆回执：后台提取完成后在对话流尾部追加淡色一行。"""
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(
            Static(
                "[#8a8f98]  ✎ 已记住本轮要点（/memory 查看）[/]",
                classes="memory-receipt",
            )
        )
        log.scroll_end(animate=False)

    def set_retry_status(self, attempt: int, max_retries: int) -> None:
        """重试状态（app 经 on_status 回调转发）：工作行显示重试进度。"""
        if self._working is not None:
            self._working.set_retry(attempt, max_retries)

    def update_welcome(
        self,
        indexes: list[dict[str, Any]] | None,
        watch_total: int | None,
        watch_up: int,
        watch_down: int,
        has_agent: bool,
    ) -> None:
        """回填欢迎卡内容（数据未到时 indexes/watch_total 传 None 渲染骨架）。"""
        try:
            welcome = self.query_one("#chat-welcome", Static)
        except Exception:
            return
        welcome.update(
            cards.welcome_text(indexes, watch_total, watch_up, watch_down, has_agent, self._theme())
        )

    # ------------------------------------------------------------------
    # 流式渲染（逐 delta 更新 Markdown，50ms 节流）
    # ------------------------------------------------------------------

    def start_streaming(self) -> None:
        """挂载流式 Markdown widget（首个 chunk 到达前调用）。"""
        if self._stream_widget is not None:
            return
        if self._working is not None:
            self._working.clear_retry()
        self._stream_buffer = ""
        self._stream_dirty = False
        widget = Markdown("⏺ …", classes="assistant-msg streaming")
        self._stream_widget = widget
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(widget)
        log.scroll_end(animate=False)

    def append_chunk(self, delta: str) -> None:
        """追加一个流式 chunk 到缓冲区，标记 dirty 等待节流刷新。"""
        self._stream_buffer += delta
        self._stream_dirty = True

    def flush_stream(self) -> None:
        """把缓冲区内容刷新到 Markdown widget（由 app.py 的 timer 节流调用）。"""
        if not self._stream_dirty or self._stream_widget is None:
            return
        self._stream_dirty = False
        text = self._stream_buffer.lstrip("\n")
        self._stream_widget.update(f"⏺ {text}")
        self.query_one("#chat-log", VerticalScroll).scroll_end(animate=False)

    def finalize_stream(self) -> str:
        """收尾流式 widget：最终刷新并返回完整文本。"""
        self.flush_stream()
        widget = self._stream_widget
        self._stream_widget = None
        text = self._stream_buffer
        self._stream_buffer = ""
        self._stream_dirty = False
        # 如果从未收到 chunk（provider 不支持流式），移除占位 widget
        if not text and widget is not None:
            widget.remove()
        return text

    def set_cancel_callback(self, callback: Callable[[], None]) -> None:
        """注册真取消回调（app.py 传入，Esc 时触发 cancel_event.set()）。"""
        self._cancel_callback = callback

    # ------------------------------------------------------------------
    # 工作流步骤进度（StepStatus 消息驱动）
    # ------------------------------------------------------------------

    def on_step_status(self, msg: StepStatus) -> None:
        """接收 StepStatus 消息并原地更新步骤进度行。"""
        mark = {"ok": "✓", "fail": "✗", "running": "⠹"}.get(msg.state, "?")
        color = {"ok": "green", "fail": "red", "running": "yellow"}.get(msg.state, "white")
        content = f"  [{color}]{mark}[/{color}] {escape(msg.detail)}"
        key = (msg.turn_id, msg.idx)
        existing = self._step_widgets.get(key)
        if existing is not None:
            existing.update(content)
            return
        log = self.query_one("#chat-log", VerticalScroll)
        widget = Static(content, classes="step-status")
        self._step_widgets[key] = widget
        log.mount(widget)
        log.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # 清屏 / 取消 / 滚动
    # ------------------------------------------------------------------

    async def _clear_messages(self) -> None:
        """原子清空对话区：等待旧 widget detach 后再挂欢迎卡。"""
        cancel = getattr(self.app, "cancel_active_turn", None)
        if callable(cancel):
            cancel()
        if self._cancel_callback is not None:
            with contextlib.suppress(Exception):
                self._cancel_callback()
        if self._working is not None:
            self._working.stop_timer()
            self._working = None
        self._tool_widgets.clear()
        self._tool_names.clear()
        self._step_widgets.clear()
        self._queue.clear()
        self._stream_widget = None
        self._stream_buffer = ""
        self._stream_dirty = False
        self._busy = False
        self._cancelled = False
        self._cancel_callback = None
        log = self.query_one("#chat-log", VerticalScroll)
        await log.query("*").remove()
        log.mount(Static("", id="chat-welcome", classes="welcome-card"))
        self.update_welcome(None, None, 0, 0, self._has_agent())
        refresh = getattr(self.app, "_refresh_market", None)
        if callable(refresh):
            refresh()

    def clear_messages(self) -> None:
        """调度原子清屏任务（slash / Ctrl+L 共用）。"""
        self.run_worker(
            self._clear_messages(), name="clear-chat", group="clear-chat", exclusive=True
        )

    def action_clear_log(self) -> None:
        """Ctrl+L 清屏。"""
        self.clear_messages()

    def action_cancel_chat(self) -> None:
        """Esc 中断当前对话。

        真取消：先触发 cancel_event（让 worker 线程在下一个检查点退出），
        再做 UI 收尾。已流出的部分保留并标注「（已中断）」。
        """
        if not self._busy:
            return
        self._cancelled = True
        # 触发真取消（cancel_event.set()）
        if self._cancel_callback is not None:
            with contextlib.suppress(Exception):
                self._cancel_callback()
        # 保留已流出部分并标注（已中断）
        widget = self._stream_widget
        text = ""
        if widget is not None:
            text = self.finalize_stream()
            if text:
                widget.update(f"⏺ {text.lstrip()}\n\n[dim]（已中断）[/]")
        if not text:
            log = self.query_one("#chat-log", VerticalScroll)
            log.mount(
                Static(
                    "[#8a8f98]⎿  （已中断）[/]",
                    classes="interrupted-line",
                )
            )
            log.scroll_end(animate=False)

    def action_scroll_page_up(self) -> None:
        """PgUp 上翻对话。"""
        self.query_one("#chat-log", VerticalScroll).scroll_page_up(animate=False)

    def action_scroll_page_down(self) -> None:
        """PgDn 下翻对话。"""
        self.query_one("#chat-log", VerticalScroll).scroll_page_down(animate=False)
