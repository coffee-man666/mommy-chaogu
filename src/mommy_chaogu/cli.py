# ruff: noqa: F403,F405,I001
"""Command-line entry points and natural-language dispatcher.

Command-family implementations live in :mod:`mommy_chaogu.cli_commands`.
This module remains the stable compatibility facade for project entry points.
"""

from __future__ import annotations

# The facade intentionally re-exports the established command API.
from mommy_chaogu.cli_support import *
from mommy_chaogu.cli_commands.agent import *
from mommy_chaogu.cli_commands.cache import *
from mommy_chaogu.cli_commands.flows import *
from mommy_chaogu.cli_commands.memory import *
from mommy_chaogu.cli_commands.monitor import *
from mommy_chaogu.cli_commands.report import *
from mommy_chaogu.cli_commands.semicon import *
from mommy_chaogu.cli_commands.watchlist import *
from mommy_chaogu.cli_commands.web import *

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
            '  mommy "今天怎么样"        AI 自然语言对话\n'
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
            print('  mommy "今天怎么样"  # 单次查询')
        sys.exit(0)

    # 构建工具链
    from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore
    from mommy_chaogu.workflow.engine import WorkflowExecutor
    from mommy_chaogu.workflow.definitions import get_default_registry
    from mommy_chaogu.workflow.router import NLRouter

    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)
    ctx = ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
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
    router = NLRouter(get_default_registry(), executor=executor)

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


if __name__ == "__main__":
    raise SystemExit(main())
