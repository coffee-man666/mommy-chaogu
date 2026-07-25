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
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.reactive import reactive
from textual.widgets import Footer

from mommy_chaogu.tui.messages import StepStatus
from mommy_chaogu.tui.screens.help import HelpScreen
from mommy_chaogu.tui.services.bootstrap import Services
from mommy_chaogu.tui.services.errors import friendly_error
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
    _THEMES: ClassVar[list[str]] = ["dark", "light", "colorblind"]
    _INDEX_REFRESH_S: ClassVar[float] = 60.0

    def __init__(self, services: Services | None = None) -> None:
        super().__init__()
        self.services = services or Services.bootstrap()
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

    def action_cycle_theme(self) -> None:
        """Ctrl+T：在 dark / light / colorblind 之间循环。"""
        try:
            idx = self._THEMES.index(self.ui_theme)
        except ValueError:
            idx = -1
        self.ui_theme = self._THEMES[(idx + 1) % len(self._THEMES)]
        self._apply_theme()

    def _apply_theme(self, notify: bool = True) -> None:
        """应用当前主题：dark → textual-dark；light → textual-light。

        colorblind 模式下保留深色底，实际颜色重映射由
        formatting.change_color() 检查 ui_theme 后处理。
        """
        theme = self.ui_theme
        if theme == "light":
            self.theme = "textual-light"
        else:
            self.theme = "textual-dark"
        with contextlib.suppress(Exception):
            self.query_one(TopBar).set_theme(theme)
        if not notify:
            return
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

        # 3. 无 Agent → 提示配置（降级说明）
        chat.set_busy(False)
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
            self.call_from_thread(self._on_chat_error, f"工作流出错：{friendly_error(e)}")
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
            self._drain_queue()
            return
        text = summary if summary else "工作流执行完成。"
        chat.append_assistant(text)
        chat.set_busy(False)
        chat.finish_turn(self._turn_elapsed_ms())
        self._drain_queue()

    # ------------------------------------------------------------------
    # Agent 对话（worker 线程）
    # ------------------------------------------------------------------

    def _do_agent_chat(self, text: str) -> None:
        """worker 线程内调用 agent.chat，工具调用/结果 + 流式 chunk + 重试状态实时回传 UI。

        流式：on_chunk 回调把每个 delta 转发到 ChatView 的流式 widget。
        取消：cancel_event 在 worker 开始前创建，Esc 时 set()。
        token：self._stream_usage 作为 usage_out 共享 dict 传入，agent 层
           原地累加，主线程 WorkingIndicator 的 stats_provider 实时读取。
        重试：on_status("retry", {...}) 回调驱动工作行显示重试进度。
        """

        def on_tool_call(fn_name: str, fn_args: dict[str, Any]) -> None:
            self.call_from_thread(self._post_tool_started, fn_name, fn_args)

        def on_tool_result(fn_name: str, ok: bool, elapsed_ms: int, result: str) -> None:
            self.call_from_thread(self._post_tool_result, fn_name, ok, elapsed_ms, result)

        def on_status(status: str, info: dict[str, Any]) -> None:
            if status == "retry":
                attempt = int(info.get("attempt", 1))
                # 回调的 max 是「总尝试次数」（重试上限 + 1），显示为重试进度
                max_retries = max(1, int(info.get("max", 2)) - 1)
                self.call_from_thread(self._on_retry_status, attempt, max_retries)

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
                usage_out=self._stream_usage,
                on_status=on_status,
            )
        except Exception as e:
            _log.warning("Agent chat 失败: %s", e)
            self.call_from_thread(self._on_chat_error, friendly_error(e))
            return

        # 收集 usage：resp.usage 与 self._stream_usage 是同一 dict，
        # 但 resp 可能为 None（AgentBridge 未配置），这里仍走 getattr 兼容。
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

    def _on_retry_status(self, attempt: int, max_retries: int) -> None:
        """主线程：重试状态 → 工作行显示「⏳ 网络较慢，正在重试 (1/3)…」。"""
        chat = self.query_one(ChatView)
        chat.set_retry_status(attempt, max_retries)

    def _start_streaming(self) -> None:
        """主线程：首个 chunk 到达时挂载流式 widget + 启动 50ms 节流 timer。"""
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

        if interrupted or chat.is_cancelled():
            # Esc 中断：action_cancel_chat 已保留已流部分并标注「（已中断）」，
            # 这里只收尾状态 + 放行排队消息。
            chat.clear_cancelled()
            chat.set_busy(False)
            self._drain_queue()
            return

        # 如果有流式文本，流式 widget 已渲染了它（不需要再 append_assistant）；
        # 否则用非流式 reply 走 append_assistant。
        text = streamed_text or reply
        if not streamed_text:
            chat.append_assistant(text if text else "（无回复）")
        chat.set_busy(False)

        # token 统计：优先 total_tokens，否则 completion_tokens
        tokens = self._stream_usage.get("total_tokens") or self._stream_usage.get(
            "completion_tokens", 0
        )
        chat.finish_turn(self._turn_elapsed_ms(), tokens=tokens)

        # 记忆回执：后台提取完成后在对话流尾部追加淡色一行
        self.services.agent.watch_background(lambda: self.call_from_thread(self._on_memory_saved))

        self._drain_queue()

    def _on_memory_saved(self) -> None:
        """主线程：后台记忆提取完成 → 对话流尾部追加「✎ 已记住…」。"""
        with contextlib.suppress(Exception):
            chat = self.query_one(ChatView)
            chat.append_memory_receipt()

    def _on_chat_error(self, error: str) -> None:
        """主线程：对话出错（error 已是友好文案）。"""
        chat = self.query_one(ChatView)
        chat.append_hint(error)
        chat.set_busy(False)
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
