# ruff: noqa: F403,F405,I001
"""Command-line entry points and natural-language dispatcher.

Command-family implementations live in :mod:`mommy_chaogu.cli_commands`.
This module remains the stable compatibility facade for project entry points.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.text import Text

# The facade intentionally re-exports the established command API.
from mommy_chaogu.cli_support import *
from mommy_chaogu.cli_commands.agent import *
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
from mommy_chaogu.setup import main_setup

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

也可直接输入子命令：watchlist / monitor / cache / flows / agent / web / tui / connect

输入问题开始，输入 q 退出。
"""

_REPL_M_LOGO = """\
███╗   ███╗
████╗ ████║
██╔████╔██║
██║╚██╔╝██║
██║ ╚═╝ ██║
╚═╝     ╚═╝"""
_REPL_SPARKLINE = "▁▂▄▃▅▆█"
_LOGO_GRADIENT = ((124, 92, 255), (91, 192, 190))  # 品牌紫 → 青
_SPARK_UP_STYLE = "bold #f43f5e"  # A股红涨
_SPARK_DOWN_STYLE = "bold #22c55e"  # 绿跌
_SPARK_ARROW_STYLE = "bold #f59e0b"


def _render_logo() -> Text:
    """量化终端风 logo：紫→青水平渐变的块体 M + 红绿迷你 K 线。"""
    from rich.text import Text

    lines = _REPL_M_LOGO.splitlines()
    width = max(len(line) for line in lines) - 1
    (r1, g1, b1), (r2, g2, b2) = _LOGO_GRADIENT
    logo = Text(no_wrap=True)
    for y, line in enumerate(lines):
        if y:
            logo.append("\n")
        for x, char in enumerate(line):
            t = x / width
            r = round(r1 + (r2 - r1) * t)
            g = round(g1 + (g2 - g1) * t)
            b = round(b1 + (b2 - b1) * t)
            logo.append(char, style=f"bold rgb({r},{g},{b})")
    logo.append("\n")
    levels = "▁▂▃▄▅▆▇█"
    prev = 0
    for char in _REPL_SPARKLINE:
        level = levels.index(char)
        logo.append(char, style=_SPARK_UP_STYLE if level >= prev else _SPARK_DOWN_STYLE)
        prev = level
    logo.append("↗", style=_SPARK_ARROW_STYLE)
    return logo


def _flush_agent(agent: object | None) -> None:
    """退出前等后台提取线程完成（P6：daemon 线程随进程退出会被丢弃）。"""
    if agent is None:
        return
    flush = getattr(agent, "flush", None)
    if callable(flush):
        flush(timeout=10)


