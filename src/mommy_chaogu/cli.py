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

from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB
from mommy_chaogu.market_data import EfinanceAdapter
from mommy_chaogu.monitor import Monitor
from mommy_chaogu.semicon.store import Board, ChainPosition, Subcategory
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.watchlist.store import (
    GroupAlreadyExistsError,
    GroupNotFoundError,
    StockEntryNotFoundError,
)

# ---------- 默认路径 ----------

DEFAULT_DB_PATH = PORTFOLIO_DB  # watchlist / portfolio / custom_alerts
DEFAULT_LOG_PATH = Path("data/monitor.log")
DEFAULT_SIGNALS_LOG_PATH = Path("data/signals.log")
DEFAULT_CACHE_DB_PATH = MARKET_DB  # quote/bar/flow 缓存
DEFAULT_SEMICON_DB_PATH = REFERENCE_DB  # 半导体产业链
DEFAULT_FLOWS_SEMICON_DB_PATH = REFERENCE_DB  # flows 拉哪只从哪取
DEFAULT_FLOWS_DB_PATH = MARKET_DB  # 资金流缓存落到哪（复用 cache 表）
DEFAULT_FLOWS_MONITOR_LOG_PATH = Path("data/flows_monitor.log")  # monitor 信号日志
DEFAULT_FLOWS_REPORT_DIR = Path("reports/")  # 收盘日报输出目录


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
    print(f"分组数: {st['groups']}  自选股条目: {st['entries']}  去重股票数: {st['codes']}")
    return 0


def cmd_watchlist_export(args: argparse.Namespace) -> int:
    s = _store(args)
    output = Path(args.output) if args.output else None
    path = s.export_to_json(
        output,
        indent=args.indent,
        ensure_ascii=args.ensure_ascii,
    )
    st = s.stats()
    print(f"已导出 {st['groups']} 组 / {st['entries']} 条 → {path}")
    return 0


def build_watchlist_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-watchlist",
        description="妈妈炒股 - 自选股池管理",
        epilog=(
            "example:\n"
            "  mommy watchlist add 600519 --group 白酒\n"
            "  mommy watchlist list --by-group\n"
            "  mommy watchlist groups"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})"
    )

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

    # export
    p_e = sub.add_parser("export", help="导出自选股到 JSON 文件")
    p_e.add_argument(
        "--output",
        "-o",
        default=None,
        help="输出路径（默认 <db 所在目录>/watchlist.json）",
    )
    p_e.add_argument("--indent", type=int, default=2, help="JSON 缩进（默认 2）")
    p_e.add_argument(
        "--ensure-ascii",
        action="store_true",
        help="转义非 ASCII（默认不转义，保留中文）",
    )
    p_e.set_defaults(func=cmd_watchlist_export)

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


# ============================================================
# mommy-agent — LLM agent 交互式 CLI
# ============================================================


def build_agent_parser() -> argparse.ArgumentParser:
    """构建 mommy-agent 的 argparse parser。"""
    p = argparse.ArgumentParser(
        prog="mommy-agent",
        description="妈妈炒股 - LLM agent（交互式对话 / 单次提问）",
    )
    p.add_argument(
        "query",
        nargs="*",
        help="提问内容（留空则进入交互式 REPL）",
    )
    p.add_argument(
        "--provider",
        default=None,
        help="LLM provider（deepseek / openai / kimi / zai，默认读 .env）",
    )
    p.add_argument(
        "--model",
        default=None,
        help="模型名（默认由 provider 决定）",
    )
    p.add_argument(
        "--max-tool-calls",
        type=int,
        default=10,
        help="最大工具调用轮数（默认 10）",
    )
    return p


def _build_agent_context() -> object:
    """从项目默认配置构造 agent ToolContext。"""
    from mommy_chaogu.agent.tools import ToolContext
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)

    return ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        db_path=AGENT_DB,
    )


def main_agent() -> NoReturn:
    """mommy-agent 入口：交互式 LLM 对话（带工具 + 记忆系统）。"""
    parser = build_agent_parser()
    args = parser.parse_args()

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.agent.service import AgentService
    from mommy_chaogu.agent.vector_search import VectorSearch
    from mommy_chaogu.db_paths import AGENT_DB

    ctx = _build_agent_context()
    vs = VectorSearch(AGENT_DB)
    agent = AgentService(
        ctx,
        provider=args.provider,
        model=args.model,
        max_tool_calls=args.max_tool_calls,
        episodic=EpisodicMemory(AGENT_DB),
        tracker=PredictionTracker(AGENT_DB),
        semantic=SemanticMemory(AGENT_DB),
        vector_search=vs,
    )

    query = " ".join(args.query).strip() if args.query else ""

    if query:
        # 单次提问模式
        resp = agent.chat(query)
        print(resp.text)
        sys.exit(0)

    # 交互式 REPL
    print("妈妈炒股 Agent — 输入问题，Ctrl+C 或输入 q 退出\n")
    try:
        while True:
            try:
                user_input = input("❯ ").strip()
            except EOFError:
                break
            if not user_input or user_input.lower() in ("q", "quit", "exit"):
                break
            resp = agent.chat(user_input)
            print(f"\n{resp.text}\n")
            if resp.tool_calls:
                tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                print(f"[工具调用: {tool_names}]\n")
    except KeyboardInterrupt:
        print("\n再见！")
    sys.exit(0)


