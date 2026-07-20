"""Textual TUI 主入口。

MommyTuiApp — 类 Claude Code CLI 的沉浸式体验。

单个 MainScreen 持有 ContentSwitcher，Tab 快捷键在两个视图间切换：
  - ChatView（对话）：沉浸式 AI 对话
  - DashboardView（看板）：自选股/持仓/主题/信号
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.reactive import reactive
from textual.widgets import ContentSwitcher, Input

from mommy_chaogu.tui.messages import StepStatus
from mommy_chaogu.tui.screens.help import HelpScreen
from mommy_chaogu.tui.screens.main import MainScreen
from mommy_chaogu.tui.services.bootstrap import Services
from mommy_chaogu.tui.views.chat import ChatView
from mommy_chaogu.tui.views.dashboard import DashboardView
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


def _switch_mode(app: Any, mode: str) -> None:
    """切换 ContentSwitcher 到 chat / dashboard。"""
    switcher = app.query_one("#main", ContentSwitcher)
    switcher.current = mode


def _switch_tab(app: Any, tab_id: str) -> None:
    """切换看板到指定 tab。"""
    _switch_mode(app, "dashboard")
    from textual.widgets import TabbedContent

    dashboard = app.query_one(DashboardView)
    dashboard.query_one("#dashboard-tabs", TabbedContent).active = tab_id


class _MommyCommandProvider(Provider):
    """命令面板 Provider：refresh / 切模式 / 切 tab / 帮助。"""

    def _commands(self) -> list[tuple[str, Any]]:
        app: Any = self.app
        return [
            ("刷新数据", app.action_refresh),
            ("切换到 AI 对话", lambda: _switch_mode(app, "chat")),
            ("切换到数据看板", lambda: _switch_mode(app, "dashboard")),
            ("看板 · 自选股", lambda: _switch_tab(app, "watch")),
            ("看板 · 持仓", lambda: _switch_tab(app, "hold")),
            ("看板 · 主题", lambda: _switch_tab(app, "theme")),
            ("看板 · 信号", lambda: _switch_tab(app, "signal")),
            ("帮助", app.action_help),
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
    """Mommy Chaogu TUI 主应用。

    用法：
        mommy-tui          # 命令行启动
        python -m mommy_chaogu.tui.app
    """

    TITLE = "Mommy Chaogu"
    CSS_PATH = "styles.tcss"

    COMMANDS: ClassVar[set[type[Provider] | Any]] = {_MommyCommandProvider}

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "toggle_mode", "切换模式", priority=True),
        Binding("ctrl+p", "app.command_palette", "命令面板"),
        Binding("ctrl+t", "cycle_theme", "主题", show=False),
        Binding("ctrl+q", "quit", "退出"),
        Binding("r", "refresh", "刷新"),
        Binding("question_mark", "help", "帮助", show=False),
    ]

    services: Services
    ui_theme: reactive[str] = reactive("dark")
    _THEMES: ClassVar[list[str]] = ["dark", "light", "colorblind"]

    def __init__(self, services: Services | None = None) -> None:
        super().__init__()
        self.services = services or Services.bootstrap()
        self._turn_started: float = 0.0
        self._tool_seq: int = 0
        self._pending_tool_ids: dict[str, deque[int]] = defaultdict(deque)
        # 流式 + 取消状态（每个 turn 重置）
        self._cancel_event: threading.Event | None = None
        self._stream_usage: dict[str, int] = {}
        self._stream_flush_timer: Any = None

    def compose(self) -> ComposeResult:
        """挂载主屏。"""
        yield MainScreen()

    def on_mount(self) -> None:
        """主屏已由 compose 挂载；此处触发首次数据拉取。"""
        self.ui_theme = os.environ.get("MOMMY_TUI_THEME", "dark")
        self._apply_theme()
        self._refresh_data()

    # ------------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------------

    def action_toggle_mode(self) -> None:
        """Tab 切换：对话 ⇄ 看板。

        在对话模式中如果输入框有斜杠补全建议，优先接受补全而非切换。
        """
        switcher = self.query_one("#main", ContentSwitcher)
        if switcher.current == "chat":
            if self._try_accept_slash_suggestion():
                return
            switcher.current = "dashboard"
        else:
            switcher.current = "chat"
            with contextlib.suppress(Exception):
                self.query_one("#prompt", Input).focus()

    def _try_accept_slash_suggestion(self) -> bool:
        """如果对话输入框处于 slash 选择态，Tab 接受当前选中的候选。"""
        try:
            chat = self.query_one(ChatView)
            prompt = chat.query_one("#prompt", Input)
        except Exception:
            return False
        completion = chat.selected_slash_completion()
        if completion is None or completion == prompt.value:
            return False
        prompt.value = completion
        prompt.cursor_position = len(completion)
        return True

    # ------------------------------------------------------------------
    # 全局动作
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        """刷新当前视图数据。"""
        self._refresh_data()

    def action_help(self) -> None:
        """弹出帮助。"""
        self.push_screen(HelpScreen())

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------

    def action_cycle_theme(self) -> None:
        """Ctrl+T：在 dark / light / colorblind 之间循环。"""
        try:
            idx = self._THEMES.index(self.ui_theme)
        except ValueError:
            idx = -1
        self.ui_theme = self._THEMES[(idx + 1) % len(self._THEMES)]
        self._apply_theme()
        with contextlib.suppress(Exception):
            from mommy_chaogu.tui.screens.stock_detail import StockDetailScreen

            screen = self.screen
            if isinstance(screen, StockDetailScreen):
                screen.refresh_theme()

    def _apply_theme(self) -> None:
        """应用当前主题：dark → textual-dark；light → textual-light。

        colorblind 模式下保留深色底，实际颜色重映射由
        formatting.change_color() 检查 ui_theme 后处理。
        """
        theme = self.ui_theme
        if theme == "light":
            self.theme = "textual-light"
        else:
            self.theme = "textual-dark"
        labels = {"dark": "深色", "light": "浅色", "colorblind": "色盲友好"}
        label = labels.get(theme, theme)
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

        # 每轮重置 cancel + usage 状态
        self._cancel_event = threading.Event()
        self._stream_usage = {}
        chat.set_cancel_callback(self._cancel_event.set)

        # 1. 尝试工作流路由
        route = self.services.agent.route(text)
        if route is not None and getattr(route, "matched", False):
            workflow = getattr(route, "workflow", None)
            if workflow is not None:
                step_names = [s.display_name for s in workflow.steps]
                chat.append_workflow_match(workflow.description, step_names)

                def _run_workflow() -> None:
                    self._do_workflow(route, text)

                self.run_worker(_run_workflow, name="workflow", thread=True)
                return

        # 2. 无工作流匹配 → 走 Agent
        if self.services.agent.has_agent():

            def _run_agent() -> None:
                self._do_agent_chat(text)

            self.run_worker(_run_agent, name="agent-chat", thread=True)
            return

        # 3. 无 Agent → 提示配置
        chat.set_busy(False)
        chat.append_hint(
            "未配置 AI agent。请在 .env 中设置 API key"
            "（如 DEEPSEEK_API_KEY），或运行 `mommy --setup` 进行配置。"
        )

    def open_stock_detail(self, code: str) -> None:
        """打开个股详情屏。"""
        from mommy_chaogu.tui.screens.stock_detail import StockDetailScreen

        self.push_screen(StockDetailScreen(code=code))

    # ------------------------------------------------------------------
    # 工作流执行（worker 线程）
    # ------------------------------------------------------------------

    def _do_workflow(self, route: Any, text: str) -> None:
        """worker 线程内执行工作流，通过 call_from_thread 回主线程更新 UI。"""
        step_idx = 0

        def on_step_start(display_name: str) -> None:
            nonlocal step_idx
            idx = step_idx
            step_idx += 1
            self.call_from_thread(self._post_step, idx, "running", display_name)

        def on_step_done(display_name: str, success: bool) -> None:
            idx = step_idx - 1
            state = "ok" if success else "fail"
            self.call_from_thread(self._post_step, idx, state, display_name)

        try:
            result = self.services.agent.execute_workflow(route, text, on_step_start, on_step_done)
        except Exception as e:
            _log.warning("工作流执行失败: %s", e)
            self.call_from_thread(self._on_chat_error, f"工作流出错：{e}")
            return

        summary = ""
        if result is not None:
            summary = getattr(result, "summary", "") or ""
        self.call_from_thread(self._on_workflow_done, summary)

    def _post_step(self, idx: int, state: str, detail: str) -> None:
        """主线程：向 ChatView 发送 StepStatus 消息。"""
        chat = self.query_one(ChatView)
        chat.post_message(StepStatus(idx=idx, state=state, detail=detail))

    def _on_workflow_done(self, summary: str) -> None:
        """主线程：工作流执行完成。"""
        chat = self.query_one(ChatView)
        if chat.is_cancelled():
            chat.clear_cancelled()
            chat.set_busy(False)
            return
        text = summary if summary else "工作流执行完成。"
        chat.append_assistant(text)
        chat.set_busy(False)
        chat.finish_turn(self._turn_elapsed_ms())

    # ------------------------------------------------------------------
    # Agent 对话（worker 线程）
    # ------------------------------------------------------------------

    def _do_agent_chat(self, text: str) -> None:
        """worker 线程内调用 agent.chat，工具调用/结果 + 流式 chunk 实时回传 UI。

        #4 流式：on_chunk 回调把每个 delta 转发到 ChatView 的流式 widget。
        #5 取消：cancel_event 在 worker 开始前创建，Esc 时 set()。
        #6 token：usage 由 agent 层累加，worker 结束后传给 finish_turn。
        """

        def on_tool_call(fn_name: str, fn_args: dict[str, Any]) -> None:
            self.call_from_thread(self._post_tool_started, fn_name, fn_args)

        def on_tool_result(fn_name: str, ok: bool, elapsed_ms: int, result: str) -> None:
            self.call_from_thread(self._post_tool_result, fn_name, ok, elapsed_ms, result)

        # 流式 chunk 回调：worker 线程调用，通过 call_from_thread 转主线程
        streaming_started = threading.Event()

        def on_chunk(delta: str) -> None:
            if not streaming_started.is_set():
                streaming_started.set()
                self.call_from_thread(self._start_streaming)

            self.call_from_thread(self._append_stream_chunk, delta)

        try:
            resp = self.services.agent.chat(
                text,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                on_chunk=on_chunk,
                cancel_event=self._cancel_event,
            )
        except Exception as e:
            _log.warning("Agent chat 失败: %s", e)
            self.call_from_thread(self._on_chat_error, f"Agent 出错：{e}")
            return

        # 收集 usage（#6）
        usage = getattr(resp, "usage", {}) if resp is not None else {}
        interrupted = getattr(resp, "interrupted", False) if resp is not None else False
        reply = ""
        if resp is not None:
            reply = getattr(resp, "text", "") or ""

        self.call_from_thread(self._on_agent_done, reply, interrupted, usage)

    def _post_tool_started(self, name: str, args: dict[str, Any]) -> None:
        """主线程：分配 call_id 并通知 ChatView 挂载 ToolIndicator。"""
        self._tool_seq += 1
        self._pending_tool_ids[name].append(self._tool_seq)
        chat = self.query_one(ChatView)
        chat.tool_call_started(self._tool_seq, name, args)

    def _post_tool_result(self, name: str, ok: bool, elapsed_ms: int, result: str) -> None:
        """主线程：按 FIFO 匹配同名 call_id，通知 ChatView 更新指示器。

        agent 循环单线程顺序执行工具，同名调用按先来先完成匹配。
        """
        queue = self._pending_tool_ids.get(name)
        call_id = queue.popleft() if queue else 0
        chat = self.query_one(ChatView)
        chat.tool_call_finished(call_id, ok, elapsed_ms, result)

    def _start_streaming(self) -> None:
        """主线程：首个 chunk 到达时挂载流式 widget + 启动 50ms 节流 timer。"""
        chat = self.query_one(ChatView)
        chat.start_streaming()
        # 注册 usage 共享 dict 给 WorkingIndicator 做 token 统计
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

    def _append_stream_chunk(self, delta: str) -> None:
        """主线程：追加一个 chunk 到 ChatView 缓冲区。"""
        chat = self.query_one(ChatView)
        chat.append_chunk(delta)

    def _turn_elapsed_ms(self) -> int:
        if self._turn_started <= 0:
            return 0
        return int((time.monotonic() - self._turn_started) * 1000)

    def _on_agent_done(
        self, reply: str, interrupted: bool = False, usage: dict[str, int] | None = None
    ) -> None:
        """主线程：Agent 回复完成。"""
        self._stream_usage = usage or {}
        chat = self.query_one(ChatView)

        # 如果流式 widget 存在，收尾它（最终刷新 + 拿到流式文本）
        streamed_text = ""
        if chat._stream_widget is not None:
            streamed_text = chat.finalize_stream()
        # 停止 flush timer（如果还在跑）
        if self._stream_flush_timer is not None:
            self._stream_flush_timer.stop()
            self._stream_flush_timer = None

        if interrupted:
            # Esc 真取消：action_cancel_chat 已显示"已中断"，这里只收尾 busy
            chat.clear_cancelled()
            chat.set_busy(False)
            return

        if chat.is_cancelled():
            # UI 取消（旧路径兼容）
            chat.clear_cancelled()
            chat.set_busy(False)
            return

        # 如果有流式文本，流式 widget 已渲染了它（不需要再 append_assistant）；
        # 否则用非流式 reply 走 append_assistant。
        text = streamed_text or reply
        if not streamed_text:
            chat.append_assistant(text if text else "（无回复）")
        chat.set_busy(False)

        # token 统计（#6）：优先 total_tokens，否则 completion_tokens
        tokens = self._stream_usage.get("total_tokens") or self._stream_usage.get(
            "completion_tokens", 0
        )
        chat.finish_turn(self._turn_elapsed_ms(), tokens=tokens)

    def _on_chat_error(self, error: str) -> None:
        """主线程：对话出错。"""
        chat = self.query_one(ChatView)
        chat.append_hint(error)
        chat.set_busy(False)

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------

    def _refresh_data(self) -> None:
        """在独立 worker 线程拉取行情 + 持仓。"""
        self.run_worker(
            self._do_refresh,
            name="quotes",
            group="quotes",
            exclusive=True,
            thread=True,
        )

    def _do_refresh(self) -> None:
        """worker 线程内执行：调数据服务，回主线程应用。"""
        try:
            svc = self.services.data
            rows = svc.watchlist_quotes()
            summary = svc.portfolio_snapshot()
        except Exception as e:
            _log.warning("数据刷新失败: %s", e)
            self.call_from_thread(self._on_refresh_error, f"数据刷新失败: {e}")
            return
        self.call_from_thread(self._apply_data, rows, summary)

    def _on_refresh_error(self, error: str) -> None:
        """主线程：数据刷新出错。"""
        with contextlib.suppress(Exception):
            self.notify(error, severity="error", timeout=5)

    def _apply_data(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        """主线程：更新看板 + 顶栏。"""
        with contextlib.suppress(Exception):
            dashboard = self.query_one(DashboardView)
            dashboard.update_watchlist(rows)
            dashboard.update_portfolio(summary)

        source = self.services.data.source_label()
        top = self.query_one(TopBar)
        top.source_label = source or "无数据"
        top.connection_level = "live" if rows else "degraded"


def main() -> None:
    """命令行入口：mommy-tui。"""
    # Parse before setup/importing services so --help and --version are
    # guaranteed to be non-interactive CLI operations.
    build_tui_parser().parse_args()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # 启动前检查 .env 配置，未配置则引导用户完成向导
    from mommy_chaogu.setup import check_and_run_setup

    check_and_run_setup()
    app = MommyTuiApp()
    app.run()


if __name__ == "__main__":
    main()
