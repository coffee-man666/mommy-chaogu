"""实时行情表（DataTable + 定时刷新）。

列：代码/名称/现价/涨跌幅/主力。
选中行回车 → push 详情屏。
红涨绿跌（A 股习惯）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable, Static

_log = logging.getLogger(__name__)

COLOR_UP = "red"
COLOR_DOWN = "green"
COLOR_FLAT = "white"

# 匹配 Textual DOMNode.BINDINGS 的类型
_Bindings = list[Binding | tuple[str, str] | tuple[str, str, str]]


class QuoteTable(Vertical):
    """实时行情表。

    Messages:
        QuoteRowActivated: 回车选中某行时触发（用于 push 详情屏）
    """

    class QuoteRowActivated(Message):
        """行情表行被激活（回车）。"""

        def __init__(self, code: str, name: str) -> None:
            super().__init__()
            self.code = code
            self.name = name

    BINDINGS: ClassVar[_Bindings] = [
        Binding("enter", "activate_row", "详情", show=True),
    ]

    DEFAULT_CSS = """
    QuoteTable {
        height: 100%;
        border: round $panel;
    }
    QuoteTable > .title {
        padding: 0 1;
        height: 1;
        background: $boost;
        color: $text;
    }
    QuoteTable > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._codes: list[str] = []
        self._code_name: dict[str, str] = {}
        self._refresh_task: object = None

    def compose(self) -> ComposeResult:
        yield Static("📊 自选股行情", classes="title")
        yield DataTable(id="quote-grid", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#quote-grid", DataTable)
        table.add_column("代码", width=8)
        table.add_column("名称", width=10)
        table.add_column("现价", width=10)
        table.add_column("涨跌幅", width=10)
        table.add_column("主力", width=10)

        # 加载自选股代码
        self._refresh_task = asyncio.get_event_loop().create_task(self._load_and_refresh())
        self.set_interval(5, self._refresh_quotes)

    async def _load_and_refresh(self) -> None:
        """启动时加载全部自选股代码。"""
        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        try:
            codes = await data_service.get_all_watchlist_codes()
        except Exception as e:
            _log.warning("加载自选股代码失败: %s", e)
            return

        if not codes:
            return

        try:
            grouped = await data_service.get_watchlist_stocks()
        except Exception:
            grouped = {}

        self._codes = codes
        for stocks in grouped.values():
            for s in stocks:
                self._code_name.setdefault(s["code"], s["name"])
        for c in codes:
            self._code_name.setdefault(c, c)

        await self._refresh_quotes()

    async def _refresh_quotes(self) -> None:
        """从 data_service 拉取行情并更新表格。"""
        if not self._codes:
            return

        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        try:
            quotes = await data_service.get_quotes(self._codes)
        except Exception as e:
            _log.debug("刷新行情失败: %s", e)
            return

        table = self.query_one("#quote-grid", DataTable)
        table.clear()

        for q in quotes:
            code = str(q.code)
            name = self._code_name.get(code, str(q.name))

            price_str = f"{q.price:.2f}"
            pct_str = f"{q.change_pct:+.2f}%"

            pct_val = float(q.change_pct)
            if pct_val > 0:
                pct_color = COLOR_UP
                price_color = COLOR_UP
            elif pct_val < 0:
                pct_color = COLOR_DOWN
                price_color = COLOR_DOWN
            else:
                pct_color = COLOR_FLAT
                price_color = COLOR_FLAT

            # 主力净流入暂不可用
            flow_str = "—"

            table.add_row(
                code,
                name,
                (price_str, price_color),
                (pct_str, pct_color),
                flow_str,
            )

    def action_activate_row(self) -> None:
        """回车：推送详情屏。"""
        table = self.query_one("#quote-grid", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return
        with contextlib.suppress(Exception):
            row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
            code = str(row_key.value)
            name = self._code_name.get(code, code)
            self.post_message(self.QuoteRowActivated(code=code, name=name))