# ============================================================
# mommy — 面向用户的自然语言入口
# ============================================================


_WELCOME = """\
╭──────────────────────────────────────────╮
│     📋 妈妈炒股 — 你的投资助手            │
╰──────────────────────────────────────────╯

我可以帮你：

  📈 看行情   "今天怎么样" / "大盘怎么样"
  🔍 分析股票 "分析一下比亚迪" / "600519 怎么样"
  📊 看板块   "半导体板块怎么样" / "创新药板块分析"
  💰 看资金   "主力在买什么" / "资金流怎么样"
  💼 看持仓   "我的持仓怎么样"
  📋 管自选   "加个自选股 600519"
  📅 看业绩   "中报怎么样" / "业绩披露"
  📝 写报告   "今日总结" / "收盘报告"

也可直接输入子命令：watchlist / monitor / cache / flows / agent / web / tui

输入问题开始，输入 q 退出。
"""


def _run_mommy_repl(
    router: object,
    executor: object,
    agent: object | None,
    verbose: bool = False,
) -> NoReturn:
    """自然语言交互式 REPL。

    先尝试匹配工作流（零成本快速路径），
    未命中则 fallback 到 AgentService（LLM 自主对话）。
    """
    print(_WELCOME)

    from mommy_chaogu.workflow.engine import WorkflowResult

    while True:
        try:
            user_input = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            sys.exit(0)

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            sys.exit(0)

        # 帮助命令
        if user_input.lower() in ("help", "帮助", "?"):
            print(_WELCOME)
            continue

        # 尝试路由到工作流
        route = router.route(user_input)  # type: ignore[attr-defined]
        if route.matched:
            # 显示匹配反馈
            wf_desc = route.workflow.description  # type: ignore[attr-defined]
            if verbose:
                wf_id = route.workflow.id  # type: ignore[attr-defined]
                print(f"  [匹配工作流: {wf_desc}] (id={wf_id})")
            else:
                print(f"  [匹配: {wf_desc}]")

            # 工作流执行 + 进度显示
            def on_start(name: str) -> None:
                print(f"  ⠹ {name}...", end="\r", flush=True)

            def on_done(name: str, ok: bool) -> None:
                mark = "✓" if ok else "✗"
                print(f"  {mark} {name}" + " " * 10)

            print()
            result: WorkflowResult = router.execute_route(  # type: ignore[attr-defined]
                route,
                user_input,
                on_step_start=on_start,
                on_step_done=on_done,
            )
            print()

            if result.summary:
                print(result.summary)
                print()
            elif result.steps:
                # 没有总结时显示简单结果
                _print_workflow_result(result)
                print()

            # 建议
            print("💡 继续问我，或输入 q 退出\n")
        else:
            # 未命中预设工作流
            if verbose:
                reason = getattr(route, "fallback_reason", "")
                print(f"  [未命中预设工作流{f': {reason}' if reason else ''}]")
            print("  [转交 AI 助手处理]\n")

            # Fallback: 通用 LLM agent
            if agent is None:
                print(
                    "⚠️ AI 助手不可用（未配置 API key）。\n"
                    "   运行 mommy --setup 进行配置，或在 .env 文件中设置 API key。\n"
                    "   配置后可使用 AI 分析功能；行情查询和资金流等工作流仍可正常使用。\n"
                )
                continue

            print("🤔 让我想想...\n")
            try:
                def _on_tool(name: str, a: dict[str, object]) -> None:
                    if verbose:
                        args_str = ", ".join(f"{k}={v}" for k, v in a.items())
                        print(f"  🔧 {name}({args_str})")
                    else:
                        print(f"  🔧 调用: {name}...")

                resp = agent.chat(user_input, on_tool_call=_on_tool)
                print(f"\n{resp.text}\n")
                if resp.tool_calls and not verbose:
                    tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                    print(f"[调用了 {len(resp.tool_calls)} 个工具: {tool_names}]\n")
            except Exception as e:
                err_msg = str(e)
                if "rate_limit" in err_msg.lower() or "429" in err_msg:
                    print("⚠️ API 调用频率超限，请稍后重试。\n")
                elif "quota" in err_msg.lower() or "insufficient" in err_msg.lower():
                    print("⚠️ API 额度已用完，请检查账户余额。\n")
                elif "authentication" in err_msg.lower() or "401" in err_msg:
                    print("⚠️ API key 无效，请检查 .env 配置。\n")
                else:
                    print(f"⚠️ 出错了: {e}\n")


