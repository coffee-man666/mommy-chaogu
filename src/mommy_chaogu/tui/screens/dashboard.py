"""数据看板屏（Tab 切换过去）。

TabbedContent 标签页：自选股 / 持仓 / 主题 / 信号。
底部状态栏。

Tab → 切换回对话。
"""

from __future__ import annotations

import contextlib
import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Static, TabbedContent, TabPane

from mommy_chaogu.tui.widgets.quote_table import QuoteTable
from mommy_chaogu.tui.widgets.status_bar import StatusBar

_log = logging.getLogger(__name__)

COLOR_UP = "red"
COLOR_DOWN = "green"

# 匹配 Textual DOMNode.BINDINGS 的类型
_Bindings = list[Binding | tuple[str, str] | tuple[str, str, str]]


# ======================================================================
# 内联 Widget：持仓 / 主题 / 信号
# ======================================================================


class HoldingsTable(Vertical):
    """持仓表（内联在 dashboard.py）。

    显示每只持仓的代码/名称/数量/成本/现价/盈亏。
    """

    DEFAULT_CSS = """
    HoldingsTable {
        height: 100%;
        border: round $panel;
    }
    HoldingsTable > .title {
        padding: 0 1;
        height: 1;
        background: $boost;
    }
    HoldingsTable > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._refresh_task: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("💰 持仓", classes="title")
        yield DataTable(id="holdings-grid", cursor_type="row")

    async def on_mount(self) -> None:
        table = self.query_one("#holdings-grid", DataTable)
        table.add_column("代码", width=8)
        table.add_column("名称", width=10)
        table.add_column("数量", width=10)
        table.add_column("成本", width=10)
        table.add_column("现价", width=10)
        table.add_column("盈亏", width=14)

        self._refresh_task = self.set_interval(10, self._refresh)
        await self._refresh()

    def on_unmount(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.stop()

    async def _refresh(self) -> None:
        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        try:
            summary = await data_service.get_portfolio_summary()
        except Exception as e:
            _log.debug("刷新持仓失败: %s", e)
            return

        table = self.query_one("#holdings-grid", DataTable)
        table.clear()

        positions = summary.get("positions", [])
        if not positions:
            table.add_row("—", "暂无持仓", "", "", "", "")
            return

        for p in positions:
            pos = p.get("position")
            if pos is None:
                continue
            code = str(getattr(pos, "code", ""))
            name = str(getattr(pos, "name", "") or code)
            shares = int(p.get("shares", 0))
            cost = p.get("avg_cost")
            cur = p.get("current_price")
            pnl = p.get("unrealized_pnl")

            cost_str = f"{float(cost):.2f}" if cost else "—"
            cur_str = f"{float(cur):.2f}" if cur else "—"

            if pnl is not None:
                pnl_val = float(pnl)
                color = COLOR_UP if pnl_val >= 0 else COLOR_DOWN
                sign = "+" if pnl_val >= 0 else ""
                pnl_str: str | tuple[str, str] = (
                    f"[{color}]{sign}{pnl_val:,.2f}[/{color}]",
                    color,
                )
            else:
                pnl_str = "—"

            table.add_row(code, name, str(shares), cost_str, cur_str, pnl_str)


class ThemeBrowser(Vertical):
    """主题浏览器（内联在 dashboard.py）。

    浏览半导体产业链参考库，按链条分类列出。
    """

    DEFAULT_CSS = """
    ThemeBrowser {
        height: 100%;
        border: round $panel;
    }
    ThemeBrowser > .title {
        padding: 0 1;
        height: 1;
        background: $boost;
    }
    ThemeBrowser > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._load_task: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("🏭 半导体产业链", classes="title")
        yield DataTable(id="theme-grid", cursor_type="row", zebra_stripes=True)

    async def on_mount(self) -> None:
        table = self.query_one("#theme-grid", DataTable)
        table.add_column("链条", width=16)
        table.add_column("环节", width=14)
        table.add_column("代码", width=8)
        table.add_column("名称", width=14)

        await self._load()

    def on_unmount(self) -> None:
        if self._load_task is not None:
            self._load_task.stop()

    async def _load(self) -> None:
        from anyio import to_thread

        def _fetch() -> list[tuple[str, str, str, str]]:
            try:
                from mommy_chaogu.db_paths import REFERENCE_DB
                from mommy_chaogu.semicon import SemiconStore

                store = SemiconStore(REFERENCE_DB)
                rows: list[tuple[str, str, str, str]] = []
                all_stocks = store.list_all()
                for s in all_stocks:
                    chain = getattr(s, "chain_position", "") or ""
                    sub = getattr(s, "subcategory", "") or ""
                    code = getattr(s, "code", "") or ""
                    name = getattr(s, "name", "") or ""
                    rows.append((str(chain), str(sub), str(code), str(name)))
                return rows
            except Exception as e:
                _log.debug("加载产业链失败: %s", e)
                return []

        rows = await to_thread.run_sync(_fetch)

        table = self.query_one("#theme-grid", DataTable)
        table.clear()

        if not rows:
            table.add_row("—", "暂无产业链数据", "", "")
            return

        for chain, sub, code, name in rows:
            table.add_row(chain, sub, code, name)


