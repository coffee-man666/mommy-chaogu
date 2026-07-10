"""个股详情屏（push screen）。

包含：
- 报价信息卡（现价/涨跌/量额/换手/PE）
- 近 20 日 Sparkline 走势
- K 线数据表（最近 10 天 OHLCV）
- ESC 返回
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Sparkline, Static

_log = logging.getLogger(__name__)

COLOR_UP = "red"
COLOR_DOWN = "green"

# 匹配 Textual DOMNode.BINDINGS 的类型
_Bindings = list[Binding | tuple[str, str] | tuple[str, str, str]]


class DetailScreen(Screen[object]):
    """个股详情屏。

    通过 push_screen 进入，ESC 返回。
    """

    BINDINGS: ClassVar[_Bindings] = [
        Binding("escape,q", "pop_screen", "返回", show=True),
    ]

    DEFAULT_CSS = """
    DetailScreen {
        layout: vertical;
        padding: 0 1;
    }
    DetailScreen > .detail-title {
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    DetailScreen > .detail-quote {
        height: auto;
        min-height: 4;
        padding: 0 1;
        border: round $panel;
    }
    DetailScreen > .detail-body {
        height: 1fr;
    }
    DetailScreen > .detail-body > Vertical {
        width: 1fr;
    }
    DetailScreen > .detail-kline {
        height: 1fr;
        border: round $panel;
        padding: 0 1;
    }
    DetailScreen > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, code: str, name: str = "") -> None:
        super().__init__()
        self.code = code
        self.stock_name = name

    def compose(self) -> ComposeResult:
        yield Static(f"🔍 {self.code} {self.stock_name}", classes="detail-title")

        with Horizontal(classes="detail-body"):
            with Vertical():
                yield Static("加载中…", id="detail-quote-info", classes="detail-quote")
                yield Static("📈 近 20 日走势", id="detail-spark-title")
                yield Sparkline(id="detail-spark", data=[0.0])
            with Vertical(classes="detail-kline"):
                yield Static("📊 近 10 日 K 线", classes="detail-title")
                yield DataTable(id="detail-kline-table")

    def on_mount(self) -> None:
        table = self.query_one("#detail-kline-table", DataTable)
        table.add_column("日期", width=12)
        table.add_column("开", width=10)
        table.add_column("高", width=10)
        table.add_column("低", width=10)
        table.add_column("收", width=10)
        table.add_column("量", width=14)
        table.add_column("涨跌", width=10)

        asyncio.get_event_loop().create_task(self._load_detail())

    async def _load_detail(self) -> None:
        """加载详情数据：报价 + 走势 + K 线。"""
        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        # 加载报价
        try:
            quotes = await data_service.get_quotes([self.code])
            if quotes:
                self._render_quote(quotes[0])
            else:
                with contextlib.suppress(Exception):
                    info = self.query_one("#detail-quote-info", Static)
                    info.update(f"[yellow]未获取到 {self.code} 的行情数据[/]")
        except Exception as e:
            _log.warning("加载报价失败: %s", e)

        # 加载走势（Sparkline）+ K 线表
        try:
            bars = await data_service.get_bars(self.code, limit=20)
        except Exception as e:
            _log.warning("加载 K 线失败: %s", e)
            return

        if not bars:
            return

        # Sparkline
        closes: list[float] = []
        for b in bars:
            with contextlib.suppress(Exception):
                closes.append(float(b["close"]))

        if closes:
            with contextlib.suppress(Exception):
                spark = self.query_one("#detail-spark", Sparkline)
                spark.data = closes
                title = self.query_one("#detail-spark-title", Static)
                title.update(f"📈 近 {len(closes)} 日走势")

        # K 线表（最近 10 天）
        self._render_klines(bars[-10:])

    def _render_quote(self, quote: object) -> None:
        """渲染报价信息卡。"""
        try:
            price = quote.price  # type: ignore[attr-defined]
            change = quote.change  # type: ignore[attr-defined]
            change_pct = quote.change_pct  # type: ignore[attr-defined]
            volume = quote.volume  # type: ignore[attr-defined]
            turnover = quote.turnover.amount  # type: ignore[attr-defined]
            turnover_rate = getattr(quote, "turnover_rate", None)
            pe = getattr(quote, "pe_dynamic", None)
            prev_close = quote.prev_close  # type: ignore[attr-defined]

            pct_val = float(change_pct)
            color = COLOR_UP if pct_val > 0 else (COLOR_DOWN if pct_val < 0 else "white")

            tr_str = f"{float(turnover_rate):.2f}%" if turnover_rate else "—"
            pe_str = f"{float(pe):.1f}" if pe else "—"

            vol_wan = float(volume) / 10000
            turnover_yi = float(turnover) / 1e8

            text = (
                f"[bold]现价[/]: [{color}]{float(price):.2f}[/{color}]  "
                f"[bold]涨跌[/]: [{color}]{float(change):+.2f} "
                f"({pct_val:+.2f}%)[/{color}]  "
                f"[bold]昨收[/]: {float(prev_close):.2f}\n"
                f"[bold]成交量[/]: {vol_wan:,.1f}万手  "
                f"[bold]成交额[/]: {turnover_yi:,.2f}亿  "
                f"[bold]换手[/]: {tr_str}  "
                f"[bold]PE[/]: {pe_str}"
            )
            info = self.query_one("#detail-quote-info", Static)
            info.update(text)
        except Exception as e:
            _log.debug("渲染报价失败: %s", e)

    def _render_klines(self, bars: list[dict[str, Any]]) -> None:
        """渲染 K 线表。"""
        try:
            table = self.query_one("#detail-kline-table", DataTable)
        except Exception:
            return

        table.clear()
        for b in reversed(bars):  # 最新在上
            date = str(b.get("date", ""))
            close = b.get("close", 0)
            change_pct = b.get("change_pct")

            pct_val = float(change_pct) if change_pct else 0.0
            color = COLOR_UP if pct_val > 0 else (COLOR_DOWN if pct_val < 0 else "white")
            pct_str = f"[{color}]{pct_val:+.2f}%[/{color}]" if change_pct else "—"

            vol = int(b.get("volume", 0))
            vol_wan = vol / 10000

            table.add_row(
                date,
                f"{float(b.get('open', 0)):.2f}",
                f"{float(b.get('high', 0)):.2f}",
                f"{float(b.get('low', 0)):.2f}",
                f"{float(close):.2f}",
                f"{vol_wan:,.1f}万",
                pct_str,
            )
