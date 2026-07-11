"""DashboardView — 数据看板（§3.1, §6.2-6.5）。

模式 B：自选股/持仓/主题/信号 四页 TabbedContent。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Input,
    RichLog,
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
from mommy_chaogu.tui.widgets.top_bar import market_phase

_log = logging.getLogger(__name__)

_SIGNALS_LOG = Path("data/signals.log")

_EMPTY_WATCH = """[dim]
还没有自选股

  mommy watchlist add 600519 --group 白酒
[/]"""

_EMPTY_PORTFOLIO = """[dim]
还没有持仓记录

  mommy portfolio add-position ...
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
        self.app.push_screen(_AddStockModal(), self._do_add_stock)

    def _do_add_stock(self, code: str | None) -> None:
        """Modal 回调：添加自选股。"""
        if not code:
            return
        app = self.app
        store = app.services.data.watchlist_store  # type: ignore[attr-defined]
        if store is None:
            app.notify("数据服务未就绪", timeout=2)
            return
        try:
            # 确保默认分组存在，然后添加
            store.get_or_create_group("默认")
            store.add_entry(code, "默认")
            app.notify(f"已添加 {code} 到「默认」分组", timeout=2)
            app._refresh_data()  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"添加失败: {e}", timeout=3)

    def action_remove_stock(self) -> None:
        if self.cursor_row < 0 or self.cursor_row >= len(self._rows_data):
            return
        code = self._rows_data[self.cursor_row].get("code", "")
        app = self.app
        store = app.services.data.watchlist_store  # type: ignore[attr-defined]
        if store is None:
            app.notify("数据服务未就绪", timeout=2)
            return
        # 从所有包含该 code 的分组中移除
        removed_any = False
        try:
            by_group = store.list_entries_by_group()
            for group_name, entries in by_group.items():
                if any(getattr(e, "code", None) == code for e in entries):
                    store.remove_entry(code, group_name)
                    removed_any = True
            if removed_any:
                app.notify(f"已移除 {code}", timeout=2)
                app._refresh_data()  # type: ignore[attr-defined]
            else:
                app.notify(f"{code} 不在自选股中", timeout=2)
        except Exception as e:
            app.notify(f"移除失败: {e}", timeout=3)

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
            if isinstance(p, dict):
                code = p.get("code", "")
                name = p.get("name", code)
                shares = p.get("shares", 0)
                cost = format_price(p.get("avg_cost") or p.get("cost_price"))
                price = format_price(p.get("current_price") or p.get("price"))
                pnl = p.get("unrealized_pnl")
            else:
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
        # HoldTable 没有缓存 row data，用 query 拿当前行的 code 列
        try:
            row_data = self.get_row_at(self.cursor_row)
        except Exception:
            return
        if not row_data:
            return
        code = str(row_data[0])
        self.app.open_stock_detail(code)  # type: ignore[attr-defined]


class ThemeListWidget(DataTable[Any]):
    """主题列表 — 半导体产业链参考库。"""

    def __init__(self) -> None:
        super().__init__(id="theme-table")

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_column("代码", width=8)
        self.add_column("名称", width=12)
        self.add_column("产业链位置", width=10)
        self._load_data()

    def _load_data(self) -> None:
        """从 reference.db 读取半导体产业链股票。"""
        try:
            from mommy_chaogu.db_paths import REFERENCE_DB
            from mommy_chaogu.semicon.store import SemiconStore

            store = SemiconStore(REFERENCE_DB)
            stocks = store.list_all()
            if not stocks:
                return
            for s in stocks:
                self.add_row(
                    s.code,
                    getattr(s, "name", s.code),
                    getattr(s, "chain_position", ""),
                )
        except Exception as e:
            _log.warning("加载半导体产业链失败: %s", e)


class SignalLogWidget(RichLog):
    """信号历史日志。"""

    def __init__(self) -> None:
        super().__init__(id="signal-log", markup=True)

    def on_mount(self) -> None:
        self._load_log()

    def _load_log(self) -> None:
        """读取 data/signals.log（如果存在），否则显示空态。"""
        if not _SIGNALS_LOG.exists():
            self.write("[dim]暂无信号记录\n\n  按 s 开启盘中信号扫描[/]")
            return
        try:
            text = _SIGNALS_LOG.read_text(encoding="utf-8").rstrip()
            if not text:
                self.write("[dim]暂无信号记录[/]")
                return
            lines = text.split("\n")
            # 只显示最后 200 行，避免大量历史日志卡顿
            for line in lines[-200:]:
                self.write(line)
        except Exception as e:
            _log.warning("读取信号日志失败: %s", e)
            self.write(f"[red]读取信号日志失败: {e}[/]")


