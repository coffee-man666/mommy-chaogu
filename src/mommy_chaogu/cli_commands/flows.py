"""flows command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# flows 子命令
# ============================================================


def _flows_resolve_pool(args: argparse.Namespace) -> object:
    """根据 --pool / --codes 构造 PoolSource。"""
    from mommy_chaogu.flows.pool import build_pool

    pool_db = Path(args.semicon_db) if args.pool == "semicon" else Path(args.db)
    return build_pool(
        name=args.pool,
        db_path=pool_db,
        custom_codes=args.codes,
    )


def _flows_service(args: argparse.Namespace) -> object:
    from mommy_chaogu.flows.service import FlowService

    return FlowService.from_default(Path(args.db), use_fallback=not args.no_fallback)


def _format_yi(amount) -> str:
    """把元 转成 亿元（保留 2 位小数）。"""
    from decimal import Decimal

    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    yi = amount / Decimal("100000000")
    sign = "+" if yi > 0 else ""
    return f"{sign}{yi:.2f}亿"


def _format_wan(amount) -> str:
    """把元 转成 万元（保留 0 位）。"""
    from decimal import Decimal

    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    wan = amount / Decimal("10000")
    sign = "+" if wan > 0 else ""
    return f"{sign}{wan:.0f}万"


def cmd_flows_pull(args: argparse.Namespace) -> int:
    pool = _flows_resolve_pool(args)
    service = _flows_service(args)
    print(f"📥 拉 {pool.describe()} 的资金流（force={args.force}）")
    print("─" * 70)

    if args.target in ("today", "all"):
        r = service.pull_today(pool, force=args.force)
        print(f"  当日:  ✅ {r.ok}  ❌ {r.failed}  ⏱ {r.elapsed_seconds:.1f}s")
        if r.failed_codes:
            print(
                f"    失败 codes: {r.failed_codes[:10]}{'...' if len(r.failed_codes) > 10 else ''}"
            )
    if args.target in ("history", "all"):
        r = service.pull_history(pool, days=args.days, force=args.force)
        print(f"  历史({args.days}d): ✅ {r.ok}  ❌ {r.failed}  ⏱ {r.elapsed_seconds:.1f}s")
        if r.failed_codes:
            print(
                f"    失败 codes: {r.failed_codes[:10]}{'...' if len(r.failed_codes) > 10 else ''}"
            )
    return 0


def cmd_flows_top(args: argparse.Namespace) -> int:
    pool = _flows_resolve_pool(args)
    service = _flows_service(args)

    if args.period == "today":
        rows = service.top_today(pool, n=args.n, by=args.by, direction=args.direction)
        period_label = "当日"
    else:
        rows = service.top_history(
            pool, days=args.days, n=args.n, by=args.by, direction=args.direction
        )
        period_label = f"近{args.days}日累计"

    direction_label = "净流入" if args.direction == "in" else "净流出"
    by_label = "主力净" if args.by == "main_net" else "大资金净(超大+大)"
    print(f"🏆 {pool.name} · {period_label} · 按{by_label} · {direction_label} TOP {args.n}")
    print("─" * 90)
    if not rows:
        print("（无数据，先 mommy-flows pull）")
        return 0
    print(f"{'代码':<8} {'名称':<10} {'主力净':<14} {'大资金净':<14} {'样本':<6} 期间")
    print("─" * 90)
    for s in rows:
        print(
            f"{s.code:<8} {s.name[:10]:<10} "
            f"{_format_yi(s.main_net):<14} "
            f"{_format_yi(s.big_money_net()):<14} "
            f"{s.sample_count:<6} {s.period}"
        )
    return 0


def cmd_flows_show(args: argparse.Namespace) -> int:
    service = _flows_service(args)
    info = service.show(args.code, days=args.days)
    print(f"🔍 {args.code} 资金流汇总")
    print("─" * 60)
    today = info.get("today")
    if today:
        print("📌 当日（最新快照）:")
        print(f"   主力净:   {_format_yi(today.main_net)}")
        print(
            f"   大资金净: {_format_yi(today.big_money_net())}  "
            f"(超大 {_format_yi(today.super_large_net)} + 大单 {_format_yi(today.large_net)})"
        )
        print(f"   中单净:   {_format_yi(today.medium_net)}")
        print(f"   小单净:   {_format_yi(today.small_net)}")
        if today.main_net_ratio is not None:
            print(f"   主力占比: {today.main_net_ratio}%")
        print(f"   采样数:   {today.sample_count}")
    else:
        print("📌 当日: (无缓存)")
    history = info.get("history")
    n_days = info.get("history_days_cached", 0)
    print()
    print(f"📜 近 {args.days} 日历史 (缓存 {n_days} 天):")
    if history and n_days > 0:
        print(f"   主力净累计:   {_format_yi(history.main_net)}")
        print(f"   大资金净累计: {_format_yi(history.big_money_net())}")
        print(f"   中单净累计:   {_format_yi(history.medium_net)}")
        print(f"   小单净累计:   {_format_yi(history.small_net)}")
    else:
        print("   (无历史缓存)")
    return 0


def cmd_flows_stats(args: argparse.Namespace) -> int:
    pool = _flows_resolve_pool(args)
    service = _flows_service(args)
    st = service.stats(pool)
    print(f"📊 {pool.describe()} 资金流缓存覆盖度")
    print("─" * 60)
    print(f"  池子总股数: {st['pool_total']}")
    print(f"  当日已缓存: {st['today_cached']} ({_pct(st['today_cached'], st['pool_total'])})")
    print(f"  历史已缓存: {st['history_cached']} ({_pct(st['history_cached'], st['pool_total'])})")
    return 0


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{n / total * 100:.0f}%"


def cmd_flows_clear(args: argparse.Namespace) -> int:
    pool = _flows_resolve_pool(args)
    service = _flows_service(args)
    if not args.yes:
        resp = input(f"确认清空 {pool.name} 池子的 today + history 资金流缓存？[y/N] ")
        if resp.lower() != "y":
            print("已取消")
            return 0
    r = service.clear(pool)
    print(f"✅ 已清空: 当日 {r['today_deleted']} 条 + 历史 {r['history_deleted']} 条")
    return 0


def cmd_flows_run(args: argparse.Namespace) -> int:
    """持续轮询 + ratio-based 异动检测。"""
    from mommy_chaogu.flows import FlowMonitor

    pool = _flows_resolve_pool(args)
    service = _flows_service(args)
    log_path = Path(args.log) if args.log else None
    state_path = Path(args.state) if args.state else None
    monitor = FlowMonitor(
        pool=pool,
        service=service,
        interval_seconds=args.interval,
        log_path=log_path,
        state_path=state_path,
    )
    print(f"🚀 启动资金流监控 · {pool.describe()}")
    print(f"   轮询间隔: {args.interval}s   日志: {log_path or '(stdout only)'}")
    print(f"   状态文件: {state_path or '(in-memory only)'}")
    print("   Ctrl+C 优雅退出")
    print("─" * 70)
    n = monitor.run(max_iterations=args.max_iterations, max_seconds=args.max_seconds)
    print(f"\n[monitor] 完成 {n} 轮迭代")
    return 0


def cmd_flows_report(args: argparse.Namespace) -> int:
    """生成收盘日报（markdown）。"""
    from datetime import date as _date

    from mommy_chaogu.flows import FlowReport

    pool = _flows_resolve_pool(args)
    service = _flows_service(args)
    reporter = FlowReport(service)
    day = _date.fromisoformat(args.day) if args.day else _date.today()
    output = (
        Path(args.output)
        if args.output
        else (Path(args.report_dir) / f"flows_report_{day.isoformat()}.md")
    )
    print(f"📝 生成 {pool.name} 资金流日报 · {day}")
    print(f"   输出: {output}")
    print("─" * 70)
    final = reporter.generate(
        pool=pool,
        day=day,
        history_days=args.history_days,
        output=output,
    )
    print(f"✅ 报告已生成: {final}")
    return 0


def build_flows_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-flows",
        description="妈妈炒股 - 资金流拉新 / 排行 / 监控（按股票池）",
        epilog=(
            "example:\n"
            "  mommy flows pull\n"
            "  mommy flows top --direction in\n"
            "  mommy flows run --interval 300"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # ---- 全局参数 ----
    p.add_argument(
        "--db",
        default=str(DEFAULT_FLOWS_DB_PATH),
        help=f"资金流缓存 db (默认 {DEFAULT_FLOWS_DB_PATH})",
    )
    p.add_argument(
        "--semicon-db",
        default=str(DEFAULT_FLOWS_SEMICON_DB_PATH),
        help=f"产业链 db (默认 {DEFAULT_FLOWS_SEMICON_DB_PATH})",
    )
    p.add_argument(
        "--pool",
        default="watchlist",
        choices=["watchlist", "semicon", "custom"],
        help="股票池 (默认 watchlist)",
    )
    p.add_argument("--codes", nargs="*", help="--pool custom 时手动指定 codes（空格分隔）")
    p.add_argument("--no-fallback", action="store_true", help="只用东财，不用腾讯兜底")

    sub = p.add_subparsers(dest="cmd", required=True)

    # pull
    p_p = sub.add_parser("pull", help="批量拉新到缓存（today 和/或 history）")
    p_p.add_argument(
        "--target", choices=["today", "history", "all"], default="all", help="拉哪种（默认 all）"
    )
    p_p.add_argument("--days", type=int, default=30, help="历史天数（默认 30）")
    p_p.add_argument("--force", action="store_true", help="绕过节流，强制重拉（用于首次 warmup）")
    p_p.set_defaults(func=cmd_flows_pull)

    # top
    p_t = sub.add_parser("top", help="按资金净流入/流出排行")
    p_t.add_argument(
        "--period", choices=["today", "history"], default="today", help="时间窗（默认 today）"
    )
    p_t.add_argument("--days", type=int, default=30, help="period=history 时的天数")
    p_t.add_argument("--n", type=int, default=20, help="取前 N (默认 20)")
    p_t.add_argument(
        "--by",
        choices=["main_net", "big_money"],
        default="main_net",
        help="排序指标（默认 主力净 = main_net）",
    )
    p_t.add_argument(
        "--direction", choices=["in", "out"], default="in", help="净流入 / 净流出（默认 in）"
    )
    p_t.set_defaults(func=cmd_flows_top)

    # show
    p_s = sub.add_parser("show", help="查单只股票的资金流汇总")
    p_s.add_argument("code", help="股票代码")
    p_s.add_argument("--days", type=int, default=30, help="历史聚合天数")
    p_s.set_defaults(func=cmd_flows_show)

    # stats
    sub.add_parser("stats", help="缓存覆盖度").set_defaults(func=cmd_flows_stats)

    # clear
    p_c = sub.add_parser("clear", help="清空某池子的 today + history 缓存")
    p_c.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    p_c.set_defaults(func=cmd_flows_clear)

    # run (持续监控)
    p_run = sub.add_parser("run", help="持续轮询 + ratio-based 异动检测（Ctrl+C 退出）")
    p_run.add_argument(
        "--interval", "-i", type=float, default=300.0, help="轮询间隔秒（默认 300 = 5 分钟）"
    )
    p_run.add_argument(
        "--max-iterations", "-n", type=int, default=None, help="最多跑 N 轮（默认无限）"
    )
    p_run.add_argument("--max-seconds", type=float, default=None, help="最多跑 N 秒（默认无限）")
    p_run.add_argument(
        "--log",
        default=str(DEFAULT_FLOWS_MONITOR_LOG_PATH),
        help=f"信号日志路径 (默认 {DEFAULT_FLOWS_MONITOR_LOG_PATH})",
    )
    p_run.add_argument(
        "--state", default="data/.flow_monitor_state.json", help="状态文件路径（断点续传用）"
    )
    p_run.set_defaults(func=cmd_flows_run)

    # report (收盘日报)
    p_rep = sub.add_parser("report", help="生成资金流收盘日报（markdown）")
    p_rep.add_argument("--day", help="日期 YYYY-MM-DD（默认今天）")
    p_rep.add_argument("--history-days", type=int, default=30, help="历史累计天数（默认 30）")
    p_rep.add_argument("--output", "-o", help="输出文件路径")
    p_rep.add_argument(
        "--report-dir",
        default=str(DEFAULT_FLOWS_REPORT_DIR),
        help=f"报告输出目录 (默认 {DEFAULT_FLOWS_REPORT_DIR})",
    )
    p_rep.set_defaults(func=cmd_flows_report)

    return p


def main_flows() -> NoReturn:
    parser = build_flows_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)
