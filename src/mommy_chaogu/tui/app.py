"""Textual TUI 主入口。

MommyTuiApp — 类 Claude Code CLI 的沉浸式体验。

单个 MainScreen 持有 ContentSwitcher，Tab 快捷键在两个视图间切换：
  - ChatView（对话）：沉浸式 AI 对话
  - DashboardView（看板）：自选股/持仓/主题/信号
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.widgets import ContentSwitcher, Input

from mommy_chaogu.tui.messages import StepStatus
from mommy_chaogu.tui.screens.help import HelpScreen
from mommy_chaogu.tui.screens.main import MainScreen
from mommy_chaogu.tui.services.bootstrap import Services
from mommy_chaogu.tui.views.chat import ChatView
from mommy_chaogu.tui.views.dashboard import DashboardView
from mommy_chaogu.tui.widgets.top_bar import TopBar

_log = logging.getLogger(__name__)


def _format_tool_args(args: dict[str, Any]) -> str:
    """Compact display of tool arguments for chat log."""
    parts: list[str] = []
    for v in args.values():
        if isinstance(v, str) and len(v) <= 30:
            parts.append(v)
        elif isinstance(v, (int, float)):
            parts.append(str(v))
        elif isinstance(v, str):
            parts.append(v[:27] + "…")
    return ", ".join(parts)


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
        Binding("ctrl+q", "quit", "退出"),
        Binding("r", "refresh", "刷新"),
        Binding("question_mark", "help", "帮助", show=False),
    ]

    services: Services

    def __init__(self, services: Services | None = None) -> None:
        super().__init__()
        self.services = services or Services.bootstrap()

    def compose(self) -> ComposeResult:
        """挂载主屏。"""
        yield MainScreen()

    def on_mount(self) -> None:
        """主屏已由 compose 挂载；此处触发首次数据拉取。"""
        self._refresh_data()

    # ------------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------------

    def action_toggle_mode(self) -> None:
        """Tab 切换：对话 ⇄ 看板。"""
        switcher = self.query_one("#main", ContentSwitcher)
        if switcher.current == "dashboard":
            switcher.current = "chat"
            with contextlib.suppress(Exception):
                self.query_one("#prompt", Input).focus()
        else:
            switcher.current = "dashboard"

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
    # 对话入口（ChatView 委托）
    # ------------------------------------------------------------------

    def handle_chat_message(self, text: str) -> None:
        """处理用户输入的消息：路由 → 工作流 / Agent / 提示。"""
        chat = self.query_one(ChatView)
        chat.append_user(text)
        chat.set_busy(True)

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
        """打开个股详情屏（P1 实现）。"""
        self.notify(f"个股详情（{code}）开发中", timeout=2)

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
            result = self.services.agent.execute_workflow(
                route, text, on_step_start, on_step_done
            )
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

    # ------------------------------------------------------------------
    # Agent 对话（worker 线程）
    # ------------------------------------------------------------------

    def _do_agent_chat(self, text: str) -> None:
        """worker 线程内调用 agent.chat，工具调用实时回传 UI。"""
        def on_tool_call(fn_name: str, fn_args: dict[str, Any]) -> None:
            args_str = _format_tool_args(fn_args)
            self.call_from_thread(self._post_tool_call, fn_name, args_str)

        try:
            resp = self.services.agent.chat(text, on_tool_call=on_tool_call)
        except Exception as e:
            _log.warning("Agent chat 失败: %s", e)
            self.call_from_thread(self._on_chat_error, f"Agent 出错：{e}")
            return

        reply = ""
        if resp is not None:
            reply = getattr(resp, "text", "") or ""
        self.call_from_thread(self._on_agent_done, reply)

    def _post_tool_call(self, name: str, args_summary: str) -> None:
        """主线程：在对话流中追加工具调用记录。"""
        chat = self.query_one(ChatView)
        chat.append_tool_call(name, args_summary)

    def _on_agent_done(self, reply: str) -> None:
        """主线程：Agent 回复完成。"""
        chat = self.query_one(ChatView)
        if chat.is_cancelled():
            chat.clear_cancelled()
            chat.set_busy(False)
            return
        text = reply if reply else "（无回复）"
        chat.append_assistant(text)
        chat.set_busy(False)

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
        svc = self.services.data
        rows = svc.watchlist_quotes()
        summary = svc.portfolio_snapshot()
        self.call_from_thread(self._apply_data, rows, summary)

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
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    app = MommyTuiApp()
    app.run()


if __name__ == "__main__":
    main()
