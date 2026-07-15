"""monitor command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

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
    m = Monitor(
        s,
        adp,
        log_path=log_path,
        alerter=Alerter.default(log_path=signals_log_path) if args.with_signals else None,
    )  # type: ignore[arg-type]
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
    tail = lines[-args.tail :] if args.tail > 0 else lines
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
    tail = lines[-args.tail :] if args.tail > 0 else lines
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
        print(f"{rule.rule_id:<28} {cfg.enabled!s:<8} {cfg.severity.value:<10} {params_str}")
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
        epilog=(
            "example:\n"
            "  mommy monitor snapshot\n"
            "  mommy monitor run --interval 30\n"
            "  mommy monitor log --tail 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})"
    )
    p.add_argument(
        "--log", default=str(DEFAULT_LOG_PATH), help=f"日志路径 (默认 {DEFAULT_LOG_PATH})"
    )
    p.add_argument(
        "--signals-log",
        default=str(DEFAULT_SIGNALS_LOG_PATH),
        help=f"信号日志路径 (默认 {DEFAULT_SIGNALS_LOG_PATH})",
    )

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
