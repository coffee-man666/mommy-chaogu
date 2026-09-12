# ruff: noqa: F403,F405,I001
"""Command-line entry points and natural-language dispatcher.

Command-family implementations live in :mod:`mommy_chaogu.cli_commands`.
This module remains the stable compatibility facade for project entry points.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mommy_chaogu.workflow.assembly import NLRuntime
    from mommy_chaogu.workflow.router import NLRouter
    from mommy_chaogu.workflow.store import WorkflowStore

# The facade intentionally re-exports the established command API.
from mommy_chaogu.cli_support import *
from mommy_chaogu.agent.service import ChatCallbacks
from mommy_chaogu.cli_commands.agent import *
from mommy_chaogu.cli_commands.agent_managed import main_doctor
from mommy_chaogu.cli_commands.cache import *
from mommy_chaogu.cli_commands.channel import *
from mommy_chaogu.cli_commands.connect import *
from mommy_chaogu.cli_commands.flows import *
from mommy_chaogu.cli_commands.memory import *
from mommy_chaogu.cli_commands.monitor import *
from mommy_chaogu.cli_commands.report import *
from mommy_chaogu.cli_commands.semicon import *
from mommy_chaogu.cli_commands.watchlist import *
from mommy_chaogu.cli_commands.web import *
from mommy_chaogu.cli_commands.workflow import *
from mommy_chaogu.cli_repl import _REPL_SPARKLINE as _REPL_SPARKLINE
from mommy_chaogu.cli_repl import render_logo as _render_logo  # noqa: F401  测试兼容 re-export
from mommy_chaogu.cli_repl import print_workflow_result
from mommy_chaogu.errors import friendly_error
from mommy_chaogu.setup import main_setup

# ============================================================
# mommy — 面向用户的自然语言入口
# ============================================================


def _flush_agent(agent: object | None) -> None:
    """退出前等后台提取线程完成（P6：daemon 线程随进程退出会被丢弃）。"""
    if agent is None:
        return
    flush = getattr(agent, "flush", None)
    if callable(flush):
        flush(timeout=10)


def _run_mommy_repl(
    router: NLRouter,
    executor: object,
    agent: object | None,
    verbose: bool = False,
    workflow_hit_recorder: Callable[[str], None] | None = None,
) -> NoReturn:
    """专业化自然语言 REPL：富文本回答、单行进度和友好错误。

    渲染与交互组件（欢迎/帮助/斜杠命令/agent Live 视图/工作流结果打印）
    在 :mod:`mommy_chaogu.cli_repl`，本函数只保留编排循环。
    """
    import logging
    import time
    from importlib.metadata import PackageNotFoundError, version
    from uuid import uuid4

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    from mommy_chaogu.cli_prompt import ReplPrompt
    from mommy_chaogu.cli_repl import (
        EXIT_COMMANDS,
        ReplContext,
        ReplUI,
        run_agent_chat,
        run_workflow_route,
    )

    console = Console(highlight=False)
    provider = getattr(agent, "_provider", "") if agent is not None else ""
    model = getattr(agent, "_model", "") if agent is not None else ""
    model_label = str(model or "AI 未配置")
    identity = f"{provider} / {model}" if provider and model else "AI 未配置"
    session_id = f"session_{uuid4().hex[:12]}"
    cwd = Path.cwd()
    cwd_full = str(cwd)
    cwd_label = f"…/{'/'.join(cwd.parts[-3:])}" if len(cwd_full) > 40 else cwd_full
    try:
        app_version = version("mommy-chaogu")
    except PackageNotFoundError:
        app_version = "dev"
    prompt = ReplPrompt(
        model_label=model_label,
        cwd_label=cwd_label,
        status_provider=lambda: "AI 已连接" if agent is not None else "仅行情模式",
    )

    # 默认界面不应混入 requests/SQLAlchemy 等底层 traceback。-v 模式
    # 保留原日志，用于开发者诊断。
    if not verbose:
        package_logger = logging.getLogger("mommy_chaogu")
        package_logger.handlers.clear()
        package_logger.addHandler(logging.NullHandler())
        package_logger.propagate = False

    ui = ReplUI(
        console,
        ReplContext(
            provider=provider,
            model_label=model_label,
            identity=identity,
            cwd_full=cwd_full,
            session_id=session_id,
            app_version=app_version,
            has_agent=agent is not None,
        ),
    )
    ui.welcome()

    while True:
        try:
            user_input = prompt.read()
        except KeyboardInterrupt:
            console.print("\n[dim]已取消当前输入。输入 /quit 退出。[/]")
            continue
        except EOFError:
            console.print("\n[dim]再见。[/]")
            _flush_agent(agent)
            sys.exit(0)

        if not user_input:
            continue
        console.print(f"[bold #7c5cff]›[/] {user_input}")
        if ui.handle_command(user_input):
            if user_input.lower() in EXIT_COMMANDS:
                _flush_agent(agent)
                sys.exit(0)
            continue

        route = router.route(user_input)
        started = time.monotonic()

        if route.matched:
            wf_desc = route.workflow.description if route.workflow is not None else ""
            try:
                result = run_workflow_route(console, router, route, user_input)
            except Exception as exc:
                ui.error(exc, verbose)
                continue

            console.print()
            if result.summary:
                console.print(Markdown(result.summary))
            elif result.steps:
                print_workflow_result(result)
            if (
                workflow_hit_recorder is not None
                and result.workflow_id.startswith("user_")
                and result.succeeded
            ):
                workflow_hit_recorder(result.workflow_id)
            elapsed = time.monotonic() - started
            console.print(f"[dim]✓ {wf_desc} · {elapsed:.1f}s[/]")
            continue

        if agent is None:
            console.print(
                Panel(
                    "AI 助手尚未配置。运行 [bold]mommy setup[/] 配置 Provider、模型和 API key。",
                    title="[yellow]需要配置[/]",
                    border_style="yellow",
                )
            )
            continue

        try:
            stats = run_agent_chat(console, agent, user_input, verbose)  # type: ignore[arg-type]
        except KeyboardInterrupt:
            console.print("[yellow]■ 已中断当前任务。[/]")
            continue
        except Exception as exc:
            ui.error(exc, verbose)
            continue

        if verbose and stats.verbose_events:
            console.print(
                Panel("\n".join(stats.verbose_events), title="执行详情", border_style="dim")
            )

        elapsed = time.monotonic() - started
        unique_tools = list(dict.fromkeys(stats.tool_names))
        details = f" · {len(stats.tool_names)} 次数据查询" if stats.tool_names else ""
        if stats.failed_tools:
            details += f" · [yellow]{stats.failed_tools} 项未取到[/]"
        if verbose and unique_tools:
            details += f" · {', '.join(unique_tools)}"
        console.print(f"[dim]✓ 完成 · {elapsed:.1f}s{details}[/]")


def _build_dispatch() -> dict[str, tuple[str, Callable[[], object] | None]]:
    """子命令 → (prog 名, main 函数) 分发表；tui 走独立 entry point 用 None。"""
    return {
        "watchlist": ("mommy-watchlist", main_watchlist),
        "monitor": ("mommy-monitor", main_monitor),
        "cache": ("mommy-cache", main_cache),
        "channel": ("mommy-channel", main_channel),
        "connect": ("mommy-connect", main_connect),
        "setup": ("mommy-setup", main_setup),
        "semicon": ("mommy-semicon", main_semicon),
        "flows": ("mommy-flows", main_flows),
        "report": ("mommy-report", main_report),
        "agent": ("mommy-agent", main_agent),
        "memory": ("mommy-memory", main_memory),
        "web": ("mommy-web", main_web),
        "tui": ("mommy-tui", None),
        "workflow": ("mommy-workflow", main_workflow),
        "doctor": ("mommy-doctor", main_doctor),
    }


def _launch_subcommand(func: Callable[[], object] | None) -> None:
    """启动分发表命中的子命令 main（tui 延迟导入，避免 REPL 模式背上 Textual）。"""
    if func is not None:
        func()
        return
    from mommy_chaogu.tui.app import main as _tui_main

    _tui_main()


def _dispatch_passthrough_subcommand(
    dispatch: dict[str, tuple[str, Callable[[], object] | None]],
) -> bool:
    """直接子命令（mommy watchlist list）与 --raw 透传模式。

    命中并启动子命令时返回 True（子命令 main 自行退出）；否则返回 False
    继续自然语言模式。--raw 的用法错误直接 sys.exit。
    """
    argv = sys.argv
    if len(argv) > 1 and argv[1] in dispatch:
        prog_name, func = dispatch[argv[1]]
        sys.argv = [prog_name, *argv[2:]]
        _launch_subcommand(func)
        return True

    if len(argv) > 1 and argv[1] in ("--raw", "--advanced"):
        remaining = argv[2:]
        if not remaining:
            print("用法: mommy --raw <子命令> [参数]")
            print("可用子命令: " + ", ".join(dispatch.keys()))
            sys.exit(1)
        subcmd = remaining[0]
        if subcmd not in dispatch:
            print(f"未知子命令: {subcmd}")
            print(f"可用: {', '.join(dispatch.keys())}")
            sys.exit(1)
        prog_name, func = dispatch[subcmd]
        sys.argv = [prog_name, *remaining[1:]]
        _launch_subcommand(func)
        return True

    return False


def _build_cli_toolchain() -> tuple[NLRuntime, WorkflowStore]:
    """CLI 入口的工具链装配：CachedAdapter + 共享 build_nl_runtime 工厂。"""
    from mommy_chaogu.agent.tools import ToolContext
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import create_adapter_chain
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore
    from mommy_chaogu.workflow.assembly import build_nl_runtime
    from mommy_chaogu.workflow.store import WorkflowStore

    adapter = CachedMarketDataAdapter(create_adapter_chain(), CacheStore(MARKET_DB))
    ctx = ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
    )
    # 三入口共享装配工厂（builtin + 自定义工作流 merge + 共享 summarizer），
    # 本入口持有 WorkflowStore 以便 increment_hit / 退出 close
    workflow_store = WorkflowStore(AGENT_DB)
    return build_nl_runtime(context=ctx, workflow_store=workflow_store), workflow_store


def _run_single_query(
    query: str,
    *,
    runtime: NLRuntime,
    workflow_store: WorkflowStore,
    verbose: bool,
) -> NoReturn:
    """单次自然语言查询：正则工作流优先，未命中转交 AI 助手，完成即退出。"""
    router, agent = runtime.router, runtime.agent_service

    route = router.route(query)
    if route.matched:
        if verbose:
            wf = route.workflow
            print(f"  [匹配工作流: {wf.description if wf else '?'}]")
            print(f"  [工作流 ID: {wf.id if wf else '?'}]")
        else:
            wf_desc = route.workflow.description if route.workflow is not None else "?"
            print(f"  [匹配: {wf_desc}]")
        print()
        try:
            result = router.execute_route(
                route,
                query,
                on_step_start=lambda n: print(f"  ⠹ {n}...", end="\r", flush=True),
                on_step_done=lambda n, ok: print(f"  {'✓' if ok else '✗'} {n}" + " " * 10),
            )
        except ValueError as exc:
            print(f"  ⚠️ 工作流参数解析失败: {exc}")
            workflow_store.close()
            sys.exit(1)
        print()
        if result.summary:
            print(result.summary)
        else:
            print_workflow_result(result)
        if result.workflow_id.startswith("user_") and result.succeeded:
            workflow_store.increment_hit(result.workflow_id)
    else:
        # 未命中预设工作流
        if verbose:
            reason = getattr(route, "fallback_reason", "")
            print(f"  [未命中预设工作流{f': {reason}' if reason else ''}]")
        print("  [转交 AI 助手处理]")

        if agent is None:
            print(
                "⚠️ AI 助手不可用（未配置 API key）。\n"
                "   运行 mommy setup 配置 Provider、模型和 API key。\n"
                "   配置后可使用 AI 分析功能；行情查询和资金流等工作流仍可正常使用。\n"
            )
        else:

            def _on_tool(name: str, a: dict[str, object]) -> None:
                if verbose:
                    args_str = ", ".join(f"{k}={v}" for k, v in a.items())
                    print(f"  🔧 {name}({args_str})")
                else:
                    print(f"  🔧 调用: {name}...")

            try:
                resp = agent.chat(query, callbacks=ChatCallbacks(on_tool_call=_on_tool))
                print(f"\n{resp.text}\n")
                if resp.tool_calls and not verbose:
                    tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                    print(f"[调用了 {len(resp.tool_calls)} 个工具: {tool_names}]")
                # P6：后台提取线程完成后再退出（单发模式唯一的消息轮次，
                # 不 flush 进程退出时提取会被静默丢弃）
                agent.flush(timeout=30)
            except Exception as e:
                print(f"\n⚠️ {friendly_error(e)}\n")
    workflow_store.close()
    sys.exit(0)


def main_mommy() -> None:
    """mommy — 面向用户的自然语言入口。

    无参数 → 进入交互式 REPL
    带参数 → 单次自然语言查询
    <子命令> [参数] → 透传到底层 CLI（如 mommy watchlist list）
    --raw <子命令> [参数] → 同上（向后兼容）
    """
    # 加载 .env 里的 API key（与 mommy-agent 的 load_config、TUI bootstrap
    # 对齐——主入口漏了这步时，只配 .env 的用户会被误报「未配置 API key」）。
    # 不覆盖已有的 shell 环境变量。
    from mommy_chaogu.config import load_runtime_env

    load_runtime_env()

    if _dispatch_passthrough_subcommand(_build_dispatch()):
        return

    parser = argparse.ArgumentParser(
        prog="mommy",
        description="妈妈炒股 - 自然语言投资助手",
        epilog=(
            "用法示例：\n"
            '  mommy "今天怎么样"        AI 自然语言对话\n'
            "  mommy watchlist list       结构化子命令（同 mommy --raw watchlist list）\n"
            "  mommy                      进入交互式 REPL\n"
            "\n"
            "可用子命令: watchlist, monitor, cache, semicon, flows, report, agent, memory, channel, connect, setup, web, tui, workflow, doctor"
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
        help="运行首次配置引导（Provider + 模型 + API key + 微信）",
    )
    # 解析已知参数；无法识别的参数告警而非静默吞掉（拼错参数应当被看见）
    args, unknown = parser.parse_known_args()
    if unknown:
        print(
            f"⚠️ 已忽略无法识别的参数: {' '.join(unknown)}（完整用法见 mommy --help）",
            file=sys.stderr,
        )

    # --setup 模式：运行首次配置引导
    if args.setup:
        from mommy_chaogu.setup import run_setup_wizard

        sys.exit(0 if run_setup_wizard(offer_interface=True) else 1)

    # 安装后第一次直接运行 mommy 时自动进入统一 onboarding；已有项目级
    # 或用户级配置时是一次无交互的快速检查。
    from mommy_chaogu.setup import check_and_run_setup, configured_interface

    check_and_run_setup(offer_interface=True)

    # 只有无参数的交互式启动才遵循界面偏好。单次问答和结构化
    # 子命令仍保持可组合的 CLI 语义。
    if not args.query:
        interface = configured_interface()
        if interface == "tui":
            sys.argv = ["mommy-tui"]
            from mommy_chaogu.tui.app import main as _tui_main

            _tui_main()
            return
        if interface == "web":
            sys.argv = ["mommy-web"]
            main_web()
            return

    runtime, workflow_store = _build_cli_toolchain()

    # 单次查询模式
    query = " ".join(args.query).strip() if args.query else ""
    if query:
        _run_single_query(
            query, runtime=runtime, workflow_store=workflow_store, verbose=args.verbose
        )

    # 交互式 REPL
    try:
        _run_mommy_repl(
            runtime.router,
            runtime.executor,
            runtime.agent_service,
            verbose=args.verbose,
            workflow_hit_recorder=workflow_store.increment_hit,
        )
    finally:
        workflow_store.close()


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