def _print_workflow_result(result: object) -> None:
    """没有 LLM 总结时，简单格式化输出工作流结果。"""

    for sr in result.steps:  # type: ignore[attr-defined]
        if not sr.success:
            continue
        print(f"**{sr.display_name}**")
        data = sr.data
        if isinstance(data, dict):
            # 尝试提取关键字段
            if "indexes" in data:
                for idx in data["indexes"][:6]:  # type: ignore[index]
                    if isinstance(idx, dict):
                        name = idx.get("name", "?")
                        price = idx.get("price", "?")
                        chg = idx.get("change_pct", 0)
                        sign = "+" if chg and chg >= 0 else ""
                        print(
                            f"  {name}: {price} ({sign}{chg:.2f}%)" if chg else f"  {name}: {price}"
                        )
            elif "sectors" in data:
                sectors = data["sectors"][:5]  # type: ignore[index]
                for s in sectors:
                    if isinstance(s, dict):
                        print(f"  {s.get('name', '?')}: {s.get('change_pct', '?')}%")
            elif "stocks" in data:
                stocks = data["stocks"][:10]  # type: ignore[index]
                for st in stocks:
                    if isinstance(st, dict):
                        code = st.get("code", "?")
                        name = st.get("name", "")
                        chg = st.get("change_pct", 0)
                        sign = "+" if chg and chg >= 0 else ""
                        print(f"  {code} {name}: {sign}{chg}%" if chg else f"  {code} {name}")
            else:
                # 概要输出
                keys = list(data.keys())[:5]
                print(f"  ({', '.join(keys)})")
        elif isinstance(data, list):
            print(f"  共 {len(data)} 条")
        elif isinstance(data, str) and data:
            print(f"  {data[:200]}")
        print()


