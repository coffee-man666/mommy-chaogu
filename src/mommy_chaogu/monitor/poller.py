"""监控轮询核心。

Snapshot：一次抓取的数据快照
Monitor：执行轮询 + 输出到控制台 + 追加日志

设计原则：
- Snapshot 是不可变 dataclass，方便测试和缓存
- Monitor 接收任意 MarketDataAdapter 和 WatchlistStore（依赖倒置）
- 控制台输出用 ANSI 清屏 + 重绘（妈妈体验友好）
- 日志每行一条（plain text），团长问起来直接 grep / tail
"""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from mommy_chaogu.market_data import MarketDataAdapter, Quote
from mommy_chaogu.market_data.types import MoneyFlow
from mommy_chaogu.monitor.output import format_log_line, format_table
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import StockEntry, WatchlistStore

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    """自选股池里一只股票的一行快照。"""
    entry: StockEntry
    group_name: str
    quote: Quote
    latest_flow: MoneyFlow | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """一次完整的快照。"""
    timestamp: datetime
    snapshot_id: int
    rows: tuple[SnapshotRow, ...]
    total_main_net: Decimal = Decimal("0")
    n_codes: int = 0
    n_up: int = 0
    n_down: int = 0
    n_flat: int = 0

    @classmethod
    def build(cls, rows: list[SnapshotRow], snapshot_id: int) -> Snapshot:
        """从行数据构建快照，自动计算汇总指标。"""
        n = len(rows)
        n_up = sum(1 for r in rows if r.quote.change_pct > 0)
        n_down = sum(1 for r in rows if r.quote.change_pct < 0)
        n_flat = n - n_up - n_down
        total_main = sum(
            (r.latest_flow.main_net.amount for r in rows if r.latest_flow is not None),
            Decimal("0"),
        )
        return cls(
            timestamp=datetime.now(UTC).astimezone(),
            snapshot_id=snapshot_id,
            rows=tuple(rows),
            total_main_net=total_main,
            n_codes=n,
            n_up=n_up,
            n_down=n_down,
            n_flat=n_flat,
        )


