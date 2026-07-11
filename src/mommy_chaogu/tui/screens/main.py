"""MainScreen — 常驻主屏，持有双视图 ContentSwitcher（§3.2）。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, Footer

from mommy_chaogu.tui.views.chat import ChatView
from mommy_chaogu.tui.views.dashboard import DashboardView
from mommy_chaogu.tui.widgets.top_bar import TopBar


class MainScreen(Vertical):
    """主屏：TopBar + ContentSwitcher + Footer。"""

    DEFAULT_CSS = """
    MainScreen {
        layers: base;
    }
    """

    def compose(self) -> ComposeResult:
        yield TopBar()
        with ContentSwitcher(initial="dashboard", id="main"):
            yield ChatView(id="chat")
            yield DashboardView(id="dashboard")
        yield Footer()