def main_mommy() -> NoReturn:
    """mommy — 面向用户的自然语言入口。

    无参数 → 进入交互式 REPL
    带参数 → 单次自然语言查询
    <子命令> [参数] → 透传到底层 CLI（如 mommy watchlist list）
    --raw <子命令> [参数] → 同上（向后兼容）
    """
    # 子命令 → 对应 main_* 函数 / entry point 的分发表
    # mommy watchlist list / mommy --raw watchlist list 共用同一张表
    dispatch: dict[str, tuple[str, object]] = {
        "watchlist": ("mommy-watchlist", main_watchlist),
        "monitor": ("mommy-monitor", main_monitor),
        "cache": ("mommy-cache", main_cache),
        "semicon": ("mommy-semicon", main_semicon),
        "flows": ("mommy-flows", main_flows),
        "report": ("mommy-report", main_report),
        "agent": ("mommy-agent", main_agent),
        "memory": ("mommy-memory", main_memory),
        "web": ("mommy-web", main_web),
        "tui": ("mommy-tui", None),
    }

    # 直接子命令模式：mommy watchlist list
    if len(sys.argv) > 1 and sys.argv[1] in dispatch:
        subcmd = sys.argv[1]
        prog_name, func = dispatch[subcmd]
        sys.argv = [prog_name, *sys.argv[2:]]
        if func is not None:
            func()
        else:
            # tui: 独立 entry point，直接导入调用
            from mommy_chaogu.tui.app import main as _tui_main

            _tui_main()
        return

    # --raw 模式：透传到底层 CLI 子命令（向后兼容）
    if len(sys.argv) > 1 and sys.argv[1] in ("--raw", "--advanced"):
        remaining = sys.argv[2:]
        if not remaining:
            print("用法: mommy --raw <子命令> [参数]")
            print("可用子命令: " + ", ".join(dispatch.keys()))
            sys.exit(1)
        subcmd = remaining[0]
        sub_args = remaining[1:]

        if subcmd not in dispatch:
            print(f"未知子命令: {subcmd}")
            print(f"可用: {', '.join(dispatch.keys())}")
            sys.exit(1)

        prog_name, func = dispatch[subcmd]
        sys.argv = [prog_name, *sub_args]
        if func is not None:
            func()
        else:
            from mommy_chaogu.tui.app import main as _tui_main

            _tui_main()
        return

    # 正常自然语言模式
    parser = argparse.ArgumentParser(
        prog="mommy",
        description="妈妈炒股 - 自然语言投资助手",
        epilog=(
            "用法示例：\n"
            "  mommy \"今天怎么样\"        AI 自然语言对话\n"
            "  mommy watchlist list       结构化子命令（同 mommy --raw watchlist list）\n"
            "  mommy                      进入交互式 REPL\n"
            "\n"
            "可用子命令: watchlist, monitor, cache, semicon, flows, report, agent, memory, web, tui"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="自然语言提问（留空则进入交互式对话）",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="访问底层 CLI 子命令（高级用户，可直接用子命令名替代）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="显示详细的路由决策和工具调用信息",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="运行首次配置引导（选择 LLM provider + 填入 API key）",
    )
    # 解析已知参数，剩余的忽略（避免 argparse 报错）
    args, _unknown = parser.parse_known_args()

    # --setup 模式：运行首次配置引导
    if args.setup:
        from mommy_chaogu.setup import run_setup_wizard

        if run_setup_wizard():
            print("\n✅ 配置完成！现在可以开始使用了：")
            print("  mommy              # 进入交互式对话")
            print("  mommy \"今天怎么样\"  # 单次查询")
        sys.exit(0)

    # 构建工具链
    from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore
    from mommy_chaogu.workflow.engine import WorkflowExecutor
    from mommy_chaogu.workflow.router import NLRouter

    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)
    ctx = ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        db_path=AGENT_DB,
    )
    tool_registry = ToolRegistry(ctx)

    # 构建 LLM summarizer adapter（如果 API key 可用）
    llm_summarizer = None
    agent: object | None = None
    try:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker
        from mommy_chaogu.agent.semantic_memory import SemanticMemory
        from mommy_chaogu.agent.service import AgentService

        episodic = EpisodicMemory(AGENT_DB)
        agent = AgentService(
            ctx,
            episodic=episodic,
            tracker=PredictionTracker(AGENT_DB),
            semantic=SemanticMemory(AGENT_DB),
            vector_search=None,  # VectorSearch 需要 LLM client，延迟到 AgentService 内部处理
        )

        # Adapter: 让 AgentService 兼容 LLMSummarizer Protocol
        class _AgentSummarizer:
            def __init__(self, svc: AgentService) -> None:
                self._svc = svc

            def summarize(self, template: str, context: str) -> str:
                prompt = template.format(context=context)
                resp = self._svc.chat_raw(
                    [{"role": "user", "content": prompt}],
                )
                return resp.text

        llm_summarizer = _AgentSummarizer(agent)
    except (ValueError, OSError):
        # 没有配置 API key — 工作流仍可执行（没有 LLM 总结）
        pass

    executor = WorkflowExecutor(tool_registry, llm_summarizer=llm_summarizer)  # type: ignore[arg-type]
    router = NLRouter(executor=executor)

    # 单次查询模式
    query = " ".join(args.query).strip() if args.query else ""
    if query:
        route = router.route(query)
        if route.matched:
            if args.verbose:
                wf = route.workflow  # type: ignore[attr-defined]
                print(f"  [匹配工作流: {wf.description}]")
                print(f"  [工作流 ID: {wf.id}]")
            else:
                wf_desc = route.workflow.description  # type: ignore[attr-defined]
                print(f"  [匹配: {wf_desc}]")
            print()
            result = router.execute_route(
                route,
                query,
                on_step_start=lambda n: print(f"  ⠹ {n}...", end="\r", flush=True),
                on_step_done=lambda n, ok: print(f"  {'✓' if ok else '✗'} {n}" + " " * 10),
            )
            print()
            if result.summary:
                print(result.summary)
            else:
                _print_workflow_result(result)
        else:
            # 未命中预设工作流
            if args.verbose:
                reason = getattr(route, "fallback_reason", "")
                print(f"  [未命中预设工作流{f': {reason}' if reason else ''}]")
            print("  [转交 AI 助手处理]")

            # Fallback to agent
            if agent is None:
                print(
                    "⚠️ AI 助手不可用（未配置 API key）。\n"
                    "   运行 mommy --setup 进行配置，或在 .env 文件中设置 API key。\n"
                    "   配置后可使用 AI 分析功能；行情查询和资金流等工作流仍可正常使用。\n"
                )
            else:
                def _on_tool(name: str, a: dict[str, object]) -> None:
                    if args.verbose:
                        args_str = ", ".join(f"{k}={v}" for k, v in a.items())
                        print(f"  🔧 {name}({args_str})")
                    else:
                        print(f"  🔧 调用: {name}...")

                try:
                    resp = agent.chat(query, on_tool_call=_on_tool)
                    print(f"\n{resp.text}\n")
                    if resp.tool_calls and not args.verbose:
                        tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                        print(f"[调用了 {len(resp.tool_calls)} 个工具: {tool_names}]")
                except Exception as e:
                    err_msg = str(e)
                    if "rate_limit" in err_msg.lower() or "429" in err_msg:
                        print("\n⚠️ API 调用频率超限，请稍后重试。\n")
                    elif "quota" in err_msg.lower() or "insufficient" in err_msg.lower():
                        print("\n⚠️ API 额度已用完，请检查账户余额。\n")
                    elif "authentication" in err_msg.lower() or "401" in err_msg:
                        print("\n⚠️ API key 无效，请检查 .env 配置。\n")
                    else:
                        print(f"\n⚠️ 出错了: {e}\n")
        sys.exit(0)

    # 交互式 REPL
    _run_mommy_repl(router, executor, agent, verbose=args.verbose)


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
    sub.add_parser("semicon", help="半导体产业链参考库").set_defaults(
        func=lambda _: _dispatch_subcommand(build_semicon_parser(), "mommy-semicon")
    )
    sub.add_parser("flows", help="资金流拉新 + 排行 + 监控").set_defaults(
        func=lambda _: _dispatch_subcommand(build_flows_parser(), "mommy-flows")
    )
    sub.add_parser("report", help="报告 HTML 渲染（单日 / 索引 / 预览）").set_defaults(
        func=lambda _: _dispatch_subcommand(build_report_parser(), "mommy-report")
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
    p.add_argument(
        "--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})"
    )
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


# ============================================================
# semicon 子命令
# ============================================================


def _semicon_store(args: argparse.Namespace) -> object:
    from mommy_chaogu.semicon import SemiconStore

    return SemiconStore(Path(args.db))


def cmd_semicon_seed(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon import seed_store

    s = _semicon_store(args)
    r = seed_store(s, overwrite=args.overwrite)
    print(f"✅ seed 完成: 新增 {r['inserted']}  更新 {r['updated']}  跳过 {r['skipped']}")
    return 0


def _print_stocks(stocks: list[object]) -> None:
    if not stocks:
        print("（暂无数据）")
        return
    print(f"{'代码':<8} {'名称':<10} {'主位置':<6} {'子分类':<8} {'产品':<16} {'板块':<6} 备注")
    print("─" * 90)
    for s in stocks:
        prod = (s.product or "—")[:14]
        note = (s.note or "")[:30]
        print(
            f"{s.code:<8} {s.name:<10} {s.chain_position:<6} {s.subcategory:<8} "
            f"{prod:<16} {s.board:<6} {note}"
        )


def cmd_semicon_list(args: argparse.Namespace) -> int:
    s = _semicon_store(args)
    if args.chain:
        rows = s.list_by_chain(args.chain)
    elif args.subcategory:
        rows = s.list_by_subcategory(args.subcategory)
    else:
        rows = s.list_all()
    _print_stocks(rows)
    print(f"\n共 {len(rows)} 条")
    return 0


def cmd_semicon_search(args: argparse.Namespace) -> int:
    s = _semicon_store(args)
    rows = s.search(args.keyword)
    print(f"🔍 关键字 {args.keyword!r} 命中 {len(rows)} 条")
    print("─" * 90)
    _print_stocks(rows)
    return 0


def cmd_semicon_get(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon.store import StockNotFoundError

    s = _semicon_store(args)
    try:
        row = s.require(args.code)
    except StockNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"代码: {row.code}")
    print(f"名称: {row.name}")
    print(f"主位置: {row.chain_position}")
    print(f"子分类: {row.subcategory}")
    print(f"产品: {row.product or '—'}")
    print(f"板块: {row.board}")
    print(f"备注: {row.note or '—'}")
    print(f"添加于: {row.created_at:%Y-%m-%d %H:%M:%S}")
    print(f"更新于: {row.updated_at:%Y-%m-%d %H:%M:%S}")
    return 0


def cmd_semicon_stats(args: argparse.Namespace) -> int:
    s = _semicon_store(args)
    st = s.stats()
    print("📊 半导体产业链参考库统计")
    print("─" * 60)
    print(f"  股票总数:    {st['total']}")
    print(f"  主位置数:    {st['chains']} ({' / '.join(c.value for c in ChainPosition)})")
    print(f"  子分类数:    {st['subcategories']}")
    print(f"  板块数:      {st['boards']}")
    print()
    print("按主位置分布:")
    for cp, n in s.count_by_chain():
        bar = "█" * min(n // 2, 30)
        print(f"  {cp:<6} {n:>3}  {bar}")
    print()
    print("按子分类分布（chain / subcategory / count）:")
    for cp, sub, n in s.count_by_subcategory():
        bar = "█" * min(n, 20)
        print(f"  {cp:<6} / {sub:<8} {n:>3}  {bar}")
    return 0


def cmd_semicon_add(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon.store import StockAlreadyExistsError

    s = _semicon_store(args)
    try:
        row = s.add(
            args.code,
            args.name,
            args.chain,
            args.subcategory,
            product=args.product,
            board=args.board,
            note=args.note,
        )
    except StockAlreadyExistsError as e:
        print(f"⚠️  {e}")
        return 1
    print(f"✅ 已添加 {row.code} {row.name} ({row.chain_position}/{row.subcategory})")
    return 0


def cmd_semicon_remove(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon.store import StockNotFoundError

    s = _semicon_store(args)
    try:
        s.remove(args.code)
    except StockNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"🗑️  已删除 {args.code}")
    return 0


def build_semicon_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-semicon",
        description="妈妈炒股 - 半导体产业链参考库（A 股，按位置/产品分组）",
        epilog=(
            "example:\n"
            "  mommy semicon seed\n"
            "  mommy semicon list --chain 上游\n"
            "  mommy semicon search 存储"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db",
        default=str(DEFAULT_SEMICON_DB_PATH),
        help=f"数据库路径 (默认 {DEFAULT_SEMICON_DB_PATH})",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # seed
    p_seed = sub.add_parser("seed", help="灌入种子数据")
    p_seed.add_argument("--overwrite", action="store_true", help="覆盖已有记录（更新字段）")
    p_seed.set_defaults(func=cmd_semicon_seed)

    # list
    p_l = sub.add_parser("list", help="列出股票")
    p_l.add_argument(
        "--chain",
        "-c",
        choices=[c.value for c in ChainPosition],
        help="按主位置过滤（上游/中游/下游/末端）",
    )
    p_l.add_argument("--subcategory", "-s", help="按子分类过滤（如 设备/材料/存储/...）")
    p_l.set_defaults(func=cmd_semicon_list)

    # search
    p_sr = sub.add_parser("search", help="按关键字模糊搜索 name/product/note/code")
    p_sr.add_argument("keyword", help="关键字")
    p_sr.set_defaults(func=cmd_semicon_search)

    # get
    p_g = sub.add_parser("get", help="查询单只股票详情")
    p_g.add_argument("code", help="股票代码")
    p_g.set_defaults(func=cmd_semicon_get)

    # stats
    sub.add_parser("stats", help="汇总统计 + 分布").set_defaults(func=cmd_semicon_stats)

    # add
    p_a = sub.add_parser("add", help="手动添加一条记录")
    p_a.add_argument("code", help="股票代码")
    p_a.add_argument("name", help="中文名")
    p_a.add_argument(
        "--chain", "-c", required=True, choices=[c.value for c in ChainPosition], help="主位置"
    )
    p_a.add_argument(
        "--subcategory",
        "-s",
        required=True,
        choices=[sc.value for sc in Subcategory],
        help="子分类",
    )
    p_a.add_argument("--product", "-p", help="具体产品")
    p_a.add_argument(
        "--board", "-b", default="主板", choices=[b.value for b in Board], help="板块（默认 主板）"
    )
    p_a.add_argument("--note", "-n", help="备注")
    p_a.set_defaults(func=cmd_semicon_add)

    # remove
    p_r = sub.add_parser("remove", help="删除一条记录")
    p_r.add_argument("code", help="股票代码")
    p_r.set_defaults(func=cmd_semicon_remove)

    return p


def main_semicon() -> NoReturn:
    parser = build_semicon_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)


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


# ============================================================
# report 子命令（HTML 报告渲染）
# ============================================================


DEFAULT_REPORT_HTML_DIR = Path("reports")


def _resolve_report_md(day: str | None) -> Path:
    """根据 --day 找到对应的 .md 报告。"""
    from datetime import date

    d = date.fromisoformat(day) if day else date.today()
    return Path(DEFAULT_FLOWS_REPORT_DIR) / f"flows_report_{d.isoformat()}.md"


def cmd_report_render(args: argparse.Namespace) -> int:
    from mommy_chaogu.report_render import parse_markdown_report, render_one

    md_path = _resolve_report_md(args.day)
    if not md_path.exists():
        print(f"❌ 找不到报告: {md_path}")
        print(f"   先跑: uv run mommy-flows --pool {args.pool} report --day {args.day or '今天'}")
        return 1

    r = parse_markdown_report(md_path)
    out_dir = Path(args.out_dir)
    p = render_one(r, out_dir=out_dir)
    print(f"✅ {p}  ({p.stat().st_size:,} B)")
    print(f"   打开: open {p}")
    return 0


def cmd_report_index(args: argparse.Namespace) -> int:
    """扫描所有 .md 报告，渲染 index.html。"""
    from mommy_chaogu.report_render import (
        ReportData,
        parse_markdown_report,
        render_index,
    )

    src_dir = Path(DEFAULT_FLOWS_REPORT_DIR)
    if not src_dir.exists():
        print(f"❌ 报告目录不存在: {src_dir}")
        return 1

    md_files = sorted(src_dir.glob("*.md"))
    if not md_files:
        print(f"❌ 没有任何报告: {src_dir}/*.md")
        return 1

    reports: list[ReportData] = []
    for p in md_files:
        try:
            reports.append(parse_markdown_report(p))
        except Exception:
            # 跳过非 flows 日报格式的 .md 文件
            continue
    if not reports:
        print(f"❌ 没有找到可解析的 flows 日报: {src_dir}/*.md")
        return 1
    p = render_index(reports, out_dir=args.out_dir)
    print(f"✅ {p}  ({len(reports)} 份报告)")
    return 0


def cmd_report_serve(args: argparse.Namespace) -> int:
    """起一个临时 HTTP server 预览 reports/。"""
    import http.server
    import socketserver

    out_dir = Path(args.out_dir).resolve()
    if not out_dir.exists():
        print(f"❌ {out_dir} 不存在，先跑 mommy-report render")
        return 1

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(out_dir), **kwargs)

    with socketserver.TCPServer(("0.0.0.0", args.port), _Handler) as srv:
        print(f"🌐 {out_dir} listening on http://localhost:{args.port}/")
        print("   Ctrl+C 退出")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 bye")
    return 0


def build_report_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-report",
        description="把 .md 资金流报告渲染成独立 HTML 网页",
        epilog=(
            "example:\n"
            "  mommy report render\n"
            "  mommy report index\n"
            "  mommy report serve --port 8787"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_r = sub.add_parser("render", help="渲染单日报告 HTML")
    p_r.add_argument("--day", help="日期 YYYY-MM-DD（默认今天）")
    p_r.add_argument("--pool", default="semicon", help="池子（决定报告路径）")
    p_r.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_HTML_DIR),
        help=f"HTML 输出目录 (默认 {DEFAULT_REPORT_HTML_DIR})",
    )
    p_r.set_defaults(func=cmd_report_render)

    p_i = sub.add_parser("index", help="扫描全部 .md 报告，重建 index.html")
    p_i.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_HTML_DIR),
        help=f"HTML 输出目录 (默认 {DEFAULT_REPORT_HTML_DIR})",
    )
    p_i.set_defaults(func=cmd_report_index)

    p_s = sub.add_parser("serve", help="起 HTTP server 预览 reports/")
    p_s.add_argument("--port", type=int, default=8787, help="端口（默认 8787）")
    p_s.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_HTML_DIR),
        help=f"HTML 输出目录 (默认 {DEFAULT_REPORT_HTML_DIR})",
    )
    p_s.set_defaults(func=cmd_report_serve)

    return p