class SignalList(Vertical):
    """信号列表（内联在 dashboard.py）。

    列出内置告警规则，并对自选股实时评估触发情况。
    """

    DEFAULT_CSS = """
    SignalList {
        height: 100%;
        border: round $panel;
    }
    SignalList > .title {
        padding: 0 1;
        height: 1;
        background: $boost;
    }
    SignalList > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._eval_task: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("🔔 信号监控", classes="title")
        yield DataTable(id="signal-grid", cursor_type="row")

    async def on_mount(self) -> None:
        table = self.query_one("#signal-grid", DataTable)
        table.add_column("规则", width=24)
        table.add_column("描述", width=40)

        self._load_rules()
        self._eval_task = self.set_interval(15, self._evaluate)
        await self._evaluate()

    def on_unmount(self) -> None:
        if self._eval_task is not None:
            self._eval_task.stop()

    def _load_rules(self) -> None:
        """加载内置告警规则列表。"""
        table = self.query_one("#signal-grid", DataTable)
        try:
            from mommy_chaogu.signals import default_rules

            rules = default_rules()
            for r in rules:
                rid = r.rule_id
                desc = getattr(r, "config", None)
                desc_str = str(desc) if desc else ""
                table.add_row(rid, desc_str)
        except Exception as e:
            _log.debug("加载信号规则失败: %s", e)
            table.add_row("—", f"加载失败: {e}")

    async def _evaluate(self) -> None:
        """对自选股实时评估信号（结果追加到表格底部）。"""
        # 简单展示：拉自选股报价，统计涨跌
        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        try:
            codes = await data_service.get_all_watchlist_codes()
        except Exception:
            return

        if not codes:
            return

        try:
            quotes = await data_service.get_quotes(codes)
        except Exception as e:
            _log.debug("信号评估拉行情失败: %s", e)
            return

        n_up = sum(1 for q in quotes if float(q.change_pct) > 0)
        n_down = sum(1 for q in quotes if float(q.change_pct) < 0)

        # 更新标题显示统计
        with contextlib.suppress(Exception):
            title = self.query_one(".title", Static)
            title.update(
                f"🔔 信号监控 | "
                f"[{COLOR_UP}]↑{n_up}[/{COLOR_UP}] "
                f"[{COLOR_DOWN}]↓{n_down}[/{COLOR_DOWN}] "
                f"共 {len(quotes)} 只"
            )


# ======================================================================
# 看板主屏
# ======================================================================


class DashboardScreen(Screen[object]):
    """数据看板屏。

    TabbedContent：自选股 / 持仓 / 主题 / 信号。
    Tab → 切换回对话。
    """

    BINDINGS: ClassVar[_Bindings] = [
        Binding("tab", "cycle_screen", "对话", priority=True),
        Binding("ctrl+q", "quit", "退出"),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    DashboardScreen > TabbedContent {
        height: 1fr;
    }
    DashboardScreen > TabbedContent > ContentSwitcher > TabPane {
        padding: 0;
    }
    DashboardScreen > StatusBar {
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("自选股", id="tab-watchlist"):
                yield QuoteTable()
            with TabPane("持仓", id="tab-portfolio"):
                yield HoldingsTable()
            with TabPane("主题", id="tab-themes"):
                yield ThemeBrowser()
            with TabPane("信号", id="tab-signals"):
                yield SignalList()
        yield StatusBar()

    def on_quote_table_quote_row_activated(self, event: QuoteTable.QuoteRowActivated) -> None:
        """行情表回车 → push 详情屏。"""
        from mommy_chaogu.tui.screens.detail import DetailScreen

        self.app.push_screen(DetailScreen(code=event.code, name=event.name))
