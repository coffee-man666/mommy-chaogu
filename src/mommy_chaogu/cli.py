"""CLI 入口：watchlist / monitor 命令。

注册方式（在 pyproject.toml 里）：
    [project.scripts]
    mommy-watchlist = "mommy_chaogu.cli:main_watchlist"
    mommy-monitor = "mommy_chaogu.cli:main_monitor"

用法示例：
    mommy-watchlist add-group 白酒 --description "白酒板块"
    mommy-watchlist add 600519 --group 白酒 --note "妈妈长期持有"
    mommy-watchlist list
    mommy-watchlist list --by-group
    mommy-watchlist remove 600519 --group 白酒
    mommy-watchlist groups
    mommy-watchlist stats

    mommy-monitor snapshot
    mommy-monitor run --interval 30
    mommy-monitor log --tail 20
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from mommy_chaogu.market_data import EfinanceAdapter
from mommy_chaogu.monitor import Monitor
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.watchlist.store import (
    GroupAlreadyExistsError,
    GroupNotFoundError,
    StockEntryNotFoundError,
)

# ---------- 默认路径 ----------

DEFAULT_DB_PATH = Path("data/watchlist.db")
DEFAULT_LOG_PATH = Path("data/monitor.log")
DEFAULT_SIGNALS_LOG_PATH = Path("data/signals.log")
DEFAULT_CACHE_DB_PATH = Path("data/watchlist.db")  # cache 与 watchlist 共用一份 db


# ---------- 共用 ----------

def _store(args: argparse.Namespace) -> WatchlistStore:
    return WatchlistStore(Path(args.db))


# ============================================================
# watchlist 子命令
# ============================================================

def cmd_watchlist_add_group(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        g = s.add_group(args.name, description=args.description)
    except GroupAlreadyExistsError as e:
        print(f"⚠️  {e}")
        return 1
    print(f"✅ 已创建分组 {g.name!r} (id={g.id})")
    return 0


def cmd_watchlist_remove_group(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        s.remove_group(args.name)
    except GroupNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"🗑️  已删除分组 {args.name!r}")
    return 0


def cmd_watchlist_groups(args: argparse.Namespace) -> int:
    s = _store(args)
    rows = s.list_groups()
    if not rows:
        print("（暂无分组）")
        return 0
    print(f"{'分组':<16} {'描述':<30} {'股票数':>6}")
    print("─" * 56)
    for g, n in rows:
        desc = (g.description or "")[:28]
        print(f"{g.name:<16} {desc:<30} {n:>6}")
    return 0


def cmd_watchlist_add(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        entry = s.add_entry(args.code, args.group, note=args.note)
    except GroupNotFoundError as e:
        print(f"❌ {e}")
        return 1
    # 顺手拉一下名字回填
    if entry.name is None:
        try:
            adp = EfinanceAdapter()
            q = adp.get_quote(args.code)
            if q:
                s.backfill_name(args.code, q.name)
                refreshed = s.list_entries(group_name=args.group)
                match = next((e for e in refreshed if e.code == args.code), None)
                if match is not None:
                    entry = match
        except Exception:
            pass
    name = entry.name or "(名称待回填)"
    note = f"  # {entry.note}" if entry.note else ""
    print(f"✅ 已添加 {args.code} {name} 到分组 {args.group!r}{note}")
    return 0


def cmd_watchlist_remove(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        s.remove_entry(args.code, args.group)
    except GroupNotFoundError as e:
        print(f"❌ {e}")
        return 1
    except StockEntryNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"🗑️  已删除 {args.code} (从 {args.group!r})")
    return 0


def cmd_watchlist_list(args: argparse.Namespace) -> int:
    s = _store(args)
    if args.by_group:
        by_group = s.list_entries_by_group()
        if not by_group:
            print("（暂无自选股）")
            return 0
        for group_name, entries in by_group.items():
            print(f"\n📁 {group_name} ({len(entries)})")
            if not entries:
                print("   (empty)")
                continue
            for e in entries:
                name = e.name or "—"
                note = f"  # {e.note}" if e.note else ""
                print(f"   {e.code:<8} {name:<10}{note}")
        return 0

    entries = s.list_entries()
    if not entries:
        print("（暂无自选股，先 watchlist add）")
        return 0
    print(f"{'代码':<8} {'名称':<10} {'分组':<12} {'备注':<30}")
    print("─" * 64)
    for e in entries:
        name = e.name or "—"
        note = (e.note or "")[:28]
        print(f"{e.code:<8} {name:<10} {e.group.name:<12} {note:<30}")
    return 0


def cmd_watchlist_stats(args: argparse.Namespace) -> int:
    s = _store(args)
    st = s.stats()
    print(
        f"分组数: {st['groups']}  "
        f"自选股条目: {st['entries']}  "
        f"去重股票数: {st['codes']}"
    )
    return 0


def build_watchlist_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-watchlist",
        description="妈妈炒股 - 自选股池管理",
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})")

    sub = p.add_subparsers(dest="cmd", required=True)

    # add-group
    p_ag = sub.add_parser("add-group", help="新建分组")
    p_ag.add_argument("name", help="分组名（中文/英文）")
    p_ag.add_argument("--description", "-d", help="分组描述")
    p_ag.set_defaults(func=cmd_watchlist_add_group)

    # remove-group
    p_rg = sub.add_parser("remove-group", help="删除分组（连带删自选股）")
    p_rg.add_argument("name", help="分组名")
    p_rg.set_defaults(func=cmd_watchlist_remove_group)

    # groups
    p_g = sub.add_parser("groups", help="列出所有分组")
    p_g.set_defaults(func=cmd_watchlist_groups)

    # add
    p_a = sub.add_parser("add", help="添加自选股")
    p_a.add_argument("code", help="股票代码（如 600519）")
    p_a.add_argument("--group", "-g", required=True, help="所属分组")
    p_a.add_argument("--note", "-n", help="备注")
    p_a.set_defaults(func=cmd_watchlist_add)

    # remove
    p_r = sub.add_parser("remove", help="删除自选股")
    p_r.add_argument("code", help="股票代码")
    p_r.add_argument("--group", "-g", required=True, help="所属分组")
    p_r.set_defaults(func=cmd_watchlist_remove)

    # list
    p_l = sub.add_parser("list", help="列出自选股")
    p_l.add_argument("--by-group", "-G", action="store_true", help="按分组显示")
    p_l.set_defaults(func=cmd_watchlist_list)

    # stats
    p_s = sub.add_parser("stats", help="汇总统计")
    p_s.set_defaults(func=cmd_watchlist_stats)

    return p


def main_watchlist() -> NoReturn:
    parser = build_watchlist_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)


# ============================================================
# monitor 子命令
# ============================================================

def _make_adapter(args: argparse.Namespace) -> object:
    """构造 adapter，默认用 fallback + 缓存包装。

    顺序：EfinanceAdapter (主) → TencentAdapter (fallback) → CachedMarketDataAdapter (外层)
    东财接口挂了 → 自动降级到腾讯财经（数据稳定）
    """
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    store = CacheStore(Path(args.db))
    return CachedMarketDataAdapter(base, store)


def cmd_monitor_snapshot(args: argparse.Namespace) -> int:
    s = _store(args)
    adp = _make_adapter(args)
    log_path = Path(args.log) if args.log else None
    signals_log_path = Path(args.signals_log) if args.signals_log else None
    m = Monitor(s, adp, log_path=log_path)  # type: ignore[arg-type]
    snap = m.snapshot_now()
    m.print_snapshot(snap, clear_screen=False)
    m.write_log(snap)

    # 信号评估
    if args.with_signals:
        alerter = Alerter.default(log_path=signals_log_path)
        signals = alerter.evaluate(snap)
        print()
        print(alerter.format_signals(signals))
        alerter.write_signals_log(signals)
    return 0


def cmd_monitor_run(args: argparse.Namespace) -> int:
    s = _store(args)
    adp = _make_adapter(args)
    log_path = Path(args.log) if args.log else None
    signals_log_path = Path(args.signals_log) if args.signals_log else None
    m = Monitor(s, adp, log_path=log_path, alerter=Alerter.default(log_path=signals_log_path) if args.with_signals else None)  # type: ignore[arg-type]
    m.run(
        interval_seconds=args.interval,
        max_iterations=args.max_iterations,
        clear_screen=not args.no_clear,
    )
    return 0


def cmd_monitor_log(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"日志文件不存在: {log_path}")
        return 1
    # 简单 tail：读最后 N 行
    with log_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = lines[-args.tail:] if args.tail > 0 else lines
    print("".join(tail), end="")
    if not tail or not tail[-1].endswith("\n"):
        print()
    return 0


def cmd_monitor_signals(args: argparse.Namespace) -> int:
    """查看 signals.log 历史信号。"""
    log_path = Path(args.signals_log)
    if not log_path.exists():
        print(f"信号日志文件不存在: {log_path}")
        return 1
    with log_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = lines[-args.tail:] if args.tail > 0 else lines
    print(f"📡 信号日志 (最后 {len(tail)} 条):")
    print("─" * 60)
    print("".join(tail), end="")
    if not tail or not tail[-1].endswith("\n"):
        print()
    return 0


def cmd_monitor_rules(_args: argparse.Namespace) -> int:
    """列出所有内置规则 + 默认配置。"""
    from mommy_chaogu.signals.rules import RULES_REGISTRY  # noqa: F401
    print("📐 内置告警规则")
    print("=" * 70)
    print(f"{'rule_id':<28} {'enabled':<8} {'severity':<10} {'params'}")
    print("─" * 70)
    from mommy_chaogu.signals.rules import default_rules
    for rule in default_rules():
        cfg = rule.config
        params_str = ", ".join(f"{k}={v}" for k, v in cfg.params.items())
        if len(params_str) > 40:
            params_str = params_str[:37] + "..."
        print(f"{rule.rule_id:<28} {cfg.enabled!s:<8} "
              f"{cfg.severity.value:<10} {params_str}")
    print()
    print("💡 自定义阈值：在 pyproject 里配 / 或代码里 new RuleWithConfig(...)")
    return 0


def cmd_monitor_stats(args: argparse.Namespace) -> int:
    s = _store(args)
    adp = EfinanceAdapter()
    log_path = Path(args.log) if args.log else None
    m = Monitor(s, adp, log_path=log_path)  # type: ignore[arg-type]
    snap = m.snapshot_now()
    st = s.stats()
    print("=" * 50)
    print(f"  自选股池统计  @ {snap.timestamp:%Y-%m-%d %H:%M:%S}")
    print("=" * 50)
    print(f"  分组数: {st['groups']}")
    print(f"  自选股条目: {st['entries']}")
    print(f"  去重股票数: {st['codes']}")
    print(f"  本次抓到行情: {snap.n_codes}")
    print(f"  ↑{snap.n_up}  ↓{snap.n_down}  —{snap.n_flat}")
    print(f"  主力净流入合计: {snap.total_main_net:+.2f} 元")
    return 0


def build_monitor_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-monitor",
        description="妈妈炒股 - 自选股监控",
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})")
    p.add_argument("--log", default=str(DEFAULT_LOG_PATH), help=f"日志路径 (默认 {DEFAULT_LOG_PATH})")
    p.add_argument("--signals-log", default=str(DEFAULT_SIGNALS_LOG_PATH),
                   help=f"信号日志路径 (默认 {DEFAULT_SIGNALS_LOG_PATH})")

    sub = p.add_subparsers(dest="cmd", required=True)

    # snapshot
    p_s = sub.add_parser("snapshot", help="拉一次快照并打印")
    p_s.add_argument("--with-signals", "-S", action="store_true", help="同时评估告警信号")
    p_s.set_defaults(func=cmd_monitor_snapshot)

    # run
    p_r = sub.add_parser("run", help="持续轮询 (Ctrl+C 退出)")
    p_r.add_argument("--interval", "-i", type=float, default=30.0, help="轮询间隔秒 (默认 30)")
    p_r.add_argument("--max-iterations", "-n", type=int, default=None, help="最大轮询次数")
    p_r.add_argument("--no-clear", action="store_true", help="不清屏，追加输出")
    p_r.add_argument("--with-signals", "-S", action="store_true", help="同时评估告警信号")
    p_r.set_defaults(func=cmd_monitor_run)

    # log
    p_l = sub.add_parser("log", help="查看监控日志（tail）")
    p_l.add_argument("--tail", "-n", type=int, default=20, help="最后 N 行 (默认 20)")
    p_l.set_defaults(func=cmd_monitor_log)

    # signals
    p_sig = sub.add_parser("signals", help="查看信号日志（tail）")
    p_sig.add_argument("--tail", "-n", type=int, default=20, help="最后 N 行 (默认 20)")
    p_sig.set_defaults(func=cmd_monitor_signals)

    # rules
    p_rl = sub.add_parser("rules", help="列出所有内置告警规则")
    p_rl.set_defaults(func=cmd_monitor_rules)

    # stats
    p_st = sub.add_parser("stats", help="自选池 + 快照汇总")
    p_st.set_defaults(func=cmd_monitor_stats)

    return p


def main_monitor() -> NoReturn:
    parser = build_monitor_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)


# ============================================================
# 顶级命令 mommy-chaogu
# ============================================================

def main() -> int:
    """顶级入口（mommy-chaogu）。"""
    p = argparse.ArgumentParser(
        prog="mommy-chaogu",
        description="妈妈炒股 - 行情监控 / 投资陪伴",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("watchlist", help="自选股池管理").set_defaults(
        func=lambda _: _dispatch_subcommand(build_watchlist_parser(), "mommy-watchlist")
    )
    sub.add_parser("monitor", help="行情监控").set_defaults(
        func=lambda _: _dispatch_subcommand(build_monitor_parser(), "mommy-monitor")
    )
    sub.add_parser("cache", help="行情缓存管理").set_defaults(
        func=lambda _: _dispatch_subcommand(build_cache_parser(), "mommy-cache")
    )

    args = p.parse_args()
    rc = args.func(args)
    return int(rc) if rc is not None else 0


def _dispatch_subcommand(parser: argparse.ArgumentParser, prog: str) -> int:
    """把 mommy-chaogu watchlist [args...] 转发到 watchlist parser。"""
    # argparse 已经吃过顶层 cmd，剩下的 sys.argv 重新解析
    parser.prog = prog
    args = parser.parse_args(sys.argv[2:])
    rc = args.func(args)
    return int(rc) if rc is not None else 0


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
    print(f"  quote_fetch_interval_seconds:             {cfg.quote_fetch_interval_seconds} 秒 ({cfg.quote_fetch_interval_seconds // 60} 分钟)")
    print(f"  today_money_flow_fetch_interval_seconds:  {cfg.today_money_flow_fetch_interval_seconds} 秒")
    print(f"  market_snapshot_fetch_interval_seconds:   {cfg.market_snapshot_fetch_interval_seconds} 秒 ({cfg.market_snapshot_fetch_interval_seconds // 3600} 小时)")
    print(f"  bar_fetch_interval_seconds:               {cfg.bar_fetch_interval_seconds} 秒 (1 天)")
    print(f"  money_flow_history_fetch_interval_seconds:{cfg.money_flow_history_fetch_interval_seconds} 秒")
    print(f"  market_snapshot_history_keep:             {cfg.market_snapshot_history_keep} 份")
    return 0


def build_cache_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-cache",
        description="妈妈炒股 - 行情缓存管理",
    )
    p.add_argument("--db", default=str(DEFAULT_CACHE_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_CACHE_DB_PATH})")

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


# ============================================================
# web 子命令
# ============================================================

def build_web_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-web",
        description="妈妈炒股 - Web 后端服务（FastAPI + WebSocket）",
    )
    p.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="监听端口 (默认 8000)")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})")
    p.add_argument("--poll-interval", type=float, default=5.0, help="后台轮询间隔（秒）(默认 5)")
    p.add_argument(
        "--server-chan-key",
        default=os.environ.get("SERVER_CHAN_KEY", ""),
        help="Server酱 SendKey（启用微信推送，默认读 $SERVER_CHAN_KEY）",
    )
    p.add_argument(
        "--web-base-url",
        default=os.environ.get("WEB_BASE_URL", ""),
        help="Web 前端的公网/HTTPS URL（推送消息里带 K 线链接用）",
    )
    p.add_argument("--reload", action="store_true", help="开发模式热重载")
    p.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return p


def cmd_web_serve(args: argparse.Namespace) -> int:
    """启动 Web 服务。"""
    import uvicorn

    from mommy_chaogu.web import create_app

    app = create_app(
        db_path=Path(args.db),
        poll_interval_seconds=args.poll_interval,
        server_chan_key=args.server_chan_key or None,
        web_base_url=args.web_base_url,
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def main_web() -> NoReturn:
    parser = build_web_parser()
    args = parser.parse_args()
    sys.exit(cmd_web_serve(args))


if __name__ == "__main__":
    main()
