"""底部状态栏（数据源/时间/延迟）。

固定一行高度：数据源名称 | 数据年龄 | 持仓盈亏速览。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

_log = logging.getLogger(__name__)


class StatusBar(Horizontal):
    """底部状态栏。

    显示：数据源 | 最后刷新时间 | 持仓盈亏速览。
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    StatusBar > .status-left {
        width: 1fr;
    }
    StatusBar > .status-center {
        width: 1fr;
        text-align: center;
    }
    StatusBar > .status-right {
        width: 1fr;
        text-align: right;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._portfolio_task: object = None

    def compose(self) -> ComposeResult:
        yield Static("数据源: —", id="status-source", classes="status-left")
        yield Static("—", id="status-time", classes="status-center")
        yield Static("持仓: —", id="status-portfolio", classes="status-right")

    def on_mount(self) -> None:
        """初始化 + 定时刷新。"""
        self._update_source()
        self.set_interval(10, self._refresh_portfolio)
        self._portfolio_task = asyncio.get_event_loop().create_task(self._refresh_portfolio_async())

    def _update_source(self) -> None:
        """更新数据源标识。"""
        with contextlib.suppress(Exception):
            source_label = self.query_one("#status-source", Static)
            source_label.update("📊 数据源: Efinance+Tencent (Fallback)")

    def update_time(self) -> None:
        """更新最后刷新时间。"""
        with contextlib.suppress(Exception):
            time_label = self.query_one("#status-time", Static)
            time_label.update(f"最后刷新: {datetime.now():%H:%M:%S}")

    def _refresh_portfolio(self) -> None:
        """刷新持仓盈亏速览。"""
        self._portfolio_task = asyncio.get_event_loop().create_task(self._refresh_portfolio_async())

    async def _refresh_portfolio_async(self) -> None:
        app = self.app
        data_service = getattr(app, "data_service", None)
        if data_service is None:
            return

        try:
            summary = await data_service.get_portfolio_summary()
        except Exception as e:
            _log.debug("刷新持仓概要失败: %s", e)
            return

        n = summary.get("n_positions", 0)
        if n == 0:
            label = "持仓: 无"
        else:
            pnl = summary.get("total_unrealized_pnl")
            if pnl is None:
                label = f"持仓: {n} 只"
            else:
                pnl_val = float(pnl)
                pct = summary.get("total_unrealized_pnl_pct")
                pct_str = f" ({float(pct):+.2f}%)" if pct else ""
                color = "red" if pnl_val >= 0 else "green"
                sign = "+" if pnl_val >= 0 else ""
                label = f"持仓: {n} 只 | [{color}]{sign}{pnl_val:,.2f}{pct_str}[/{color}]"

        with contextlib.suppress(Exception):
            port_label = self.query_one("#status-portfolio", Static)
            port_label.update(label)

        # 同时更新时间
        self.update_time()
