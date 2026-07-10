"""Textual TUI 主入口。

MommyTUIApp — 类 Claude Code CLI 的沉浸式体验。

两个 Screen 模式，Tab 快捷键切换：
  - ChatScreen（默认）：沉浸式 AI 对话
  - DashboardScreen：数据看板（自选股/持仓/主题/信号）
"""

from __future__ import annotations

import logging

from textual.app import App

from mommy_chaogu.tui.data_service import TUIDataService
from mommy_chaogu.tui.screens.chat import ChatScreen
from mommy_chaogu.tui.screens.dashboard import DashboardScreen

_log = logging.getLogger(__name__)


class MommyTUIApp(App[None]):
    """Mommy Chaogu TUI 主应用。

    用法：
        mommy-tui          # 命令行启动
        python -m mommy_chaogu.tui.app
    """

    TITLE = "Mommy Chaogu"
    CSS_PATH = "app.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.data_service = TUIDataService()
        self._mode = "chat"

    def on_mount(self) -> None:
        """挂载默认主屏（沉浸式对话）。"""
        self.push_screen(ChatScreen())

    def action_cycle_screen(self) -> None:
        """Tab 切换模式：对话 ↔ 看板。"""
        if self._mode == "chat":
            self._mode = "dashboard"
            self.pop_screen()
            self.push_screen(DashboardScreen())
        else:
            self._mode = "chat"
            self.pop_screen()
            self.push_screen(ChatScreen())


def main() -> None:
    """命令行入口：mommy-tui。"""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    app = MommyTUIApp()
    app.run()


if __name__ == "__main__":
    main()
