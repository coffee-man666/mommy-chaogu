"""Monitor 单测 — 用 MockMarketDataAdapter 不依赖外部网络。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.market_data import MarketDataAdapter, Quote
from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    QuoteType,
)
from mommy_chaogu.monitor import Monitor
from mommy_chaogu.watchlist import WatchlistStore

# ---------- Mock Adapter ----------

class MockMarketDataAdapter:
    """测试用 mock adapter，可预设返回值。"""

    def __init__(
        self,
        quotes: dict[str, Quote] | None = None,
        flows: dict[str, list[MoneyFlow]] | None = None,
    ) -> None:
        self.name = "mock"
        self._quotes = quotes or {}
        self._flows = flows or {}
        self.call_log: list[tuple[str, tuple]] = []

    def get_quote(self, code: str) -> Quote | None:
        self.call_log.append(("get_quote", (code,)))
        return self._quotes.get(code)

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        self.call_log.append(("get_quotes", (tuple(codes),)))
        return [q for c in codes if (q := self._quotes.get(c)) is not None]

    def list_market_quotes(self) -> list[Quote]:
        return list(self._quotes.values())

    def get_order_book(self, code: str): return None
    def get_bars(self, code: str, **kw): return []
    def get_ticks(self, code: str, limit=None): return []

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        self.call_log.append(("get_today_money_flow", (code,)))
        return self._flows.get(code, [])

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        return self._flows.get(code, [])

    def get_belonging_boards(self, code: str): return []
    def health_check(self) -> bool:
        return True


def _make_quote(code: str, price: str, pct: str) -> Quote:
    return Quote(
        code=code,
        name=f"名称{code}",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal(price),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        prev_close=Decimal(price),
        change=Decimal("0"),
        change_pct=Decimal(pct),
        volume=100000,
        turnover=Money.from_yuan(100000000),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime(2026, 6, 26, 11, 30),
    )


def _make_flow(code: str, main: str, ts: datetime | None = None) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=f"名称{code}",
        timestamp=ts or datetime(2026, 6, 26, 11, 30),
        main_net=Money.from_yuan(main),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(0),
        super_large_net=Money.from_yuan(0),
    )


# ---------- Fixtures ----------

@pytest.fixture
def store(tmp_path: Path) -> WatchlistStore:
    s = WatchlistStore(tmp_path / "test.db")
    s.add_group("白酒")
    s.add_group("银行")
    s.add_entry("600519", "白酒", note="茅台")
    s.add_entry("000001", "银行")
    return s


@pytest.fixture
def monitor(store: WatchlistStore, tmp_path: Path) -> Monitor:
    quotes = {
        "600519": _make_quote("600519", "1184.98", "0.08"),
        "000001": _make_quote("000001", "10.27", "-1.44"),
    }
    flows = {
        "600519": [_make_flow("600519", "-368000000")],
        "000001": [_make_flow("000001", "+120000000")],
    }
    adapter = MockMarketDataAdapter(quotes=quotes, flows=flows)
    return Monitor(store, adapter, log_path=tmp_path / "monitor.log")


# ---------- Snapshot 构建 ----------

def test_snapshot_now_pulls_quotes_and_flows(monitor: Monitor, store: WatchlistStore) -> None:
    snap = monitor.snapshot_now()
    assert snap.n_codes == 2
    codes = {r.quote.code for r in snap.rows}
    assert codes == {"600519", "000001"}


def test_snapshot_aggregates_metrics(monitor: Monitor) -> None:
    snap = monitor.snapshot_now()
    # 600519: +0.08% (up), 000001: -1.44% (down)
    assert snap.n_up == 1
    assert snap.n_down == 1
    assert snap.n_flat == 0
    # 主力净流入: -368000000 + 120000000 = -248000000
    assert snap.total_main_net == Decimal("-248000000")


def test_snapshot_id_increments(monitor: Monitor) -> None:
    s1 = monitor.snapshot_now()
    s2 = monitor.snapshot_now()
    assert s2.snapshot_id == s1.snapshot_id + 1


def test_snapshot_assigns_group_name(monitor: Monitor) -> None:
    snap = monitor.snapshot_now()
    by_code = {r.quote.code: r.group_name for r in snap.rows}
    assert by_code == {"600519": "白酒", "000001": "银行"}


def test_snapshot_skips_codes_with_no_quote(store: WatchlistStore, tmp_path: Path) -> None:
    # 只 mock 了 600519
    quotes = {"600519": _make_quote("600519", "100", "0")}
    adapter = MockMarketDataAdapter(quotes=quotes, flows={})
    monitor = Monitor(store, adapter, log_path=None)
    snap = monitor.snapshot_now()
    assert snap.n_codes == 1


# ---------- 日志 ----------

def test_log_line_format(monitor: Monitor) -> None:
    snap = monitor.snapshot_now()
    line = monitor.log_line(snap)
    assert "[2026-06-26" in line
    assert "snapshot #1" in line
    assert "codes=2" in line
    assert "主力净流入=" in line
    assert "600519" in line
    assert "000001" in line


def test_write_log_appends_lines(monitor: Monitor, tmp_path: Path) -> None:
    snap1 = monitor.snapshot_now()
    snap2 = monitor.snapshot_now()
    monitor.write_log(snap1)
    monitor.write_log(snap2)
    log_path = tmp_path / "monitor.log"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert "snapshot #1" in lines[0]
    assert "snapshot #2" in lines[1]


def test_format_table_contains_all_rows(monitor: Monitor) -> None:
    snap = monitor.snapshot_now()
    table = monitor.format(snap)
    assert "600519" in table
    assert "000001" in table
    assert "白酒" in table
    assert "银行" in table
    assert "主力净流入" in table


def test_format_table_empty_pool(store: WatchlistStore) -> None:
    """自选池为空时给出友好提示。"""
    # 清空 entries（清掉所有分组会级联删 entries）
    for _g in store.list_groups():
        # 直接 SQL 删除绕过 ORM detach 问题
        from sqlalchemy import delete

        from mommy_chaogu.watchlist.models import StockEntry
        with store.engine.begin() as conn:
            conn.execute(delete(StockEntry))
            conn.execute(delete(__import__('mommy_chaogu.watchlist.models', fromlist=['Group']).Group))

    adapter = MockMarketDataAdapter()
    monitor = Monitor(store, adapter, log_path=None)
    snap = monitor.snapshot_now()
    table = monitor.format(snap)
    assert "共 0 只" in table
    assert "empty" in table.lower() or "空" in table or "0" in table


# ---------- 空 adapter 健康检查 ----------

def test_protocol_satisfaction() -> None:
    """MockAdapter 必须实现 MarketDataAdapter Protocol。"""
    adapter = MockMarketDataAdapter()
    assert isinstance(adapter, MarketDataAdapter)
