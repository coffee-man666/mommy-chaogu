"""DashboardView — 数据看板（§3.1, §6.2-6.5）。

模式 B：自选股/持仓/主题/信号 四页 TabbedContent。
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Static,
    TabbedContent,
    TabPane,
)

from mommy_chaogu.tui.services.formatting import (
    change_arrow,
    change_color,
    format_amount,
    format_change_pct,
    format_flow,
    format_price,
)

_log = logging.getLogger(__name__)

_EMPTY_WATCH = """[dim]
还没有自选股

  mommy watchlist add 600519 --group 白酒
[/]"""

_EMPTY_PORTFOLIO = """[dim]
还没有持仓记录

  mommy portfolio add-position ...
[/]"""

_EMPTY_SIGNALS = """[dim]
暂无信号记录

  按 s 开启盘中信号扫描
[/]"""


class WatchTable(DataTable[Any]):
    """自选股表。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("o", "cycle_sort", "排序"),
        Binding("a", "add_stock", "加自选"),
        Binding("x", "remove_stock", "移除"),
        Binding("enter", "show_detail", "详情"),
    ]

    _sort_key: int = 0  # 0=涨跌幅, 1=主力净流入, 2=代码

    def __init__(self) -> None:
        super().__init__(id="watch-table")
        self._rows_data: list[dict[str, Any]] = []

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_column("代码", width=8)
        self.add_column("名称", width=10)
        self.add_column("现价", width=10)
        self.add_column("涨跌幅", width=10)
        self.add_column("主力", width=10)

    def update_data(self, rows: list[dict[str, Any]]) -> None:
        """更新表格数据（全量重建，P1 优化为 cell 级 diff）。"""
        self._rows_data = self._sort_rows(rows)
        self.clear()
        for r in self._rows_data:
            code = r.get("code", "")
            name = r.get("name", code)
            price = format_price(r.get("price"))
            chg = r.get("change_pct")
            chg_str = f"{change_arrow(chg)} {format_change_pct(chg)}"
            chg_color = change_color(chg)
            flow_str = format_flow(r.get("main_flow"))
            flow_color = change_color(r.get("main_flow"))
            self.add_row(
                code,
                name,
                price,
                f"[{chg_color}]{chg_str}[/{chg_color}]",
                f"[{flow_color}]{flow_str}[/{flow_color}]",
            )

    def _sort_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._sort_key == 0:
            return sorted(rows, key=lambda r: float(r.get("change_pct") or 0), reverse=True)
        if self._sort_key == 1:
            return sorted(rows, key=lambda r: float(r.get("main_flow") or 0), reverse=True)
        return sorted(rows, key=lambda r: r.get("code", ""))

    def action_cycle_sort(self) -> None:
        labels = ["涨跌幅", "主力净流入", "代码"]
        self._sort_key = (self._sort_key + 1) % 3
        if self._rows_data:
            self.update_data(self._rows_data)
        self.app.notify(f"排序: {labels[self._sort_key]}", timeout=1)

    def action_add_stock(self) -> None:
        self.app.notify("添加自选请使用: mommy watchlist add <code> --group <组名>", timeout=3)

    def action_remove_stock(self) -> None:
        if self.cursor_row < 0 or self.cursor_row >= len(self._rows_data):
            return
        code = self._rows_data[self.cursor_row].get("code", "")
        self.app.notify(f"移除请使用: mommy watchlist remove {code}", timeout=3)

    def action_show_detail(self) -> None:
        if self.cursor_row < 0 or self.cursor_row >= len(self._rows_data):
            return
        code = self._rows_data[self.cursor_row].get("code", "")
        self.app.open_stock_detail(code)  # type: ignore[attr-defined]


class SummaryCard(Static):
    """持仓摘要卡片。"""