def main_report() -> NoReturn:
    parser = build_report_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)


# ============================================================
# memory 子命令（记忆系统可见性）
# ============================================================


def _truncate(text: str, width: int) -> str:
    """把文本截断到 *width* 个字符，超出则加省略号。"""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_memory_stats(args: argparse.Namespace) -> int:
    """显示记忆系统汇总统计。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.memory import ConversationMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    db_path = Path(args.db)
    conv = ConversationMemory(db_path).summary()
    ep = EpisodicMemory(db_path).summary()
    pred = PredictionTracker(db_path).stats()
    sem = SemanticMemory(db_path).summary()

    print("🧠 记忆系统统计")
    print("─" * 60)
    print(f"  数据库: {db_path}")
    print()
    print("对话记忆 (agent_memory):")
    print(f"  总条数: {conv['total']}  (user {conv['user']} / assistant {conv['assistant']})")
    print()
    print("事件记忆 (episodic_events):")
    print(f"  总条数: {ep['total']}")
    if ep.get("earliest"):
        print(f"  时间跨度: {ep['earliest'][:10]} ~ {ep['latest'][:10]}")
    if ep["by_type"]:
        print("  按类型:")
        for t, n in sorted(ep["by_type"].items(), key=lambda x: -x[1]):
            print(f"    {t}: {n}")
    print()
    print("预测追踪 (predictions):")
    print(
        f"  总数: {pred['total']}  "
        f"命中 {pred['hit']}  未中 {pred['missed']}  待验证 {pred['pending']}"
    )
    if pred["hit"] + pred["missed"] > 0:
        print(f"  命中率: {pred['hit_rate']:.1%}")
    print()
    print("知识记忆 (semantic_knowledge):")
    print(f"  总条数: {sem['total']}  (active {sem['active']} / superseded {sem['superseded']})")
    return 0


def cmd_memory_events(args: argparse.Namespace) -> int:
    """显示最近的结构化事件。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    em = EpisodicMemory(Path(args.db))
    events = em.recent(days=args.days, limit=args.limit)
    if not events:
        print("（暂无事件）")
        return 0
    print(f"📋 最近事件（{len(events)} 条）")
    print("─" * 80)
    print(f"{'时间':<21} {'类型':<18} {'代码':<8} {'摘要'}")
    print("─" * 80)
    for e in events:
        ts = str(e["timestamp"])[:19]
        etype = _truncate(e["event_type"], 18)
        code = e.get("code") or "—"
        summary = _truncate(e["summary"], 40)
        print(f"{ts:<21} {etype:<18} {code:<8} {summary}")
    return 0