def _run_mommy_repl(
    router: object,
    executor: object,
    agent: object | None,
    verbose: bool = False,
    workflow_hit_recorder: Callable[[str], None] | None = None,
) -> NoReturn:
    """专业化自然语言 REPL：富文本回答、单行进度和友好错误。"""
    import json
    import logging
    import time
    from importlib.metadata import PackageNotFoundError, version
    from uuid import uuid4

    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text

    from mommy_chaogu.cli_prompt import ReplPrompt
    from mommy_chaogu.tui.widgets.tool_indicator import tool_display_name
    from mommy_chaogu.workflow.engine import WorkflowResult

    console = Console(highlight=False)
    provider = getattr(agent, "_provider", "") if agent is not None else ""
    model = getattr(agent, "_model", "") if agent is not None else ""
    model_label = str(model or "AI 未配置")
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

    def render_welcome() -> None:
        identity = f"{provider} / {model}" if provider and model else "AI 未配置"
        metadata = Table.grid(padding=(0, 1))
        metadata.add_column(style="bold")
        metadata.add_column()
        metadata.add_row("Directory:", cwd_full)
        metadata.add_row("Session:", session_id)
        metadata.add_row("Model:", identity)
        metadata.add_row("Version:", app_version)
        metadata.add_row(
            "Services:", "AI connected · market data ready" if agent else "market only"
        )
        welcome_content = metadata
        if console.size.width >= 72:
            logo = _render_logo()
            header = Table.grid(expand=True, padding=(0, 2))
            header.add_column(width=18, no_wrap=True)
            header.add_column(ratio=1)
            header.add_row(logo, metadata)
            welcome_content = header
        help_text = Text()
        help_text.append("\n直接输入问题，或使用 ", style="dim")
        help_text.append("/help", style="bold cyan")
        help_text.append(" 查看命令。", style="dim")
        console.print(
            Panel(
                welcome_content,
                title="[bold #7c5cff]Welcome to mommy-chaogu[/]",
                subtitle="[dim]你的本地 AI 投研助手[/]",
                border_style="#5bc0be",
                padding=(1, 2),
            )
        )
        console.print(help_text)

    def render_error(exc: Exception) -> None:
        message = str(exc)
        lowered = message.lower()
        if "rate_limit" in lowered or "429" in lowered:
            friendly = "API 调用频率超限，请稍后重试。"
        elif "quota" in lowered or "insufficient" in lowered:
            friendly = "API 额度已用完，请检查账户余额。"
        elif "authentication" in lowered or "401" in lowered:
            friendly = "API key 无效，请运行 `mommy setup` 重新配置。"
        else:
            friendly = "这次没能完成，请稍后重试。"
            if verbose:
                friendly += f"\n\n{type(exc).__name__}: {message}"
        console.print(Panel(friendly, title="[bold red]执行失败[/]", border_style="red"))

    def render_help() -> None:
        commands = Table.grid(padding=(0, 2))
        commands.add_column(style="bold cyan")
        commands.add_column()
        commands.add_row("/help", "查看命令")
        commands.add_row("/status", "查看会话、模型和服务状态")
        commands.add_row("/model", "查看当前 Provider 和模型")
        commands.add_row("/clear", "清空屏幕")
        commands.add_row("/tui", "查看全屏终端界面启动方式")
        commands.add_row("/web", "查看浏览器界面启动方式")
        commands.add_row("/quit", "退出")
        console.print(Panel(commands, title="命令", border_style="#4b5563"))

    render_welcome()

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
        command = user_input.lower()
        if command in {"q", "quit", "exit", "/q", "/quit", "/exit"}:
            console.print("[dim]再见。[/]")
            _flush_agent(agent)
            sys.exit(0)
        if command in {"help", "帮助", "?", "/help"}:
            render_help()
            continue
        if command in {"clear", "/clear"}:
            console.clear()
            render_welcome()
            continue
        if command == "/status":
            render_welcome()
            continue
        if command == "/model":
            console.print(f"[dim]当前模型：[/][bold]{provider or '?'} / {model_label}[/]")
            continue
        if command == "/tui":
            console.print("退出后运行 [bold]mommy tui[/] 可进入全屏终端界面。")
            continue
        if command == "/web":
            console.print("退出后运行 [bold]mommy web[/] 可启动浏览器界面。")
            continue

        route = router.route(user_input)  # type: ignore[attr-defined]
        started = time.monotonic()

        if route.matched:
            wf_desc = route.workflow.description  # type: ignore[attr-defined]
            current_step = wf_desc
            try:
                with console.status(f"[cyan]{current_step}[/]", spinner="dots") as status:

                    def on_start(name: str) -> None:
                        nonlocal current_step
                        current_step = name
                        status.update(f"[cyan]{name}[/]")

                    def on_done(name: str, ok: bool) -> None:
                        mark = "✓" if ok else "✗"
                        color = "green" if ok else "red"
                        status.update(f"[{color}]{mark}[/] {name}")

                    result: WorkflowResult = router.execute_route(  # type: ignore[attr-defined]
                        route,
                        user_input,
                        on_step_start=on_start,
                        on_step_done=on_done,
                    )
            except Exception as exc:
                render_error(exc)
                continue

            console.print()
            if result.summary:
                console.print(Markdown(result.summary))
            elif result.steps:
                _print_workflow_result(result)
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

        tool_names: list[str] = []
        failed_tools = 0
        verbose_events: list[str] = []
        tool_events: list[dict[str, object]] = []
        answer_chunks: list[str] = []
        activity = ["正在理解问题…"]

        def render_agent_activity(
            *,
            running: bool = True,
            _tool_events: list[dict[str, object]] = tool_events,
            _answer_chunks: list[str] = answer_chunks,
            _activity: list[str] = activity,
        ) -> Group:
            renderables: list[object] = []
            for event in _tool_events[-8:]:
                state = str(event["state"])
                if state == "running":
                    marker, style = "⏺", "cyan"
                elif state == "ok":
                    marker, style = "✓", "green"
                else:
                    marker, style = "✗", "red"
                row = Text()
                row.append(f"{marker} ", style=style)
                row.append(str(event["label"]))
                elapsed_ms = event.get("elapsed_ms")
                if elapsed_ms is not None:
                    row.append(f"  {int(elapsed_ms) / 1000:.1f}s", style="dim")
                renderables.append(row)
            if running and not _answer_chunks:
                renderables.append(Spinner("dots", Text(_activity[0], style="cyan")))
            if _answer_chunks:
                renderables.append(Markdown("".join(_answer_chunks)))
            if not renderables:
                renderables.append(Text(_activity[0], style="cyan"))
            return Group(*renderables)

        try:
            with Live(
                render_agent_activity(),
                console=console,
                refresh_per_second=12,
                vertical_overflow="visible",
            ) as live:

                def on_tool(
                    name: str,
                    args: dict[str, object],
                    _tool_names: list[str] = tool_names,
                    _verbose_events: list[str] = verbose_events,
                    _tool_events: list[dict[str, object]] = tool_events,
                    _activity: list[str] = activity,
                ) -> None:
                    display = tool_display_name(name)
                    _tool_names.append(display)
                    _activity[0] = f"{display}…"
                    _tool_events.append({"name": name, "label": display, "state": "running"})
                    live.update(render_agent_activity())
                    if verbose:
                        rendered_args = ", ".join(f"{key}={value}" for key, value in args.items())
                        _verbose_events.append(f"• {name}({rendered_args})")

                def on_tool_result(
                    name: str,
                    ok: bool,
                    elapsed_ms: int,
                    result: str,
                    _tool_events: list[dict[str, object]] = tool_events,
                ) -> None:
                    nonlocal failed_tools
                    actual_ok = ok
                    try:
                        payload = json.loads(result)
                        actual_ok = actual_ok and not (
                            isinstance(payload, dict) and "error" in payload
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass
                    if not actual_ok:
                        failed_tools += 1
                    for event in reversed(_tool_events):
                        if event["name"] == name and event["state"] == "running":
                            event["state"] = "ok" if actual_ok else "error"
                            event["elapsed_ms"] = elapsed_ms
                            break
                    live.update(render_agent_activity())

                def on_status(
                    kind: str,
                    data: dict[str, object],
                    _activity: list[str] = activity,
                ) -> None:
                    if kind == "retry":
                        attempt = data.get("attempt", "?")
                        _activity[0] = f"连接波动，正在重试（{attempt}）…"
                        live.update(render_agent_activity())

                def on_chunk(text: str, _answer_chunks: list[str] = answer_chunks) -> None:
                    _answer_chunks.append(text)
                    live.update(render_agent_activity())

                resp = agent.chat(
                    user_input,
                    on_tool_call=on_tool,
                    on_tool_result=on_tool_result,
                    on_chunk=on_chunk,
                    on_status=on_status,
                )
                if not answer_chunks and resp.text:
                    answer_chunks.append(resp.text)
                live.update(render_agent_activity(running=False), refresh=True)
        except KeyboardInterrupt:
            console.print("[yellow]■ 已中断当前任务。[/]")
            continue
        except Exception as exc:
            render_error(exc)
            continue

        if verbose and verbose_events:
            console.print(Panel("\n".join(verbose_events), title="执行详情", border_style="dim"))

        elapsed = time.monotonic() - started
        unique_tools = list(dict.fromkeys(tool_names))
        details = f" · {len(tool_names)} 次数据查询" if tool_names else ""
        if failed_tools:
            details += f" · [yellow]{failed_tools} 项未取到[/]"
        if verbose and unique_tools:
            details += f" · {', '.join(unique_tools)}"
        console.print(f"[dim]✓ 完成 · {elapsed:.1f}s{details}[/]")


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
    # 加载 .env 里的 API key（与 mommy-agent 的 load_config、TUI bootstrap
    # 对齐——主入口漏了这步时，只配 .env 的用户会被误报「未配置 API key」）。
    # 不覆盖已有的 shell 环境变量。
    from mommy_chaogu.config import load_runtime_env

    load_runtime_env()

    # 子命令 → 对应 main_* 函数 / entry point 的分发表
    # mommy watchlist list / mommy --raw watchlist list 共用同一张表
    dispatch: dict[str, tuple[str, object]] = {
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
            "可用子命令: watchlist, monitor, cache, semicon, flows, report, agent, memory, channel, connect, setup, web, tui, workflow"
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
    # 解析已知参数，剩余的忽略（避免 argparse 报错）
    args, _unknown = parser.parse_known_args()

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

    # 构建工具链
    from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import create_adapter_chain
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore
    from mommy_chaogu.workflow.engine import WorkflowExecutor, WorkflowRegistry
    from mommy_chaogu.workflow.definitions import get_default_registry
    from mommy_chaogu.workflow.router import NLRouter
    from mommy_chaogu.workflow.spec_runtime import spec_to_workflow
    from mommy_chaogu.workflow.store import WorkflowStore
    from mommy_chaogu.workflow.validator import blocking_issues, validate_spec

    base = create_adapter_chain()
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
            # vector_search 不显式传：AgentService 在 provider 有 embedding
            # 接口时自动装配，无接口时保持关键词降级
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
    merged_registry = WorkflowRegistry()
    for builtin in get_default_registry().all_workflows():
        merged_registry.register(builtin)
    workflow_store = WorkflowStore(AGENT_DB)
    for custom_spec, _meta in workflow_store.load_all():
        try:
            issues = validate_spec(custom_spec, existing_workflows=merged_registry.all_workflows())
            if blocking_issues(issues):
                continue
            if merged_registry.get(custom_spec.id) is None:
                merged_registry.register(spec_to_workflow(custom_spec))
        except (TypeError, ValueError):
            continue
    router = NLRouter(merged_registry, executor=executor)

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
            if result.workflow_id.startswith("user_") and result.succeeded:
                workflow_store.increment_hit(result.workflow_id)
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
                    "   运行 mommy setup 配置 Provider、模型和 API key。\n"
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
                    # P6：后台提取线程完成后再退出（单发模式唯一的消息轮次，
                    # 不 flush 进程退出时提取会被静默丢弃）
                    agent.flush(timeout=30)
                except Exception as e:
                    err_msg = str(e)
                    if "rate_limit" in err_msg.lower() or "429" in err_msg:
                        print("\n⚠️ API 调用频率超限，请稍后重试。\n")
                    elif "quota" in err_msg.lower() or "insufficient" in err_msg.lower():
                        print("\n⚠️ API 额度已用完，请检查账户余额。\n")
                    elif "authentication" in err_msg.lower() or "401" in err_msg:
                        print("\n⚠️ API key 无效，请运行 mommy setup 重新配置。\n")
                    else:
                        print(f"\n⚠️ 出错了: {e}\n")
        sys.exit(0)

    # 交互式 REPL
    _run_mommy_repl(
        router,
        executor,
        agent,
        verbose=args.verbose,
        workflow_hit_recorder=workflow_store.increment_hit,
    )


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
