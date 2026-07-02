#!/usr/bin/env -S uv run python
"""端到端冒烟脚本：通过 MarketDataAdapter 统一接口拉所有数据，输出样例。

用法：
    uv run python scripts/smoke_market_data.py [STOCK_CODE]...
    默认拉 600519（茅台）、000001（平安）、300750（宁德）
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta

from mommy_chaogu.market_data import (
    BarInterval,
    EfinanceAdapter,
    Quote,
    filter_by_market,
)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def show_quote(q: Quote) -> None:
    print(
        f"  {q.code} {q.name:<10} "
        f"价 {q.price:>8}  "
        f"涨跌 {q.change:>+7} ({q.change_pct:>+5.2f}%)  "
        f"量 {q.volume:>12}  "
        f"额 {q.turnover.amount:>15}  "
        f"@{q.timestamp:%H:%M:%S}"
    )


def main() -> int:
    codes = sys.argv[1:] or ["600519", "000001", "300750"]
    adp = EfinanceAdapter()
    print(f"Adapter: {adp.name} | sample codes: {codes}")

    # 1. health check
    section("1. health_check")
    t0 = time.perf_counter()
    ok = adp.health_check()
    print(f"  health = {ok}  ({time.perf_counter() - t0:.2f}s)")

    # 2. 单股实时
    section("2. get_quote (单股实时)")
    for code in codes:
        t0 = time.perf_counter()
        q = adp.get_quote(code)
        dt = time.perf_counter() - t0
        if q is None:
            print(f"  {code} -> None  ({dt:.2f}s)")
        else:
            show_quote(q)
            print(
                f"    -> {dt:.2f}s, market={q.market.value}, "
                f"pe={q.pe_dynamic}, mcap={q.total_market_cap}"
            )

    # 3. 批量实时
    section("3. get_quotes (批量)")
    t0 = time.perf_counter()
    qs = adp.get_quotes(codes)
    print(f"  got {len(qs)}/{len(codes)} quotes in {time.perf_counter() - t0:.2f}s")
    for q in qs:
        show_quote(q)

    # 4. 全市场 + 市场过滤
    section("4. list_market_quotes + filter_by_market")
    t0 = time.perf_counter()
    all_qs = adp.list_market_quotes()
    print(f"  total = {len(all_qs)}  ({time.perf_counter() - t0:.2f}s)")
    sh_qs = filter_by_market(all_qs, ["SH"])
    sz_qs = filter_by_market(all_qs, ["SZ"])
    bj_qs = filter_by_market(all_qs, ["BJ"])
    print(f"  沪A: {len(sh_qs)}, 深A: {len(sz_qs)}, 京A: {len(bj_qs)}")
    # 涨跌幅 Top 5
    top5 = sorted(all_qs, key=lambda x: x.change_pct, reverse=True)[:5]
    print("  涨幅榜 Top 5:")
    for q in top5:
        show_quote(q)
    bot5 = sorted(all_qs, key=lambda x: x.change_pct)[:5]
    print("  跌幅榜 Top 5:")
    for q in bot5:
        show_quote(q)

    # 5. 5 档盘口
    section("5. get_order_book (5档盘口)")
    for code in codes[:1]:
        ob = adp.get_order_book(code)
        if ob is None:
            print(f"  {code}: no order book")
            continue
        print(f"  {ob.code} {ob.name}  spread={ob.spread}")
        print("    买: " + " | ".join(f"{lvl.price}×{lvl.volume}" for lvl in ob.bids))
        print("    卖: " + " | ".join(f"{lvl.price}×{lvl.volume}" for lvl in ob.asks))

    # 6. K 线 - 日 / 周 / 月 / 60分
    section("6. get_bars (K线)")
    code = codes[0]
    for iv in [BarInterval.D1, BarInterval.W1, BarInterval.M, BarInterval.M60, BarInterval.M5]:
        bars = adp.get_bars(code, interval=iv, limit=3)
        print(f"  {code} {iv.value}: {len(bars)} bars (last 3)")
        for b in bars[-3:]:
            print(
                f"    {b.timestamp:%Y-%m-%d %H:%M}  "
                f"O {b.open}  H {b.high}  L {b.low}  C {b.close}  "
                f"V {b.volume}  {b.change_pct:+.2f}%"
            )

    # 7. K 线区间 + 复权
    section("7. get_bars (区间 + 复权)")
    end = date.today()
    start = end - timedelta(days=14)
    bars = adp.get_bars(code, interval=BarInterval.D1, start=start, end=end)
    print(f"  {code} 日K  {start} ~ {end}: {len(bars)} bars")

    # 8. Tick 成交明细
    section("8. get_ticks (成交明细)")
    ticks = adp.get_ticks(code, limit=5)
    print(f"  {code}: first 5 ticks of today")
    for t in ticks:
        print(f"    {t.timestamp:%H:%M:%S}  {t.price} × {t.volume} (单数={t.trade_count})")

    # 9. 当日资金流
    section("9. get_today_money_flow (当日资金流)")
    flows = adp.get_today_money_flow(code)
    print(f"  {code}: {len(flows)} time points today, latest 3:")
    for f in flows[-3:]:
        print(
            f"    {f.timestamp:%H:%M}  "
            f"主力 {f.main_net.amount:+,.0f}  "
            f"超大 {f.super_large_net.amount:+,.0f}  "
            f"大 {f.large_net.amount:+,.0f}  "
            f"中 {f.medium_net.amount:+,.0f}  "
            f"小 {f.small_net.amount:+,.0f}"
        )

    # 10. 历史资金流
    section("10. get_history_money_flow (30天)")
    hflows = adp.get_history_money_flow(code, days=30)
    print(f"  {code}: {len(hflows)} days, last 5:")
    for f in hflows[-5:]:
        print(
            f"    {f.timestamp:%Y-%m-%d}  主力 {f.main_net.amount:+,.0f} ({f.main_net_ratio:+.2f}%)"
        )

    # 11. 板块
    section("11. get_belonging_boards (所属板块)")
    boards = adp.get_belonging_boards(code)
    print(f"  {code} 属于 {len(boards)} 个板块:")
    for b in boards[:10]:
        pct = f"{b.change_pct:+.2f}%" if b.change_pct is not None else "—"
        print(f"    {b.code}  {b.name:<14}  {pct}")

    print()
    print("✅ all smoke checks done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
