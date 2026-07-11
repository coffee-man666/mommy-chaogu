"""StockDetailScreen — 个股详情弹窗。

从看板/对话按 Enter 弹出，展示单只股票的完整画像：
行情头部 + K 线 + 资金流 + 基本面 + 公告。
数据通过 self.app.services.data 在后台线程拉取，call_from_thread 回填。
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from mommy_chaogu.tui.services.formatting import (
    change_arrow,
    change_color,
    format_change_pct,
    format_flow,
    format_price,
)

_log = logging.getLogger(__name__)


class StockDetailScreen(ModalScreen[None]):
    """个股详情弹窗。

    用法::

        app.push_screen(StockDetailScreen(code="688981"))

    按键：
        Esc  关闭
        a    添加自选（提示 CLI 命令）
        x    移除自选（提示 CLI 命令）
    """

    # Textual 基类 BINDINGS 允许 Binding 或 tuple，需保持类型一致（协变问题）
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "dismiss", "返回"),
        Binding("a", "add_watch", "加自选"),
        Binding("x", "remove_watch", "移除"),
    ]

    DEFAULT_CSS = """
    StockDetailScreen {
        align: center middle;
    }
    #stock-detail-scroll {
        width: 90%;
        height: 85%;
        border: round $primary;
        padding: 1 2;
    }
    #stock-header {
        text-align: center;
        margin-bottom: 1;
    }
    .stock-section {
        margin-top: 1;
        padding-top: 1;
        border-top: dashed $panel;
    }
    """

    def __init__(self, code: str) -> None:
        super().__init__()
        self.code = code

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="stock-detail-scroll"):
            # 头部：代码 + 名称 + 价格 + 涨跌
            yield Static(self._header_placeholder(), id="stock-header")
            # K 线占位（P3 阶段接入 klinecharts）
            with Vertical(classes="stock-section", id="kline-section"):
                yield Static("K 线图（即将上线）", classes="section-title")
                yield Static("加载中…", id="kline-area")
            # 资金流（近 5 日）
            with Vertical(classes="stock-section", id="flow-section"):
                yield Static("资金流（近5日）", classes="section-title")
                yield Static("加载中…", id="flow-area")
            # 基本面
            with Vertical(classes="stock-section", id="fundamentals-section"):
                yield Static("基本面", classes="section-title")
                yield Static("加载中…", id="fundamentals-area")
            # 近期公告
            with Vertical(classes="stock-section", id="announcements-section"):
                yield Static("近期公告", classes="section-title")
                yield Static("加载中…", id="announcements-area")

    def _header_placeholder(self) -> str:
        """加载完成前展示的最小头部。"""
        return f"#{self.code}  加载中…"

    # ------------------------------------------------------------------
    # 数据加载（后台线程）
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """挂载后启动后台线程拉取详情。"""
        self.run_worker(self._load_detail, thread=True)

    def _load_detail(self) -> None:
        """在后台线程中拉取行情/K线/资金流/基本面/公告，逐段回填。"""
        services: Any = self.app.services  # type: ignore[attr-defined]
        data_svc: Any = services.data
        adapter: Any = getattr(data_svc, "adapter", None)

        # --- 行情头部 ---
        name = self.code
        price_text = "—"
        change_text = "—"
        if adapter is not None:
            try:
                quote = adapter.get_quote(self.code)
                if quote is not None:
                    name = getattr(quote, "name", self.code) or self.code
                    price_text = format_price(getattr(quote, "price", None))
                    pct = getattr(quote, "change_pct", None)
                    arrow = change_arrow(pct)
                    color = change_color(pct)
                    change_text = f"[{color}]{arrow} {format_change_pct(pct)}[/{color}]"
            except Exception as e:
                _log.debug("拉取行情 %s 失败: %s", self.code, e)
        header = f"#{self.code}  {name}    {price_text}  {change_text}"
        self.app.call_from_thread(self._update_widget, "#stock-header", header)

        # --- K 线 ---
        if adapter is not None:
            try:
                from mommy_chaogu.market_data.types import BarInterval

                bars = adapter.get_bars(self.code, interval=BarInterval.D1, limit=30)
                if bars:
                    # P3 阶段会接入 klinecharts，暂以文字摘要占位
                    latest = bars[-1]
                    bar_text = (
                        f"近 {len(bars)} 根日线 | "
                        f"最新收盘 {format_price(getattr(latest, 'close', None))}"
                    )
                    self.app.call_from_thread(self._update_widget, "#kline-area", bar_text)
                else:
                    self.app.call_from_thread(self._update_widget, "#kline-area", "暂无 K 线数据")
            except Exception as e:
                _log.debug("拉取 K 线 %s 失败: %s", self.code, e)
                self.app.call_from_thread(self._update_widget, "#kline-area", "K 线加载失败")

        # --- 资金流（近 5 日）---
        if adapter is not None:
            try:
                flows = adapter.get_history_money_flow(self.code, days=5)
                if flows:
                    lines: list[str] = []
                    for fl in flows:
                        date_str = str(getattr(fl, "date", ""))
                        main = getattr(fl, "main_net", None)
                        lines.append(f"{date_str}  主力净流入 {format_flow(main)}")
                    self.app.call_from_thread(self._update_widget, "#flow-area", "\n".join(lines))
                else:
                    self.app.call_from_thread(self._update_widget, "#flow-area", "暂无资金流数据")
            except Exception as e:
                _log.debug("拉取资金流 %s 失败: %s", self.code, e)
                self.app.call_from_thread(self._update_widget, "#flow-area", "资金流加载失败")

        # --- 基本面 ---
        try:
            from mommy_chaogu.market_data.fundamentals_api import get_fundamentals

            fund = get_fundamentals(self.code)
            if fund:
                lines = []
                for label, value in fund.items():
                    lines.append(f"{label}: {value}")
                self.app.call_from_thread(
                    self._update_widget, "#fundamentals-area", "\n".join(lines)
                )
            else:
                self.app.call_from_thread(
                    self._update_widget, "#fundamentals-area", "暂无基本面数据"
                )
        except Exception as e:
            _log.debug("拉取基本面 %s 失败: %s", self.code, e)
            self.app.call_from_thread(self._update_widget, "#fundamentals-area", "基本面加载失败")

        # --- 近期公告 ---
        try:
            from mommy_chaogu.market_data.news_api import get_announcements

            anns = get_announcements(self.code, limit=5)
            if anns:
                lines = []
                for ann in anns:
                    date_str = ann.get("date", "")
                    title = ann.get("title", "")
                    lines.append(f"{date_str}  {title}")
                self.app.call_from_thread(
                    self._update_widget, "#announcements-area", "\n".join(lines)
                )
            else:
                self.app.call_from_thread(self._update_widget, "#announcements-area", "暂无公告")
        except Exception as e:
            _log.debug("拉取公告 %s 失败: %s", self.code, e)
            self.app.call_from_thread(self._update_widget, "#announcements-area", "公告加载失败")

    def _update_widget(self, selector: str, text: str) -> None:
        """在 UI 线程中安全更新某个 Static 的文本。"""
        try:
            widget = self.query_one(selector, Static)
            widget.update(text)
        except Exception as e:  # widget 可能已随弹窗关闭而销毁
            _log.debug("更新 %s 失败: %s", selector, e)

    # ------------------------------------------------------------------
    # 按键动作
    # ------------------------------------------------------------------

    def action_add_watch(self) -> None:
        """提示用户通过 CLI 添加自选。"""
        self.notify(
            f"请在终端执行：\nmommy watchlist add {self.code}",
            title="加自选",
            timeout=6,
        )

    def action_remove_watch(self) -> None:
        """提示用户通过 CLI 移除自选。"""
        self.notify(
            f"请在终端执行：\nmommy watchlist remove {self.code}",
            title="移除自选",
            timeout=6,
        )
