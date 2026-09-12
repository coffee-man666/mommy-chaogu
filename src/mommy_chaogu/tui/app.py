"""Textual TUI 主入口。

MommyTuiApp — 投研 Coding Agent CLI：单屏对话即界面。

布局（无 ContentSwitcher、无看板模式）：
    TopBar（指数快照 + AI 状态 + 时钟）
    ChatView（对话流 + HintBar + 输入框）
    Footer
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any, ClassVar

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.reactive import reactive
from textual.widgets import Footer, Static

from mommy_chaogu.db_paths import DEFAULT_DATA_DIR
from mommy_chaogu.tui.messages import StepStatus
from mommy_chaogu.tui.screens.help import HelpScreen
from mommy_chaogu.tui.services.bootstrap import Services
from mommy_chaogu.tui.services.errors import friendly_error
from mommy_chaogu.tui.services.session_journal import SessionJournal
from mommy_chaogu.tui.views.chat import ChatView
from mommy_chaogu.tui.widgets.top_bar import TopBar

_log = logging.getLogger(__name__)


def build_tui_parser() -> argparse.ArgumentParser:
    """Build the lightweight CLI parser without starting Textual or setup."""
    from mommy_chaogu import __version__

    parser = argparse.ArgumentParser(
        prog="mommy-tui",
        description="启动 mommy-chaogu 的沉浸式终端界面。",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


class _MommyCommandProvider(Provider):
    """命令面板 Provider：slash 命令的图形入口。"""

    def _commands(self) -> list[tuple[str, Any]]:
        app: Any = self.app
        return [
            ("今日总览 /today", lambda: app.run_slash("today")),
            ("自选股 /watch", lambda: app.run_slash("watch")),
            ("持仓 /portfolio", lambda: app.run_slash("portfolio")),
            ("资金流 /flows", lambda: app.run_slash("flows")),
            ("预测跟踪 /predictions", lambda: app.run_slash("predictions")),
            ("近期信号 /signals", lambda: app.run_slash("signals")),
            ("记忆系统 /memory", lambda: app.run_slash("memory")),
            ("服务状态 /status", lambda: app.run_slash("status")),
            ("清空对话 /clear", lambda: app.run_slash("clear")),
            ("帮助", app.action_help),
            ("切换主题", app.action_cycle_theme),
            ("退出", app.action_quit_request),
        ]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for prompt, callback in self._commands():
            score = matcher.match(prompt)
            if score > 0:
                yield Hit(
                    float(score),
                    prompt,
                    callback,
                    help=prompt,
                )

    async def discover(self) -> Hits:
        for prompt, callback in self._commands():
            yield DiscoveryHit(prompt, callback, help=prompt)


class MommyTuiApp(App[None]):
    """Mommy Chaogu TUI 主应用（单屏对话）。

    用法：
        mommy-tui          # 命令行启动
        python -m mommy_chaogu.tui.app
    """

    TITLE = "Mommy Chaogu"
    CSS_PATH = "styles.tcss"

    COMMANDS: ClassVar[set[type[Provider] | Any]] = {_MommyCommandProvider}

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+p", "app.command_palette", "命令面板"),
        Binding("ctrl+c", "quit_request", "退出", priority=True),
        Binding("ctrl+q", "quit", "退出", show=False),
        Binding("ctrl+t", "cycle_theme", "主题", show=False),
        Binding("question_mark", "help", "帮助", show=False),
    ]

    services: Services
    ui_theme: reactive[str] = reactive("dark")
    _THEMES: ClassVar[list[str]] = ["dark", "light", "colorblind", "solarized", "nord", "latte"]
    # ui_theme 名 → textual 主题名（CSS token 跟随后者）
    _TEXTUAL_THEMES: ClassVar[dict[str, str]] = {
        "dark": "textual-dark",
        "light": "textual-light",
        "colorblind": "textual-dark",
        "solarized": "solarized-light",
        "nord": "nord",
        "latte": "catppuccin-latte",
    }
    _THEME_LABELS: ClassVar[dict[str, str]] = {
        "dark": "深色",
        "light": "浅色",
        "colorblind": "色盲友好",
        "solarized": "日光",
        "nord": "极夜",
        "latte": "拿铁",
    }
    _INDEX_REFRESH_S: ClassVar[float] = 60.0

    def __init__(self, services: Services | None = None) -> None:
        super().__init__()
        self._startup_error: str | None = None
        if services is not None:
            self.services = services
        else:
            try:
                self.services = Services.bootstrap()
            except Exception as e:
                _log.exception("TUI 服务初始化失败，已进入降级模式")
                self.services = Services()
                self._startup_error = friendly_error(e)
        self._turn_started: float = 0.0
        self._tool_seq: int = 0
        self._pending_tool_ids: dict[str, deque[int]] = defaultdict(deque)
        # 流式 + 取消状态（每个 turn 重置）
        self._cancel_event: threading.Event | None = None
        # usage 共享 dict：作为 usage_out 传给 agent 层，worker 线程原地累加，
        # WorkingIndicator 的 stats_provider 在主线程实时读它。
        self._stream_usage: dict[str, int] = {}
        self._stream_flush_timer: Any = None
        self._last_ctrl_c: float = 0.0
        self._turn_seq: int = 0
        self._active_turn_id: int | None = None
        self._conversation_history: list[dict[str, str]] = []
        # 会话级写操作放行（确认条按 a 后记住的工具名，Esc/清屏不重置，
        # 退出 TUI 才失效——对标 Claude Code 的 "always allow"）
        self._session_allowed_tools: set[str] = set()
        # 会话恢复门面（memory 未配置时为 None，/resume /new 优雅降级）
        agent_memory = getattr(self.services.agent, "_memory", None)
        self._journal: SessionJournal | None = (
            SessionJournal(agent_memory) if agent_memory is not None else None
        )
        # 本会话累计 token（每轮结束累加，TopBar 常驻显示）
        self._session_tokens: int = 0

    def compose(self) -> ComposeResult:
        """单屏：TopBar + ChatView + Footer。"""
        yield TopBar()
        yield ChatView()
        yield Footer()

    def on_mount(self) -> None:
        """设置主题 / AI 状态点，启动行情回填 worker + 周期刷新。"""
        self.ui_theme = os.environ.get("MOMMY_TUI_THEME", "dark")
        self._apply_theme(notify=False)
        provider = self.services.agent.provider_name()
        top = self.query_one(TopBar)
        top.ai_label = f"AI🟢 {provider}" if provider else "AI⚪ 未配置"
        self._refresh_market()
        self.set_interval(self._INDEX_REFRESH_S, self._refresh_market)
        if self._startup_error:
            self.query_one(ChatView).append_hint(
                f"部分服务初始化失败，已进入降级模式：{self._startup_error}"
            )
        if not self.services.agent.has_agent():
            self.query_one(ChatView).mount_onboarding()
        # 会话自动恢复（MOMMY_TUI_RESUME=off 关闭；/resume 仍可用）
        if self._journal is not None and (
            os.environ.get("MOMMY_TUI_RESUME", "").strip().lower() != "off"
        ):
            self.run_worker(self._recover_session_worker, name="session-recover", thread=True)

    # ------------------------------------------------------------------
    # 会话恢复（SessionJournal 驱动）
    # ------------------------------------------------------------------

    def _recover_session_worker(self) -> None:
        """worker 线程：解析上次会话（SQL 不占主线程），回主线程渲染。"""
        if self._journal is None:
            return
        try:
            rec = self._journal.recover_latest()
        except Exception as e:
            _log.warning("会话恢复失败: %s", e)
            return
        self.call_from_thread(self._apply_recovery, rec)

    def _apply_recovery(self, rec: Any) -> None:
        """主线程：重放尾窗 + 横幅 + 换绑续聊记忆视图。"""
        if rec is None or rec.session_id is None:
            return  # 冷启动：欢迎卡即终态，零仪式
        if self._active_turn_id is not None:
            return  # 极端竞态：活动轮次进行中不插入历史
        chat = self.query_one(ChatView)
        chat.replay_entries(rec.entries, more_older=rec.more_older)
        chat.show_resume_banner(rec.session_id, len(rec.entries))
        if self._journal is not None:
            self.services.agent.bind_conversation_memory(self._journal.bound_memory_for_agent())

    def action_new_session(self) -> None:
        """/new：分配新会话并换绑；旧会话保留在 /resume 列表。"""
        chat = self.query_one(ChatView)
        if self._journal is None:
            chat.append_hint("会话恢复未启用（记忆未配置），无法开新会话")
            return
        new_id = self._journal.begin_next()
        self.services.agent.bind_conversation_memory(self._journal.bound_memory_for_agent())
        chat.append_hint(f"已开新会话 {new_id}（旧会话保留在 /resume 列表）")

    def action_resume(self, args: str = "") -> None:
        """/resume：无参列历史会话；带 id 切换并重放。"""
        chat = self.query_one(ChatView)
        if self._journal is None:
            chat.append_hint("会话恢复未启用（记忆未配置）")
            return
        target = args.strip()
        if not target:
            sessions = self._journal.sessions()
            if not sessions:
                chat.append_hint("暂无可恢复的会话")
                return
            lines = ["[bold]📜 历史会话[/]"]
            for i, info in enumerate(sessions, 1):
                ts = info.last_active.strftime("%m-%d %H:%M")
                preview = escape(info.preview) or "—"
                lines.append(
                    f"  [b]{i}.[/] [cyan]{info.session_id}[/] · {info.n_messages} 条"
                    f" · {ts} · {preview}"
                )
            lines.append("[dim]/resume <会话id> 继续对话[/]")
            chat.mount_card(Static("\n".join(lines), classes="card"))
            return
        # 切换含 DOM 清屏重放，走事件循环 worker（SQLite 读为毫秒级）
        self.run_worker(self._switch_session_worker(target), name="session-switch")

    async def _switch_session_worker(self, target: str) -> None:
        """切换会话：清当前对话流（复用清屏协议）→ 重放目标会话。"""
        chat = self.query_one(ChatView)
        await chat._clear_messages()
        if self._journal is None:
            return
        try:
            rec = self._journal.switch(target)
        except Exception as e:
            _log.warning("切换会话失败: %s", e)
            chat.append_hint(friendly_error(e))
            return
        self._apply_recovery(rec)

    # ------------------------------------------------------------------
    # 全局动作
    # ------------------------------------------------------------------

    def action_help(self) -> None:
        """弹出帮助。"""
        self.push_screen(HelpScreen())

    def action_quit_request(self) -> None:
        """Ctrl+C：第一次提示「再按一次退出」，2 秒内第二次退出。"""
        now = time.monotonic()
        if now - self._last_ctrl_c < 2.0:
            self.exit()
            return
        self._last_ctrl_c = now
        self.notify("再按一次 Ctrl+C 退出", timeout=2)

    def run_slash(self, name: str, args: str = "") -> None:
        """命令面板入口：执行 slash 命令。"""
        chat = self.query_one(ChatView)
        chat._dispatch_slash(name, args)

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------

    def action_cycle_theme(self, name: str = "") -> None:
        """Ctrl+T 循环切换；`/theme <名称>` 直接选中（如 /theme nord）。"""
        if name:
            candidates = {t.lower(): t for t in self._THEMES}
            aliases = {"日光": "solarized", "极夜": "nord", "拿铁": "latte", "浅色": "light", "深色": "dark"}
            key = aliases.get(name, aliases.get(name.lower(), name.lower()))
            if key in candidates:
                self.ui_theme = candidates[key]
                self._apply_theme()
                return
        try:
            idx = self._THEMES.index(self.ui_theme)
        except ValueError:
            idx = -1
        self.ui_theme = self._THEMES[(idx + 1) % len(self._THEMES)]
        self._apply_theme()

    def _apply_theme(self, notify: bool = True) -> None:
        """应用当前主题：映射到对应 textual 主题（CSS token 跟随）。

        colorblind 保留深色底，涨跌色重映射由
        formatting.change_color() 检查 ui_theme 后处理。
        """
        theme = self.ui_theme
        self.theme = self._TEXTUAL_THEMES.get(theme, "textual-dark")
        with contextlib.suppress(Exception):
            self.query_one(TopBar).set_theme(theme)
        if not notify:
            return
        label = self._THEME_LABELS.get(theme, theme)
        self.notify(f"主题已切换：{label}", timeout=3)

    # ------------------------------------------------------------------
    # 对话入口（ChatView 委托）
    # ------------------------------------------------------------------

    def handle_chat_message(self, text: str) -> None:
        """处理用户输入的消息：路由 → 工作流 / Agent / 提示。"""
        chat = self.query_one(ChatView)
        chat.append_user(text)
        chat.set_busy(True)
        self._turn_started = time.monotonic()

        self._turn_seq += 1
        turn_id = self._turn_seq
        self._active_turn_id = turn_id

        # 每轮重置 cancel + usage 状态
        cancel_event = threading.Event()
        usage: dict[str, int] = {}
        self._cancel_event = cancel_event
        self._stream_usage = usage
        chat.set_cancel_callback(cancel_event.set)

        # 1. 尝试工作流路由
        route = self.services.agent.route(text)
        if route is not None and getattr(route, "matched", False):
            workflow = getattr(route, "workflow", None)
            if workflow is not None:
                step_names = [s.display_name for s in workflow.steps]
                chat.append_workflow_match(workflow.description, step_names)

                def _run_workflow() -> None:
                    self._do_workflow(route, text, turn_id, cancel_event)

                self.run_worker(_run_workflow, name="workflow", thread=True)
                return

        # 2. 无工作流匹配 → 走 Agent
        if self.services.agent.has_agent():

            def _run_agent() -> None:
                self._do_agent_chat(text, turn_id, cancel_event, usage)

            self.run_worker(_run_agent, name="agent-chat", thread=True)
            return

        # 3. 无 Agent → 提示配置（降级说明）
        chat.set_busy(False)
        self._active_turn_id = None
        chat.append_hint("AI 未配置：仅数据命令可用，配置见 .env（如 DEEPSEEK_API_KEY）")
        self._drain_queue()

    # ------------------------------------------------------------------
    # busy 排队（轮次结束自动发出）
    # ------------------------------------------------------------------

    def _drain_queue(self) -> None:
        """轮次结束后自动发出排队消息（一次一条，递归触发下一轮）。"""
        chat = self.query_one(ChatView)
        text = chat.drain_queue()
        if text is not None:
            self.handle_chat_message(text)

    def cancel_active_turn(self) -> None:
        """取消并作废当前轮；后续旧 worker 回调会被 turn id 丢弃。"""
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._active_turn_id = None
        self._turn_seq += 1
        self._pending_tool_ids.clear()
        if self._stream_flush_timer is not None:
            self._stream_flush_timer.stop()
            self._stream_flush_timer = None

    # ------------------------------------------------------------------
    # 工作流执行（worker 线程）
    # ------------------------------------------------------------------

    def _do_workflow(
        self, route: Any, text: str, turn_id: int, cancel_event: threading.Event
    ) -> None:
        """worker 线程内执行工作流，通过 call_from_thread 回主线程更新 UI。"""
        step_idx = 0

        def on_step_start(display_name: str) -> None:
            nonlocal step_idx
            idx = step_idx
            step_idx += 1
            self.call_from_thread(self._post_step, turn_id, idx, "running", display_name)

        def on_step_done(display_name: str, success: bool) -> None:
            idx = step_idx - 1
            state = "ok" if success else "fail"
            self.call_from_thread(self._post_step, turn_id, idx, state, display_name)

        try:
            result = self.services.agent.execute_workflow(
                route,
                text,
                on_step_start,
                on_step_done,
                is_cancelled=cancel_event.is_set,
            )
        except Exception as e:
            _log.warning("工作流执行失败: %s", e)
            self.call_from_thread(self._on_chat_error, turn_id, f"工作流出错：{friendly_error(e)}")
            return

        summary = ""
        if result is not None:
            summary = getattr(result, "summary", "") or ""
            if not summary and getattr(result, "steps", None):
                from mommy_chaogu.workflow.engine import _format_fallback

                summary = _format_fallback(getattr(result, "workflow_id", ""), result)
        self.call_from_thread(self._on_workflow_done, turn_id, summary)

    def _post_step(self, turn_id: int, idx: int, state: str, detail: str) -> None:
        """主线程：向 ChatView 发送 StepStatus 消息。"""
        if turn_id != self._active_turn_id:
            return
        chat = self.query_one(ChatView)
        chat.post_message(StepStatus(idx=idx, state=state, detail=detail, turn_id=turn_id))

    def _on_workflow_done(self, turn_id: int, summary: str) -> None:
        """主线程：工作流执行完成。"""
        if turn_id != self._active_turn_id:
            return
        chat = self.query_one(ChatView)
        if chat.is_cancelled():
            chat.clear_cancelled()
            chat.set_busy(False)
            self._active_turn_id = None
            self._drain_queue()
            return
        text = summary if summary else "工作流执行完成。"
        chat.append_assistant(text)
        chat.set_busy(False)
        self._active_turn_id = None
        chat.finish_turn(self._turn_elapsed_ms())
        self._drain_queue()

    # ------------------------------------------------------------------
    # Agent 对话（worker 线程）
    # ------------------------------------------------------------------

    def _do_agent_chat(
        self,
        text: str,
        turn_id: int,
        cancel_event: threading.Event,
        usage_out: dict[str, int],
    ) -> None:
        """worker 线程内调用 agent.chat，工具调用/结果 + 流式 chunk + 重试状态实时回传 UI。

        流式：on_chunk 回调把每个 delta 转发到 ChatView 的流式 widget。
        取消：cancel_event 在 worker 开始前创建，Esc 时 set()。
        token：self._stream_usage 作为 usage_out 共享 dict 传入，agent 层
           原地累加，主线程 WorkingIndicator 的 stats_provider 实时读取。
        重试：on_status("retry", {...}) 回调驱动工作行显示重试进度。
        """

        def on_tool_call(fn_name: str, fn_args: dict[str, Any]) -> None:
            self.call_from_thread(self._post_tool_started, turn_id, fn_name, fn_args)

        def on_tool_result(fn_name: str, ok: bool, elapsed_ms: int, result: str) -> None:
            self.call_from_thread(self._post_tool_result, turn_id, fn_name, ok, elapsed_ms, result)

        def on_confirm(fn_name: str, fn_args: dict[str, Any]) -> bool:
            """写操作确认：worker 线程内阻塞等待用户在确认条上决定。

            会话级放行的工具直接通过；决定通过 threading.Event 传回。
            取消整轮（Esc/清屏）按拒绝处理，避免 worker 悬空。
            """
            if fn_name in self._session_allowed_tools:
                return True
            decided = threading.Event()
            decision: list[str] = []

            def _record(choice: str) -> None:
                decision.append(choice)
                decided.set()

            # 挂载确认条必须在主线程；等待留在 worker 线程，UI 不被阻塞
            self.call_from_thread(self._show_confirm, fn_name, fn_args, _record)
            while not decided.is_set():
                cancel = self._cancel_event
                if cancel is not None and cancel.is_set():
                    self.call_from_thread(self._force_resolve_confirm)
                    return False
                decided.wait(0.2)
            choice = decision[0] if decision else "deny"
            if choice == "always":
                self._session_allowed_tools.add(fn_name)
                return True
            return choice == "allow"

        def on_status(status: str, info: dict[str, Any]) -> None:
            if status == "retry":
                attempt = int(info.get("attempt", 1))
                # 回调的 max 是「总尝试次数」（重试上限 + 1），显示为重试进度
                max_retries = max(1, int(info.get("max", 2)) - 1)
                self.call_from_thread(self._on_retry_status, turn_id, attempt, max_retries)

        # 流式 chunk 回调：worker 线程调用，通过 call_from_thread 转主线程
        streaming_started = threading.Event()

        def on_chunk(delta: str) -> None:
            if not streaming_started.is_set():
                streaming_started.set()
                self.call_from_thread(self._start_streaming, turn_id)

            self.call_from_thread(self._append_stream_chunk, turn_id, delta)

        # 思考流回调（推理模型才有 delta；普通轮永不触发）
        thinking_started = threading.Event()

        def on_thinking(delta: str) -> None:
            if not thinking_started.is_set():
                thinking_started.set()
                self.call_from_thread(self._start_thinking_block, turn_id)

            self.call_from_thread(self._append_thinking_delta, delta)

        chat_kwargs: dict[str, Any] = dict(
            history=list(self._conversation_history[-20:]),
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            usage_out=usage_out,
            on_status=on_status,
            on_thinking=on_thinking,
        )
        try:
            resp = self.services.agent.chat(text, on_confirm=on_confirm, **chat_kwargs)
        except TypeError as e:
            # 兼容旧 AgentBridge（测试桩 / 外部实现）：不认识任一新参数
            # （on_confirm / on_thinking）时，整体剔除后重试一次——
            # 能力协商从「全有」降到「基础」，而不是半个坏掉的组合
            if not any(k in str(e) for k in ("on_thinking", "on_confirm")):
                raise
            chat_kwargs.pop("on_confirm", None)
            chat_kwargs.pop("on_thinking", None)
            resp = self.services.agent.chat(text, **chat_kwargs)
        except Exception as e:
            _log.warning("Agent chat 失败: %s", e)
            self.call_from_thread(self._on_chat_error, turn_id, friendly_error(e))
            return

        # 收集 usage：resp.usage 与 self._stream_usage 是同一 dict，
        # 但 resp 可能为 None（AgentBridge 未配置），这里仍走 getattr 兼容。
        usage = getattr(resp, "usage", {}) if resp is not None else {}
        interrupted = getattr(resp, "interrupted", False) if resp is not None else False
        reply = ""
        if resp is not None:
            reply = getattr(resp, "text", "") or ""

        self.call_from_thread(self._on_agent_done, turn_id, text, reply, interrupted, usage)

    def _show_confirm(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        record: Callable[[str], None],
    ) -> None:
        """主线程：挂载内联确认条（决定经 record 回传 worker 线程）。"""
        self.query_one(ChatView).request_confirm(fn_name, fn_args, record)

    def _force_resolve_confirm(self) -> None:
        """主线程：取消整轮时把悬空确认条强制落定为拒绝。"""
        self.query_one(ChatView).force_resolve_confirm("deny")

    def _post_tool_started(self, turn_id: int, name: str, args: dict[str, Any]) -> None:
        """主线程：分配 call_id 并通知 ChatView 挂载 ToolIndicator。"""
        if turn_id != self._active_turn_id:
            return
        self._tool_seq += 1
        self._pending_tool_ids[name].append(self._tool_seq)
        chat = self.query_one(ChatView)
        chat.tool_call_started(self._tool_seq, name, args)

    def _post_tool_result(
        self, turn_id: int, name: str, ok: bool, elapsed_ms: int, result: str
    ) -> None:
        """主线程：按 FIFO 匹配同名 call_id，通知 ChatView 更新指示器。

        agent 循环单线程顺序执行工具，同名调用按先来先完成匹配。
        """
        if turn_id != self._active_turn_id:
            return
        queue = self._pending_tool_ids.get(name)
        call_id = queue.popleft() if queue else 0
        chat = self.query_one(ChatView)
        chat.tool_call_finished(call_id, ok, elapsed_ms, result)

    def _on_retry_status(self, turn_id: int, attempt: int, max_retries: int) -> None:
        """主线程：重试状态 → 工作行显示「⏳ 网络较慢，正在重试 (1/3)…」。"""
        if turn_id != self._active_turn_id:
            return
        chat = self.query_one(ChatView)
        chat.set_retry_status(attempt, max_retries)

    def _start_thinking_block(self, turn_id: int) -> None:
        """主线程：首个思考 delta 到达时挂载思考块。"""
        if turn_id != self._active_turn_id:
            return
        self.query_one(ChatView).start_thinking()

    def _append_thinking_delta(self, delta: str) -> None:
        """主线程：追加思考 delta。"""
        self.query_one(ChatView).append_thinking(delta)

    def _start_streaming(self, turn_id: int) -> None:
        """主线程：首个 chunk 到达时挂载流式 widget + 启动 50ms 节流 timer。"""
        if turn_id != self._active_turn_id:
            return
        chat = self.query_one(ChatView)
        chat.start_streaming()
        # 注册 usage 共享 dict 给 WorkingIndicator 做实时 token 统计。
        # self._stream_usage 已作为 usage_out 传给 agent 层，worker 线程在
        # 每轮 LLM 返回后原地累加，这里读到的就是实时值。
        if chat._working is not None:
            chat._working.set_stats_provider(lambda: self._stream_usage)
        # 50ms 节流 timer（在主线程刷新 Markdown）
        self._stream_flush_timer = self.set_timer(0.05, self._flush_stream_loop)

    def _flush_stream_loop(self) -> None:
        """主线程：节流刷新流式 Markdown，循环直到流式结束。"""
        chat = self.query_one(ChatView)
        chat.flush_stream()
        # 如果流式 widget 还在，继续调度下一次刷新
        if chat._stream_widget is not None:
            self._stream_flush_timer = self.set_timer(0.05, self._flush_stream_loop)
        else:
            self._stream_flush_timer = None

    def _append_stream_chunk(self, turn_id: int, delta: str) -> None:
        """主线程：追加一个 chunk 到 ChatView 缓冲区。"""
        if turn_id != self._active_turn_id:
            return
        chat = self.query_one(ChatView)
        chat.append_chunk(delta)

    def _turn_elapsed_ms(self) -> int:
        if self._turn_started <= 0:
            return 0
        return int((time.monotonic() - self._turn_started) * 1000)

    def _on_agent_done(
        self,
        turn_id: int,
        user_text: str,
        reply: str,
        interrupted: bool = False,
        usage: dict[str, int] | None = None,
    ) -> None:
        """主线程：Agent 回复完成。"""
        if turn_id != self._active_turn_id:
            return
        self._stream_usage = usage or {}
        tokens = int((usage or {}).get("total_tokens") or 0)
        if tokens > 0:
            self._session_tokens += tokens
            with contextlib.suppress(Exception):
                self.query_one(TopBar).set_session_usage(self._session_tokens)
        chat = self.query_one(ChatView)

        # 如果流式 widget 存在，收尾它（最终刷新 + 拿到流式文本）
        streamed_text = ""
        if chat._stream_widget is not None:
            streamed_text = chat.finalize_stream()
        # 停止 flush timer（如果还在跑）
        if self._stream_flush_timer is not None:
            self._stream_flush_timer.stop()
            self._stream_flush_timer = None

        if interrupted or chat.is_cancelled():
            # Esc 中断：action_cancel_chat 已保留已流部分并标注「（已中断）」，
            # 这里只收尾状态 + 放行排队消息。
            chat.clear_cancelled()
            chat.set_busy(False)
            self._active_turn_id = None
            self._drain_queue()
            return

        # 如果有流式文本，流式 widget 已渲染了它（不需要再 append_assistant）；
        # 否则用非流式 reply 走 append_assistant。
        text = streamed_text or reply
        if not streamed_text:
            chat.append_assistant(text if text else "（无回复）")
        chat.set_busy(False)
        self._active_turn_id = None

        self._conversation_history.extend(
            [{"role": "user", "content": user_text}, {"role": "assistant", "content": text}]
        )
        self._conversation_history = self._conversation_history[-20:]

        # token 统计：优先 total_tokens，否则 completion_tokens
        tokens = self._stream_usage.get("total_tokens") or self._stream_usage.get(
            "completion_tokens", 0
        )
        chat.finish_turn(self._turn_elapsed_ms(), tokens=tokens)

        # 记忆回执：后台提取完成后在对话流尾部追加淡色一行
        self.services.agent.watch_background(
            lambda: self.call_from_thread(self._on_memory_saved, turn_id)
        )

        self._drain_queue()

    def _on_memory_saved(self, turn_id: int) -> None:
        """主线程：后台记忆提取完成 → 对话流尾部追加「✎ 已记住…」。"""
        if turn_id != self._turn_seq:
            return
        with contextlib.suppress(Exception):
            chat = self.query_one(ChatView)
            chat.append_memory_receipt()

    def _on_chat_error(self, turn_id: int, error: str) -> None:
        """主线程：对话出错（error 已是友好文案）。"""
        if turn_id != self._active_turn_id:
            return
        chat = self.query_one(ChatView)
        chat.append_hint(error)
        chat.set_busy(False)
        self._active_turn_id = None
        self._drain_queue()

    # ------------------------------------------------------------------
    # 行情回填（TopBar 指数 + 欢迎卡红绿摘要）
    # ------------------------------------------------------------------

    def _refresh_market(self) -> None:
        """在独立 worker 线程拉取指数快照 + 自选股报价。"""
        self.run_worker(
            self._do_refresh_market,
            name="market",
            group="market",
            exclusive=True,
            thread=True,
        )

    def _do_refresh_market(self) -> None:
        """worker 线程内执行：调数据服务，回主线程应用。"""
        svc = self.services
        indexes: list[dict[str, Any]] | None = None
        if svc.indexes is not None:
            try:
                indexes = svc.indexes()
            except Exception as e:
                _log.debug("指数快照拉取失败: %s", e)
        rows: list[dict[str, Any]] = []
        try:
            rows = svc.data.watchlist_quotes()
        except Exception as e:
            _log.debug("自选股报价拉取失败: %s", e)
        self.call_from_thread(self._apply_market, indexes, rows)

    def _apply_market(
        self, indexes: list[dict[str, Any]] | None, rows: list[dict[str, Any]]
    ) -> None:
        """主线程：更新 TopBar 指数 + 欢迎卡红绿摘要。"""
        if indexes:
            first = indexes[0]
            top = self.query_one(TopBar)
            top.set_index(first.get("name", ""), first.get("price"), first.get("change_pct"))
        up = sum(1 for r in rows if (r.get("change_pct") or 0) > 0)
        down = sum(1 for r in rows if (r.get("change_pct") or 0) < 0)
        with contextlib.suppress(Exception):
            chat = self.query_one(ChatView)
            chat.update_welcome(indexes, len(rows), up, down, self.services.agent.has_agent())


def main() -> None:
    """命令行入口：mommy-tui。"""
    # Parse before setup/importing services so --help and --version are
    # guaranteed to be non-interactive CLI operations.
    build_tui_parser().parse_args()
    # 备用屏由 Textual 全权重绘：stderr 的任何裸写（如后台行情线程的
    # WARNING）都会落在终端光标处、把输入框区域涂花。TUI 模式日志改走
    # 数据目录下的文件；文件不可写时退化为静默，绝不回退 stderr。
    log_path = DEFAULT_DATA_DIR / "tui.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _handler: logging.Handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        _handler = logging.NullHandler()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[_handler],
    )
    # 启动前检查项目级 / 用户级配置，未配置则进入统一 onboarding
    from mommy_chaogu.setup import check_and_run_setup

    # 用户已经显式选择 TUI，首次配置后不再追问界面。
    check_and_run_setup(offer_interface=False)
    app = MommyTuiApp()
    app.run()


if __name__ == "__main__":
    main()
