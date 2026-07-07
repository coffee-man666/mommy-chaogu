"""主屏：三栏 dashboard 布局。

顶部：大盘指数卡片行。
中部：三栏水平布局（自选股树 | 行情表 | AI 对话面板）。
底部：状态栏。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen

from mommy_chaogu.tui.widgets.chat_panel import ChatPanel
from mommy_chaogu.tui.widgets.index_cards import IndexCards
from mommy_chaogu.tui.widgets.quote_table import QuoteTable
from mommy_chaogu.tui.widgets.status_bar import StatusBar
from mommy_chaogu.tui.widgets.watchlist_tree import WatchlistTree

_log = logging.getLogger(__name__)


class DashboardScreen(Screen):
    """主屏 dashboard。

    布局：
        ┌─────────────────────────────────┐
        │         IndexCards（顶部）        │
        ├──────────┬──────────┬───────────┤
        │ Watchlist │  Quote   │   Chat    │
        │   Tree    │  Table   │   Panel   │
        ├──────────┴──────────┴───────────┤
        │         StatusBar（底部）         │
        └─────────────────────────────────┘
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "退出", show=True),
        Binding("r", "refresh", "刷新", show=True),
        Binding("escape", "focus_default", "取消选择", show=False),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #main-content {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._load_task: object = None
        self._refresh_task: object = None

    def compose(self) -> ComposeResult:
        yield IndexCards(id="header")
        with Horizontal(id="main-content"):
            yield WatchlistTree(id="watchlist-pane")
            yield QuoteTable(id="quote-pane")
            yield ChatPanel(id="chat-pane")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        """挂载后加载初始数据。"""
        # 默认加载全部自选股行情
        self._load_task = asyncio.get_event_loop().create_task(self._load_initial_quotes())

    async def _load_initial_quotes(self) -> None:
        """启动时加载全部自选股代码到行情表。"""
        app = self.app
        data_service = getattr(app, "data_service", None)
        if data_service is None:
            return

        try:
            codes_raw = await data_service.get_all_watchlist_codes()
        except Exception as e:
            _log.warning("加载初始自选股失败: %s", e)
            return

        if not codes_raw:
            return

        # 补名称
        stocks = [{"code": c, "name": c} for c in codes_raw]
        with contextlib.suppress(Exception):
            quote_table = self.query_one("#quote-pane", QuoteTable)
            quote_table.set_codes(stocks)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def on_watchlist_tree_stock_selected(self, event: WatchlistTree.StockSelected) -> None:
        """自选股树选中 → 切换行情表到该股。"""
        with contextlib.suppress(Exception):
            quote_table = self.query_one("#quote-pane", QuoteTable)
            quote_table.set_codes([{"code": event.code, "name": event.name}])

    def on_quote_table_quote_row_activated(self, event: QuoteTable.QuoteRowActivated) -> None:
        """行情表回车 → push 详情屏。"""
        from mommy_chaogu.tui.screens.detail import DetailScreen

        self.app.push_screen(DetailScreen(code=event.code, name=event.name))

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        """刷新所有面板。"""
        with contextlib.suppress(Exception):
            self.query_one("#watchlist-pane", WatchlistTree).load_data()
        self._refresh_task = asyncio.get_event_loop().create_task(self._load_initial_quotes())

    def action_focus_default(self) -> None:
        """ESC 回到行情表焦点。"""
        with contextlib.suppress(Exception):
            self.query_one("#quote-pane", QuoteTable).focus()
