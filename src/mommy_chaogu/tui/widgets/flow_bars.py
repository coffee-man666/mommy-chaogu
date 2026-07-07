"""资金流迷你柱状图（Sparkline）。

在详情屏中使用，显示个股近期走势。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from decimal import Decimal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Sparkline, Static

_log = logging.getLogger(__name__)


class FlowBars(Vertical):
    """个股近期收盘价 Sparkline 走势。

    用 Textual Sparkline 绘制，数据从日 K 线 close 序列获取。
    """

    DEFAULT_CSS = """
    FlowBars {
        height: auto;
        min-height: 8;
        border: round $panel;
        padding: 0 1;
    }
    FlowBars > .title {
        height: 1;
        padding: 0;
        color: $text-muted;
    }
    FlowBars > Sparkline {
        height: 5;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._load_task: object = None

    def compose(self) -> ComposeResult:
        yield Static("📈 近期走势", classes="title")
        yield Sparkline(id="flow-spark", data=[0.0])

    def load_data(self, code: str, days: int = 20) -> None:
        """加载个股 K 线并更新 sparkline。"""
        self._load_task = asyncio.get_event_loop().create_task(self._load(code, days))

    async def _load(self, code: str, days: int) -> None:
        app = self.app
        data_service = getattr(app, "data_service", None)
        if data_service is None:
            return

        try:
            bars = await data_service.get_bars(code, limit=days)
        except Exception as e:
            _log.debug("加载走势失败: %s", e)
            return

        if not bars:
            return

        closes: list[float] = []
        for b in bars:
            with contextlib.suppress(Exception):
                closes.append(float(Decimal(str(b["close"]))))

        if not closes:
            return

        with contextlib.suppress(Exception):
            spark = self.query_one("#flow-spark", Sparkline)
            spark.data = closes

        # 更新标题
        with contextlib.suppress(Exception):
            title = self.query_one(".title", Static)
            title.update(f"📈 近 {len(closes)} 日走势")