class _AddStockModal(ModalScreen[str | None]):
    """添加自选股的简单输入弹窗。"""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "取消"),
    ]

    DEFAULT_CSS = """
    _AddStockModal {
        align: center middle;
    }
    #add-stock-box {
        width: 50;
        height: 7;
        border: round $primary;
        padding: 1 2;
    }
    #add-stock-prompt {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="add-stock-box"):
            yield Static("输入股票代码添加到「默认」分组：", id="add-stock-prompt")
            yield Input(placeholder="如 688981", id="add-stock-input")

    def on_mount(self) -> None:
        self.query_one("#add-stock-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "add-stock-input":
            code = event.value.strip()
            self.dismiss(code if code else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DashboardView(Vertical):
    """数据看板视图。"""

    signal_scan_on: reactive[bool] = reactive(False)

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("1", "switch_tab('watch')", "自选"),
        Binding("2", "switch_tab('hold')", "持仓"),
        Binding("3", "switch_tab('theme')", "主题"),
        Binding("4", "switch_tab('signal')", "信号"),
        Binding("s", "toggle_signal_scan", "信号扫描"),
    ]

    def __init__(self, id: str = "dashboard") -> None:
        super().__init__(id=id)
        self._last_refresh: float = 0.0
        self._last_signal_scan: float = 0.0
        self._signal_scan_id: int = 0

    def compose(self) -> ComposeResult:
        with TabbedContent(id="dashboard-tabs", initial="watch"):
            with TabPane("自选股", id="watch"):
                yield WatchTable()
            with TabPane("持仓", id="hold"):
                yield SummaryCards(id="summary-cards")
                yield HoldTable()
            with TabPane("主题", id="theme"):
                yield ThemeListWidget()
            with TabPane("信号", id="signal"):
                yield SignalLogWidget()

    def on_mount(self) -> None:
        """设置 1 秒心跳，按市场阶段自适应刷新。"""
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        """心跳：根据市场阶段决定刷新间隔。

        - 交易中（9:30-11:30 / 13:00-15:00）→ 每 5 秒
        - 午休（11:30-13:00）→ 每 60 秒
        - 已收盘 / 集合竞价 / 周末 → 不刷新
        """
        phase = market_phase()
        if phase == "交易中":
            interval = 5.0
        elif phase == "午休":
            interval = 60.0
        else:
            return  # 收盘/竞价/周末 — 不刷新

        now = time.monotonic()
        if now - self._last_refresh >= interval:
            self._last_refresh = now
            self.app._refresh_data()  # type: ignore[attr-defined]

        # 信号扫描：仅交易中，每 30 秒
        if (
            self.signal_scan_on
            and phase == "交易中"
            and now - self._last_signal_scan >= 30.0
        ):
            self._last_signal_scan = now
            self.run_worker(
                self._do_signal_scan,
                name="signal-scan",
                group="signal-scan",
                exclusive=True,
                thread=True,
            )

    def watch_signal_scan_on(self, value: bool) -> None:
        """响应信号扫描开关。"""
        if value:
            self._last_signal_scan = 0.0  # 下一次 tick 立即触发
            self.app.notify("信号扫描已开启（盘中每30秒）", timeout=3)
        else:
            self.app.notify("信号扫描已关闭", timeout=2)

    def action_toggle_signal_scan(self) -> None:
        """s 键切换信号扫描开关。"""
        self.signal_scan_on = not self.signal_scan_on

    def _do_signal_scan(self) -> None:
        """worker 线程：构建快照 → 跑 Alerter → 回主线程显示。"""
        services: Any = self.app.services  # type: ignore[attr-defined]
        data_svc: Any = services.data
        adapter: Any = getattr(data_svc, "adapter", None)
        store: Any = getattr(data_svc, "watchlist_store", None)
        if adapter is None or store is None:
            return

        from mommy_chaogu.monitor.poller import Snapshot, SnapshotRow
        from mommy_chaogu.signals import Alerter

        # 构建 SnapshotRow（按 code 去重，同 code 取第一个 group）
        seen: set[str] = set()
        rows: list[Any] = []
        try:
            by_group = store.list_entries_by_group()
        except Exception as e:
            _log.debug("信号扫描读取自选股失败: %s", e)
            return

        for group_name, entries in by_group.items():
            for entry in entries:
                code = getattr(entry, "code", "")
                if code in seen:
                    continue
                seen.add(code)
                try:
                    quote = adapter.get_quote(code)
                except Exception as e:
                    _log.debug("信号扫描 get_quote(%s) 失败: %s", code, e)
                    continue
                if quote is None:
                    continue
                flow: Any = None
                try:
                    flows = adapter.get_today_money_flow(code)
                    if flows:
                        flow = flows[-1]
                except Exception:
                    pass
                rows.append(
                    SnapshotRow(
                        entry=entry,
                        group_name=group_name,
                        quote=quote,
                        latest_flow=flow,
                    )
                )

        if not rows:
            return

        self._signal_scan_id += 1
        snapshot = Snapshot.build(rows, self._signal_scan_id)
        alerter = Alerter.default(log_path=_SIGNALS_LOG)
        signals = alerter.evaluate(snapshot)
        if signals:
            alerter.write_signals_log(signals)
            formatted = [s.format() for s in signals]
            self.app.call_from_thread(self._display_signals, formatted)

    def _display_signals(self, formatted: list[str]) -> None:
        """主线程：向 signal-log 写入信号并弹通知。"""
        try:
            log_widget = self.query_one("#signal-log", RichLog)
        except Exception:
            return
        for line in formatted:
            log_widget.write(line)
        self.app.notify(
            f"触发 {len(formatted)} 条信号（信号页查看详情）",
            severity="warning",
            timeout=5,
        )

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
