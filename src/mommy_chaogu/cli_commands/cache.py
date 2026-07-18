"""cache command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# cache 子命令
# ============================================================


def _cache_manager(args: argparse.Namespace) -> object:
    from mommy_chaogu.cache import CacheManager

    return CacheManager.default(Path(args.db))


def cmd_cache_stats(args: argparse.Namespace) -> int:
    m = _cache_manager(args)
    st = m.stats()
    print("📊 缓存统计")
    print("─" * 60)
    print(f"  自选报价缓存: {st['quotes']} 条")
    print(f"  K线缓存:      {st['bars']} 条")
    print(f"  当日资金流:   {st['flows_today']} 条")
    print(f"  历史资金流:   {st['flows_history']} 条")
    print(f"  全市场快照:   {st['snapshots']} 份")
    print()
    print("💡 拉新统计:")
    print(f"  缓存命中: {st['hits']} 次")
    print(f"  拉新请求: {st['fetches']} 次 (成功 {st['fetch_ok']} / 失败 {st['fetch_fail']})")
    print(f"  完全 miss: {st['miss']} 次")
    if st["fetches"] > 0:
        hit_rate = st["hits"] / (st["hits"] + st["fetches"]) * 100
        print(f"  命中率: {hit_rate:.1f}%")
    print()
    print(m.format_freshness())
    return 0


def cmd_cache_warmup(args: argparse.Namespace) -> int:
    from mommy_chaogu.watchlist import WatchlistStore

    s = WatchlistStore(Path(args.db))
    m = _cache_manager(args)
    print("🔥 预热全市场快照...")
    r = m.warmup_market()
    print(f"  ✅ 全市场: {r['n_quotes']} 只")
    codes = s.get_all_codes()
    if codes:
        print(f"🔥 预热自选股报价 ({len(codes)} 只)...")
        r = m.warmup_codes(codes)
        print(f"  ✅ 报价: {r['quotes_fetched']} 成功 / {r['quotes_failed']} 失败")
    return 0


def cmd_cache_refresh(args: argparse.Namespace) -> int:
    m = _cache_manager(args)
    if args.code:
        print(f"🔄 刷新单股 {args.code}...")
        ok = m.refresh_quote(args.code)
        print(f"  {'✅ 成功' if ok else '❌ 失败'}")
        return 0 if ok else 1
    print("🔄 刷新全市场...")
    n = m.refresh_market()
    print(f"  ✅ 全市场: {n} 只")
    return 0


def cmd_cache_clear(args: argparse.Namespace) -> int:
    from mommy_chaogu.cache import CacheStore

    s = CacheStore(Path(args.db))
    if args.all:
        s.clear_all()
        print("✅ 已清空所有缓存")
    else:
        n = s.clear_quotes()
        print(f"✅ 已清空 {n} 条 quote_cache")
    return 0


def cmd_cache_snapshots(args: argparse.Namespace) -> int:
    from mommy_chaogu.cache import CacheStore

    s = CacheStore(Path(args.db))
    rows = s.list_market_snapshots(limit=args.limit)
    if not rows:
        print("（无全市场快照，先 mommy-cache warmup）")
        return 0
    print(f"📂 全市场快照（最近 {len(rows)} 份）")
    print("─" * 70)
    print(f"{'ID':<5} {'拉取时间':<20} {'行情时间':<20} {'股票数':>8}")
    for r in rows:
        fetched = r["fetched_at"].strftime("%Y-%m-%d %H:%M:%S") if r["fetched_at"] else "—"
        quote_ts = r["quote_ts"].strftime("%Y-%m-%d %H:%M:%S") if r["quote_ts"] else "—"
        print(f"{r['id']:<5} {fetched:<20} {quote_ts:<20} {r['n_codes']:>8}")
    return 0


def cmd_cache_config(_args: argparse.Namespace) -> int:
    from mommy_chaogu.cache import default_config

    cfg = default_config()
    print("⚙️ 缓存拉新间隔配置（默认值）")
    print("─" * 60)
    print(
        f"  quote_fetch_interval_seconds:             {cfg.quote_fetch_interval_seconds} 秒 ({cfg.quote_fetch_interval_seconds // 60} 分钟)"
    )
    print(
        f"  today_money_flow_fetch_interval_seconds:  {cfg.today_money_flow_fetch_interval_seconds} 秒"
    )
    print(
        f"  market_snapshot_fetch_interval_seconds:   {cfg.market_snapshot_fetch_interval_seconds} 秒 ({cfg.market_snapshot_fetch_interval_seconds // 3600} 小时)"
    )
    print(f"  bar_fetch_interval_seconds:               {cfg.bar_fetch_interval_seconds} 秒 (1 天)")
    print(
        f"  money_flow_history_fetch_interval_seconds:{cfg.money_flow_history_fetch_interval_seconds} 秒"
    )
    print(f"  market_snapshot_history_keep:             {cfg.market_snapshot_history_keep} 份")
    return 0


def build_cache_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-cache",
        description="妈妈炒股 - 行情缓存管理",
        epilog=(
            "example:\n"
            "  mommy cache warmup\n"
            "  mommy cache refresh --code 600519\n"
            "  mommy cache stats"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db",
        default=str(DEFAULT_CACHE_DB_PATH),
        help=f"数据库路径 (默认 {DEFAULT_CACHE_DB_PATH})",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="缓存统计 + 数据新鲜度").set_defaults(func=cmd_cache_stats)
    sub.add_parser("warmup", help="盘前预热（全市场 + 自选股）").set_defaults(func=cmd_cache_warmup)

    p_r = sub.add_parser("refresh", help="强制刷新（跳过缓存节流）")
    p_r.add_argument("--code", help="刷新单股，不填则刷全市场")
    p_r.set_defaults(func=cmd_cache_refresh)

    p_c = sub.add_parser("clear", help="清空缓存")
    p_c.add_argument("--all", action="store_true", help="清空所有缓存表（不只是 quote_cache）")
    p_c.set_defaults(func=cmd_cache_clear)

    p_s = sub.add_parser("snapshots", help="列出全市场快照历史")
    p_s.add_argument("--limit", "-n", type=int, default=30, help="最多显示 N 份 (默认 30)")
    p_s.set_defaults(func=cmd_cache_snapshots)

    sub.add_parser("config", help="查看拉新间隔配置").set_defaults(func=cmd_cache_config)

    return p


def main_cache() -> NoReturn:
    parser = build_cache_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
