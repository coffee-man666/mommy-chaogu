"""顶部指数条（单行横排）。

上证 3200 ↑1.2% │ 深证 10234 ↑0.8% │ 创业板 2100 ↓0.3%
set_interval(30) 刷新。红涨绿跌（Rich Text 着色）。
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


class IndexStrip(Horizontal):
    """顶部指数条：上证/深证/创业板横排。

    一行高度，set_interval(30) 定时刷新。
    """

    DEFAULT_CSS = """
    IndexStrip {
        height: 1;
        background: $boost;
        padding: 0 1;
        color: $text;
    }
    IndexStrip > Static {
        width: 1fr;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._refresh_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Static("加载指数中…", id="index-text")

    def on_mount(self) -> None:
        self.set_interval(30, self._refresh)

    def on_unmount(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    async def _refresh(self) -> None:
        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        try:
            indexes = await data_service.get_indexes()
        except Exception as e:
            _log.debug("刷新指数失败: %s", e)
            return

        if not indexes:
            return

        parts: list[str] = []
        for idx in indexes:
            name = str(idx["name"])
            price = idx["price"]
            pct = idx["change_pct"]
            pct_val = float(pct)

            if pct_val > 0:
                color = COLOR_UP
                arrow = "↑"
            elif pct_val < 0:
                color = COLOR_DOWN
                arrow = "↓"
            else:
                color = "white"
                arrow = "→"

            parts.append(
                f"[bold]{name}[/] [{color}]{float(price):.2f} {arrow}{pct_val:+.2f}%[/{color}]"
            )

        text = " │ ".join(parts)
        with contextlib.suppress(Exception):
            label = self.query_one("#index-text", Static)
            label.update(text)
