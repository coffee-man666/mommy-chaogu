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
from textual.widgets import ContentSwitcher, Input

from mommy_chaogu.tui.screens.help import HelpScreen
from mommy_chaogu.tui.screens.main import MainScreen
from mommy_chaogu.tui.services.bootstrap import Services
from mommy_chaogu.tui.views.chat import ChatView
from mommy_chaogu.tui.views.dashboard import DashboardView
from mommy_chaogu.tui.widgets.top_bar import TopBar

_log = logging.getLogger(__name__)


class MommyTuiApp(App[None]):
    """Mommy Chaogu TUI 主应用。

    用法：
        mommy-tui          # 命令行启动
        python -m mommy_chaogu.tui.app
    """

    TITLE = "Mommy Chaogu"
    CSS_PATH = "styles.tcss"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "toggle_mode", "切换模式", priority=True),
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
        """处理用户输入的消息。"""
        chat = self.query_one(ChatView)
        chat.append_user(text)
        # stub：agent 接入后替换为流式调用
        chat.append_assistant("（stub）Agent 接入中…")

    def open_stock_detail(self, code: str) -> None:
        """打开个股详情屏（P1 实现）。"""
        self.notify(f"个股详情（{code}）开发中", timeout=2)

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
