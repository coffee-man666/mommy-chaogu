"""mommy REPL 的渲染与交互组件。

从 :func:`mommy_chaogu.cli._run_mommy_repl` 拆出的展示层：

- 欢迎卡 / 帮助 / 错误面板渲染（``ReplUI``）
- 斜杠命令处理（q / help / clear / status / model / tui / web）
- agent 流式 Live 视图与工具事件回调（``AgentLiveView`` + ``run_agent_chat``）
- 工作流路由执行与无 LLM 总结时的结果打印

本模块保持 ``mypy --strict``；Textual 依赖（tool_display_name）延迟导入，
避免非 TUI 入口背上重依赖。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from mommy_chaogu.agent.service import ChatCallbacks
from mommy_chaogu.errors import friendly_error
from mommy_chaogu.workflow.engine import WorkflowResult
from mommy_chaogu.workflow.router import NLRouter, RouteResult

if TYPE_CHECKING:
    from mommy_chaogu.agent.service import AgentService

# ---------- logo（量化终端风） ----------

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

# 退出命令集合（REPL 主循环据此 flush 后退场）
EXIT_COMMANDS = frozenset({"q", "quit", "exit", "/q", "/quit", "/exit"})


def render_logo() -> Text:
    """量化终端风 logo：紫→青水平渐变的块体 M + 红绿迷你 K 线。"""
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


# ---------- 会话上下文与 UI ----------


@dataclass(frozen=True, slots=True)
class ReplContext:
    """REPL 欢迎卡展示的会话元信息。"""

    provider: str
    model_label: str
    identity: str
    cwd_full: str
    session_id: str
    app_version: str
    has_agent: bool


class ReplUI:
    """REPL 的静态渲染与斜杠命令处理。"""

    def __init__(self, console: Console, ctx: ReplContext) -> None:
        self.console = console
        self.ctx = ctx

    def welcome(self) -> None:
        ctx = self.ctx
        metadata = Table.grid(padding=(0, 1))
        metadata.add_column(style="bold")
        metadata.add_column()
        metadata.add_row("Directory:", ctx.cwd_full)
        metadata.add_row("Session:", ctx.session_id)
        metadata.add_row("Model:", ctx.identity)
        metadata.add_row("Version:", ctx.app_version)
        metadata.add_row(
            "Services:", "AI connected · market data ready" if ctx.has_agent else "market only"
        )
        welcome_content: Table = metadata
        if self.console.size.width >= 72:
            logo = render_logo()
            header = Table.grid(expand=True, padding=(0, 2))
            header.add_column(width=18, no_wrap=True)
            header.add_column(ratio=1)
            header.add_row(logo, metadata)
            welcome_content = header
        help_text = Text()
        help_text.append("\n直接输入问题，或使用 ", style="dim")
        help_text.append("/help", style="bold cyan")
        help_text.append(" 查看命令。", style="dim")
        self.console.print(
            Panel(
                welcome_content,
                title="[bold #7c5cff]Welcome to mommy-chaogu[/]",
                subtitle="[dim]你的本地 AI 投研助手[/]",
                border_style="#5bc0be",
                padding=(1, 2),
            )
        )
        self.console.print(help_text)

    def error(self, exc: Exception, verbose: bool) -> None:
        friendly = friendly_error(exc)
        if verbose:
            friendly += f"\n\n{type(exc).__name__}: {exc}"
        self.console.print(Panel(friendly, title="[bold red]执行失败[/]", border_style="red"))

    def help_panel(self) -> None:
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
        self.console.print(Panel(commands, title="命令", border_style="#4b5563"))

    def handle_command(self, user_input: str) -> bool:
        """处理斜杠/快捷命令；命中并处理返回 True，调用方应跳过路由。

        注意：退出命令只负责打印再见，flush 与 sys.exit 由主循环完成。
        """
        ctx = self.ctx
        command = user_input.lower()
        if command in EXIT_COMMANDS:
            self.console.print("[dim]再见。[/]")
            return True
        if command in {"help", "帮助", "?", "/help"}:
            self.help_panel()
            return True
        if command in {"clear", "/clear"}:
            self.console.clear()
            self.welcome()
            return True
        if command == "/status":
            self.welcome()
            return True
        if command == "/model":
            self.console.print(
                f"[dim]当前模型：[/][bold]{ctx.provider or '?'} / {ctx.model_label}[/]"
            )
            return True
        if command == "/tui":
            self.console.print("退出后运行 [bold]mommy tui[/] 可进入全屏终端界面。")
            return True
        if command == "/web":
            self.console.print("退出后运行 [bold]mommy web[/] 可启动浏览器界面。")
            return True
        return False


# ---------- 工作流路由 ----------


def run_workflow_route(
    console: Console,
    router: NLRouter,
    route: RouteResult,
    user_input: str,
) -> WorkflowResult:
    """执行命中的工作流（带 spinner 进度），异常向上抛给调用方。"""
    assert route.workflow is not None  # matched 路由必然带 workflow
    current_step = route.workflow.description
    with console.status(f"[cyan]{current_step}[/]", spinner="dots") as status:

        def on_start(name: str) -> None:
            nonlocal current_step
            current_step = name
            status.update(f"[cyan]{name}[/]")

        def on_done(name: str, ok: bool) -> None:
            mark = "✓" if ok else "✗"
            color = "green" if ok else "red"
            status.update(f"[{color}]{mark}[/] {name}")

        return router.execute_route(
            route,
            user_input,
            on_step_start=on_start,
            on_step_done=on_done,
        )


def print_workflow_result(result: WorkflowResult) -> None:
    """没有 LLM 总结时，简单格式化输出工作流结果。"""
    for sr in result.steps:
        if not sr.success:
            continue
        print(f"**{sr.display_name}**")
        data = sr.data
        if isinstance(data, dict):
            # 尝试提取关键字段
            if "indexes" in data:
                for idx in data["indexes"][:6]:
                    if isinstance(idx, dict):
                        name = idx.get("name", "?")
                        price = idx.get("price", "?")
                        chg = idx.get("change_pct", 0)
                        sign = "+" if chg and chg >= 0 else ""
                        print(
                            f"  {name}: {price} ({sign}{chg:.2f}%)" if chg else f"  {name}: {price}"
                        )
            elif "sectors" in data:
                sectors = data["sectors"][:5]
                for s in sectors:
                    if isinstance(s, dict):
                        print(f"  {s.get('name', '?')}: {s.get('change_pct', '?')}%")
            elif "stocks" in data:
                stocks = data["stocks"][:10]
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


# ---------- agent 流式对话 ----------


@dataclass(slots=True)
class AgentTurnStats:
    """单轮 agent 对话的统计（供调用方打 footer）。"""

    tool_names: list[str] = field(default_factory=list)
    failed_tools: int = 0
    verbose_events: list[str] = field(default_factory=list)


class AgentLiveView:
    """agent 流式 Live 视图：工具事件行 + 回答 Markdown 的实时渲染。"""

    def __init__(self) -> None:
        self.activity = ["正在理解问题…"]
        self.tool_events: list[dict[str, object]] = []
        self.answer_chunks: list[str] = []
        self.stats = AgentTurnStats()

    def renderables(self, *, running: bool = True) -> Group:
        renderables: list[RenderableType] = []
        for event in self.tool_events[-8:]:
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
            if isinstance(elapsed_ms, (int, float)):
                row.append(f"  {elapsed_ms / 1000:.1f}s", style="dim")
            renderables.append(row)
        if running and not self.answer_chunks:
            renderables.append(Spinner("dots", Text(self.activity[0], style="cyan")))
        if self.answer_chunks:
            renderables.append(Markdown("".join(self.answer_chunks)))
        if not renderables:
            renderables.append(Text(self.activity[0], style="cyan"))
        return Group(*renderables)


def run_agent_chat(
    console: Console,
    agent: AgentService,
    user_input: str,
    verbose: bool,
) -> AgentTurnStats:
    """跑一轮 agent 流式对话（Live 渲染 + 工具回调统计）。

    KeyboardInterrupt 与其他异常向上抛，由 REPL 主循环统一处理。
    """
    view = AgentLiveView()
    stats = view.stats

    with Live(
        view.renderables(),
        console=console,
        refresh_per_second=12,
        vertical_overflow="visible",
    ) as live:

        def on_tool(name: str, args: dict[str, object]) -> None:
            # Textual 依赖重，非 TUI 入口延迟导入
            from mommy_chaogu.tui.widgets.tool_indicator import tool_display_name

            display = tool_display_name(name)
            stats.tool_names.append(display)
            view.activity[0] = f"{display}…"
            view.tool_events.append({"name": name, "label": display, "state": "running"})
            live.update(view.renderables())
            if verbose:
                rendered_args = ", ".join(f"{key}={value}" for key, value in args.items())
                stats.verbose_events.append(f"• {name}({rendered_args})")

        def on_tool_result(name: str, ok: bool, elapsed_ms: int, result: str) -> None:
            actual_ok = ok
            try:
                payload = json.loads(result)
                actual_ok = actual_ok and not (isinstance(payload, dict) and "error" in payload)
            except (json.JSONDecodeError, TypeError):
                pass
            if not actual_ok:
                stats.failed_tools += 1
            for event in reversed(view.tool_events):
                if event["name"] == name and event["state"] == "running":
                    event["state"] = "ok" if actual_ok else "error"
                    event["elapsed_ms"] = elapsed_ms
                    break
            live.update(view.renderables())

        def on_status(kind: str, data: dict[str, object]) -> None:
            if kind == "retry":
                attempt = data.get("attempt", "?")
                view.activity[0] = f"连接波动，正在重试（{attempt}）…"
                live.update(view.renderables())

        def on_chunk(text: str) -> None:
            view.answer_chunks.append(text)
            live.update(view.renderables())

        resp = agent.chat(
            user_input,
            callbacks=ChatCallbacks(
                on_tool_call=on_tool,
                on_tool_result=on_tool_result,
                on_chunk=on_chunk,
                on_status=on_status,
            ),
        )
        if not view.answer_chunks and resp.text:
            view.answer_chunks.append(resp.text)
        live.update(view.renderables(running=False), refresh=True)

    return stats