class SummaryCards(Horizontal):
    """持仓顶部三联摘要。"""

    def compose(self) -> ComposeResult:
        yield SummaryCard("总市值\n—", id="card-value")
        yield SummaryCard("当日盈亏\n—", id="card-day-pnl")
        yield SummaryCard("累计盈亏\n—", id="card-total-pnl")

    def update_summary(self, summary: dict[str, Any]) -> None:
        mv = summary.get("total_market_value")
        pnl = summary.get("total_unrealized_pnl")
        pnl_pct = summary.get("total_unrealized_pnl_pct")

        self.query_one("#card-value", SummaryCard).update(
            f"总市值\n[bold]{format_amount(mv)}[/]"
        )
        day_str = "—"
        if pnl is not None:
            color = change_color(float(pnl))
            day_str = f"[{color}]{format_flow(pnl)}[/{color}]"
        self.query_one("#card-day-pnl", SummaryCard).update(f"当日盈亏\n{day_str}")

        total_str = "—"
        if pnl is not None and pnl_pct is not None:
            color = change_color(float(pnl))
            total_str = f"[{color}]{format_flow(pnl)} ({format_change_pct(pnl_pct)})[/{color}]"
        self.query_one("#card-total-pnl", SummaryCard).update(f"累计盈亏\n{total_str}")


class HoldTable(DataTable[Any]):
    """持仓明细表。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("enter", "show_detail", "详情"),
    ]

    def __init__(self) -> None:
        super().__init__(id="hold-table")

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_column("代码", width=8)
        self.add_column("名称", width=10)
        self.add_column("持仓", width=8)
        self.add_column("成本", width=8)
        self.add_column("现价", width=10)
        self.add_column("盈亏", width=12)

    def update_data(self, positions: list[Any]) -> None:
        self.clear()
        for p in positions:
            code = getattr(p, "code", "")
            name = getattr(p, "name", code)
            shares = getattr(p, "shares", 0)
            cost = format_price(getattr(p, "cost_price", None))
            price = format_price(getattr(p, "current_price", None))
            pnl = getattr(p, "unrealized_pnl", None)
            pnl_str = format_flow(pnl)
            color = change_color(float(pnl) if pnl else None)
            self.add_row(code, name, str(shares), cost, price, f"[{color}]{pnl_str}[/{color}]")

    def action_show_detail(self) -> None:
        if self.cursor_row < 0:
            return
        self.app.notify("详情页开发中", timeout=2)


class ThemeListWidget(Static):
    """主题列表占位（P1 完善）。"""


class SignalLogWidget(Static):
    """信号日志占位（P1 完善）。"""


class DashboardView(Vertical):
    """数据看板视图。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("1", "switch_tab('watch')", "自选"),
        Binding("2", "switch_tab('hold')", "持仓"),
        Binding("3", "switch_tab('theme')", "主题"),
        Binding("4", "switch_tab('signal')", "信号"),
    ]

    def __init__(self, id: str = "dashboard") -> None:
        super().__init__(id=id)

    def compose(self) -> ComposeResult:
        with TabbedContent(id="dashboard-tabs", initial="watch"):
            with TabPane("自选股", id="watch"):
                yield WatchTable()
            with TabPane("持仓", id="hold"):
                yield SummaryCards(id="summary-cards")
                yield HoldTable()
            with TabPane("主题", id="theme"):
                yield Static(_EMPTY_WATCH, classes="empty-state")  # P1 填充
            with TabPane("信号", id="signal"):
                yield Static(_EMPTY_SIGNALS, classes="empty-state")

    # ------------------------------------------------------------------
    # 数据更新接口（由 app / polling worker 调用）
    # ------------------------------------------------------------------

    def update_watchlist(self, rows: list[dict[str, Any]]) -> None:
        """更新自选股表。"""
        table = self.query_one("#watch-table", WatchTable)
        if not rows:
            return
        table.update_data(rows)

    def update_portfolio(self, summary: dict[str, Any]) -> None:
        """更新持仓页。"""
        cards = self.query_one("#summary-cards", SummaryCards)
        cards.update_summary(summary)
        hold = self.query_one("#hold-table", HoldTable)
        positions = summary.get("positions", [])
        hold.update_data(positions)

    def action_switch_tab(self, tab_id: str) -> None:
        """切换看板 tab。"""
        self.query_one("#dashboard-tabs", TabbedContent).active = tab_id
