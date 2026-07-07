"""Textual TUI 主入口。

MommyTUIApp — 基于 Textual 的终端界面。
三栏 dashboard 布局，直接复用项目内部 adapter/store。
"""

from __future__ import annotations

import logging
from typing import ClassVar

from textual.app import App

from mommy_chaogu.tui.data_service import TUIDataService
from mommy_chaogu.tui.screens.dashboard import DashboardScreen

_log = logging.getLogger(__name__)


class MommyTUIApp(App):
    """Mommy Chaogu TUI 主应用。

    用法：
        mommy-tui          # 命令行启动
        python -m mommy_chaogu.tui.app
    """

    TITLE = "Mommy Chaogu TUI"
    CSS_PATH = "app.tcss"

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # 数据服务在 app 上，所有 widget 通过 self.app.data_service 访问
        self.data_service = TUIDataService()

    def on_mount(self) -> None:
        """挂载主屏。"""
        self.push_screen(DashboardScreen())


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
