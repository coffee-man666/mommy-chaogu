#!/usr/bin/env -S uv run python
"""演示信号触发（用 mock 数据，不依赖外部网络）。

展示规则触发效果，便于调试 / 给妈妈演示。
"""
from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal

from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)
from mommy_chaogu.monitor import Snapshot, SnapshotRow
from mommy_chaogu.signals import Alerter


def mk_quote(code: str, price: str, pct: str, **kw: object) -> Quote:
    return Quote(
        code=code,
        name=f"名称{code}",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal(price),
        open=Decimal(str(kw.get("open", price))),
        high=Decimal(price),
        low=Decimal(price),
        prev_close=Decimal(str(kw.get("prev_close", price))),
        change=Decimal("0"),
        change_pct=Decimal(pct),
        volume=100000,
        turnover=Money.from_yuan(100000000),
        turnover_rate=Decimal(str(kw["turnover_rate"])) if kw.get("turnover_rate") else None,
        volume_ratio=Decimal(str(kw["volume_ratio"])) if kw.get("volume_ratio") else None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime.now(),
    )


def mk_flow(code: str, main_yuan: float) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=f"名称{code}",
        timestamp=datetime.now(),
        main_net=Money.from_yuan(main_yuan),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(0),
        super_large_net=Money.from_yuan(0),
    )


def main() -> int:
    # 模拟场景：4 只自选股 + 1 只跳空
    rows = [
        SnapshotRow(
            entry=None, group_name="白酒",
            quote=mk_quote("600519", "1300", "+6.5", volume_ratio="2.8"),
            latest_flow=mk_flow("600519", 350_000_000),
        ),
        SnapshotRow(
            entry=None, group_name="白酒",
            quote=mk_quote("000858", "78", "-4.2", turnover_rate="5.5"),
            latest_flow=mk_flow("000858", -180_000_000),
        ),
        SnapshotRow(
            entry=None, group_name="银行",
            quote=mk_quote("000001", "10.5", "+0.5"),
            latest_flow=mk_flow("000001", 30_000_000),
        ),
        SnapshotRow(
            entry=None, group_name="银行",
            quote=mk_quote("600036", "36", "+1.2"),
            latest_flow=mk_flow("600036", 50_000_000),
        ),
        SnapshotRow(
            entry=None, group_name="新能源",
            quote=mk_quote("300750", "400", "-2.8", open="385", prev_close="380"),
            latest_flow=mk_flow("300750", -250_000_000),
        ),
    ]
    snap = Snapshot.build(rows, snapshot_id=99)

    alerter = Alerter.default()
    signals = alerter.evaluate(snap)

    print(f"📊 自选股快照（mock）")
    print(f"   {snap.n_codes} 只 | ↑{snap.n_up} ↓{snap.n_down} —{snap.n_flat}")
    print(f"   主力合计 {float(snap.total_main_net) / 1e8:+.2f}亿\n")

    print(f"🚨 触发信号 {len(signals)} 条：")
    print("─" * 70)
    for s in signals:
        print(s.format())
    return 0


if __name__ == "__main__":
    sys.exit(main())