def cmd_memory_predictions(args: argparse.Namespace) -> int:
    """显示最近的预测。"""
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(Path(args.db))
    preds = tracker.all(limit=args.limit, status=args.status)
    if not preds:
        print("（暂无预测）")
        return 0
    print(f"🎯 预测记录（{len(preds)} 条）")
    print("─" * 90)
    print(f"{'时间':<21} {'代码':<8} {'方向':<6} {'状态':<10} {'周期':<6} {'预测内容'}")
    print("─" * 90)
    for p in preds:
        ts = str(p.get("created_at", ""))[:19]
        code = p.get("code") or "—"
        direction = p.get("direction") or "—"
        status = p.get("status") or "—"
        timeframe = p.get("timeframe") or "—"
        prediction = _truncate(p.get("prediction") or "", 30)
        print(f"{ts:<21} {code:<8} {direction:<6} {status:<10} {timeframe:<6} {prediction}")
    return 0


def cmd_memory_knowledge(args: argparse.Namespace) -> int:
    """显示语义知识条目。"""
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    sm = SemanticMemory(Path(args.db))
    entries = sm.get_active(limit=args.limit)
    if not entries:
        print("（暂无知识条目）")
        return 0
    print(f"💡 知识记忆（{len(entries)} 条 active）")
    print("─" * 80)
    for e in entries:
        ktype = e.get("knowledge_type") or "—"
        scope = e.get("scope") or "—"
        content = _truncate(e.get("content") or "", 60)
        confidence = e.get("confidence", 0.0)
        print(f"  [{ktype}] {scope}")
        print(f"    {content}  (置信度 {confidence:.0%})")
    return 0


