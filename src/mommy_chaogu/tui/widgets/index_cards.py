"""大盘指数卡片行。

顶部水平排列的大盘指数卡片（上证/深证/创业板等）。
每个卡片：名称 + 点位 + 涨跌幅（带颜色）。
set_interval(30) 刷新。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

_log = logging.getLogger(__name__)

COLOR_UP = "red"
COLOR_DOWN = "green"


class IndexCards(Horizontal):
    """大盘指数卡片行。"""

    DEFAULT_CSS = """
    IndexCards {
        height: 3;
        border: round $panel;
        padding: 0 1;
        background: $surface;
    }
    IndexCards > .index-card {
        width: 1fr;
        height: 100%;
        padding: 0 1;
        text-align: center;
        content-align: center middle;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._refresh_task: object = None

    def compose(self) -> ComposeResult:
        # 占位卡片，数据加载后替换
        yield Static("加载指数中…", id="index-placeholder", classes="index-card")

    def on_mount(self) -> None:
        """首次加载 + 定时刷新。"""
        self._refresh_task = asyncio.get_event_loop().create_task(self._refresh())
        self.set_interval(30, self._refresh_sync)

    def _refresh_sync(self) -> None:
        """定时刷新入口。"""
        self._refresh_task = asyncio.get_event_loop().create_task(self._refresh())

    async def _refresh(self) -> None:
        """从 data_service 拉取指数并更新卡片。"""
        app = self.app
        data_service = getattr(app, "data_service", None)
        if data_service is None:
            return

        try:
            indexes = await data_service.get_indexes()
        except Exception as e:
            _log.debug("刷新指数失败: %s", e)
            return

        if not indexes:
            return

        # 清除占位 + 旧卡片
        with contextlib.suppress(Exception):
            self.query(".index-card").remove()

        for idx in indexes:
            name = str(idx["name"])
            price = idx["price"]
            pct = idx["change_pct"]

            pct_val = float(pct)
            if pct_val > 0:
                color = COLOR_UP
            elif pct_val < 0:
                color = COLOR_DOWN
            else:
                color = "white"

            text = (
                f"[bold]{name}[/]\n"
                f"[{color}]{float(price):.2f}[/{color}] "
                f"[{color}]({pct_val:+.2f}%)[/{color}]"
            )
            card = Static(text, classes="index-card", markup=True)
            self.mount(card)