class Monitor:
    """基于自选池的行情监控。

    用法：
        store = WatchlistStore(Path("data/watchlist.db"))
        adapter = EfinanceAdapter()
        monitor = Monitor(store, adapter, log_path=Path("data/monitor.log"))

        # 一次性快照
        snap = monitor.snapshot_now()
        print(monitor.format(snap))

        # 持续轮询（Ctrl+C 退出）
        monitor.run(interval_seconds=30)
    """

    def __init__(
        self,
        store: WatchlistStore,
        adapter: MarketDataAdapter,
        log_path: Path | None = None,
        stream: TextIO | None = None,
        alerter: Alerter | None = None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.log_path = log_path
        self.stream = stream or sys.stdout
        self.alerter = alerter
        self._snapshot_id = 0

        # 准备日志
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # 不重置，追加模式
            _log.info("monitor log path: %s", log_path)

    # ---------- 核心：拉一次快照 ----------

    def snapshot_now(self) -> Snapshot:
        """拉一次所有自选股的实时报价 + 当日资金流最新点。

        策略：
        1. 拉全市场实时报价（efinance 的 get_realtime_quotes() 稳定）
        2. 过滤出自选股 codes
        3. 逐个股拉当日资金流（资金流接口走 push2his，相对稳定）

        这样避免调用不稳定的 get_latest_quote(code) 单股接口。
        """
        self._snapshot_id += 1

        # 1. 拿所有自选股的 entry（含 group 信息）
        by_code = self._index_entries()
        codes = sorted(by_code.keys())
        if not codes:
            return Snapshot.build([], self._snapshot_id)

        # 2. 拉全市场快照（稳定接口）
        try:
            all_quotes = self.adapter.list_market_quotes()
        except Exception as e:
            _log.error("list_market_quotes failed: %s", e)
            all_quotes = []
        quote_by_code = {q.code: q for q in all_quotes if q.code in by_code}

        # 2b. 如果全市场拿不到（腾讯接口无全市场），逐股拉
        #     这样 TencentAdapter fallback 能提供自选股报价
        missing_codes = [c for c in codes if c not in quote_by_code]
        if missing_codes:
            _log.info("falling back to per-code quotes for %d codes", len(missing_codes))
            for code in missing_codes:
                try:
                    q = self.adapter.get_quote(code)
                    if q is not None:
                        quote_by_code[code] = q
                except Exception as e:
                    _log.warning("get_quote(%s) failed: %s", code, e)

        # 3. 对拉到的股票，回填 name
        self._backfill_names(list(quote_by_code.values()))

        # 4. 拉当日资金流（取最新一点）
        flows_by_code: dict[str, MoneyFlow] = {}
        for code in codes:
            try:
                flows = self.adapter.get_today_money_flow(code)
                if flows:
                    flows_by_code[code] = flows[-1]
            except Exception as e:
                _log.warning("get_today_money_flow(%s) failed: %s", code, e)

        # 5. 拼装 SnapshotRow
        rows: list[SnapshotRow] = []
        for code in codes:
            quote = quote_by_code.get(code)
            if quote is None:
                # 自选股不在全市场快照里（可能网络问题），跳过
                _log.warning("snapshot missing code=%s (not in market quotes)", code)
                continue
            flow = flows_by_code.get(code)
            entry = by_code[code][0]  # 多 group 重复时取第一个
            group_name = by_code[code][1]
            rows.append(SnapshotRow(
                entry=entry,
                group_name=group_name,
                quote=quote,
                latest_flow=flow,
            ))

        return Snapshot.build(rows, self._snapshot_id)

    def _index_entries(self) -> dict[str, tuple[StockEntry, str]]:
        """返回 {code: (entry, group_name)}，同一 code 多分组时取第一个。"""
        result: dict[str, tuple[StockEntry, str]] = {}
        by_group = self.store.list_entries_by_group()
        for group_name, entries in by_group.items():
            for e in entries:
                if e.code not in result:
                    result[e.code] = (e, group_name)
        return result

    def _backfill_names(self, quotes: list[Quote]) -> None:
        """回填数据库里 name 为空的 entry。"""
        for q in quotes:
            if q.name:
                self.store.backfill_name(q.code, q.name)

    # ---------- 输出 ----------

    def format(self, snapshot: Snapshot) -> str:
        return format_table(snapshot)

    def log_line(self, snapshot: Snapshot) -> str:
        return format_log_line(snapshot)

    def print_snapshot(self, snapshot: Snapshot, *, clear_screen: bool = False) -> None:
        """打印到 stdout，可选清屏（持续轮询时用）。"""
        if clear_screen:
            # ANSI: 清屏 + 移到顶部
            self.stream.write("\033[2J\033[H")
            self.stream.flush()
        self.stream.write(self.format(snapshot) + "\n")
        self.stream.flush()

    def write_log(self, snapshot: Snapshot) -> None:
        """追加单行日志到文件。"""
        if self.log_path is None:
            return
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(self.log_line(snapshot) + "\n")

    # ---------- 持续轮询 ----------

    def run(
        self,
        interval_seconds: float = 30.0,
        max_iterations: int | None = None,
        clear_screen: bool = True,
    ) -> None:
        """持续轮询。Ctrl+C 退出。

        - interval_seconds: 两次快照间隔
        - max_iterations: 限制轮询次数（测试用，None = 无限）
        - clear_screen: 每次清屏重绘
        """
        self._log(f"monitor started  interval={interval_seconds}s  "
                  f"log={self.log_path or '(none)'}")

        iteration = 0
        try:
            while True:
                iteration += 1
                try:
                    snap = self.snapshot_now()
                    self.print_snapshot(snap, clear_screen=clear_screen)
                    self.write_log(snap)

                    # 信号评估
                    if self.alerter is not None:
                        signals = self.alerter.evaluate(snap)
                        if signals:
                            self.stream.write("\n")
                            self.stream.write(self.alerter.format_signals(signals))
                            self.stream.write("\n")
                            self.stream.flush()
                            self.alerter.write_signals_log(signals)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self._log(f"snapshot #{self._snapshot_id} failed: {e!r}")

                if max_iterations is not None and iteration >= max_iterations:
                    self._log(f"max_iterations={max_iterations} reached, exit")
                    break

                try:
                    time.sleep(interval_seconds)
                except KeyboardInterrupt:
                    self._log("monitor interrupted, exit")
                    break
        except KeyboardInterrupt:
            self._log("monitor interrupted, exit")

    def _log(self, msg: str) -> None:
        """非快照状态日志（如启动/退出/异常）。"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        self.stream.write(line + "\n")
        self.stream.flush()
        if self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