def cmd_memory_history(args: argparse.Namespace) -> int:
    """显示最近对话历史。"""
    from mommy_chaogu.agent.memory import ConversationMemory

    mem = ConversationMemory(Path(args.db))
    msgs = mem.recent(limit=args.limit)
    if not msgs:
        print("（暂无对话历史）")
        return 0
    print(f"💬 对话历史（最近 {len(msgs)} 条）")
    print("─" * 80)
    for m in msgs:
        ts = m["timestamp"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)[:19]
        role = m["role"]
        content = _truncate(m["content"], 60)
        print(f"{ts_str}  [{role}] {content}")
    return 0


def build_memory_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-memory",
        description="妈妈炒股 - 记忆系统查看（对话 / 事件 / 预测 / 知识）",
    )
    p.add_argument(
        "--db",
        default=str(AGENT_DB),
        help=f"记忆数据库路径 (默认 {AGENT_DB})",
    )

    sub = p.add_subparsers(dest="cmd")

    # stats（默认）
    p_stats = sub.add_parser("stats", help="汇总统计")
    p_stats.set_defaults(func=cmd_memory_stats)

    # events
    p_ev = sub.add_parser("events", help="最近结构化事件")
    p_ev.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_ev.add_argument("--days", type=int, default=90, help="只看最近 N 天 (默认 90)")
    p_ev.set_defaults(func=cmd_memory_events)

    # predictions
    p_pr = sub.add_parser("predictions", help="预测记录")
    p_pr.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_pr.add_argument(
        "--status",
        choices=["pending", "hit", "missed", "expired", "unverifiable"],
        default=None,
        help="按状态过滤",
    )
    p_pr.set_defaults(func=cmd_memory_predictions)

    # knowledge
    p_kn = sub.add_parser("knowledge", help="语义知识条目")
    p_kn.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_kn.set_defaults(func=cmd_memory_knowledge)

    # history
    p_hi = sub.add_parser("history", help="最近对话历史")
    p_hi.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_hi.set_defaults(func=cmd_memory_history)

    return p


def main_memory() -> NoReturn:
    parser = build_memory_parser()
    args = parser.parse_args()
    # 无子命令时默认 stats
    if not getattr(args, "func", None):
        args.func = cmd_memory_stats
    rc = args.func(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
