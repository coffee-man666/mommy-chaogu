"""MCP Server：把 agent 工具暴露为 MCP 协议。

任何支持 MCP 的客户端（🦞 / Claude Desktop / Kimi Code / 等）
都可以直接连接这个 server。默认 ``market-only`` 只开放公共行情；用户明确
选择 ``personal`` 后才开放按任务读取的个人上下文与写操作。

用法：
    # stdio 模式（最简单，Claude Desktop 等用）
    uv run mommy-mcp --profile personal

    # 在 Claude Desktop config.json 里配：
    {
      "mcpServers": {
        "mommy-chaogu": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/mommy-chaogu", "mommy-mcp",
                   "--profile", "market-only"]
        }
      }
    }
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any, cast

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    AudioContent,
    CallToolRequestParams,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    ListToolsResult,
    PaginatedRequestParams,
    ResourceLink,
    TextContent,
    Tool,
    ToolAnnotations,
)

from mommy_chaogu.agent.research_tools import (
    DEFAULT_MCP_PROFILE,
    WRITE_TOOL_NAMES,
    McpProfile,
    ResearchToolCatalog,
    allowed_base_tool_names,
    normalize_mcp_profile,
)
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

_log = logging.getLogger(__name__)

#: 空闲多久后自杀退出（秒）。宿主断开会话后不回收 stdio 子进程时，server
#: 自身是唯一能兜底的一方（实测泄漏 11+ 个进程、最老存活近 3 天）。
#: ``MOMMY_MCP_IDLE_TIMEOUT=0`` 可禁用。
DEFAULT_IDLE_TIMEOUT_S = 1800.0


def _resolve_idle_timeout(explicit: float | None = None) -> float:
    """空闲超时解析：显式参数 > 环境变量 > 默认 30 分钟；非法值回退默认。"""
    if explicit is not None:
        return max(0.0, explicit)
    raw = os.environ.get("MOMMY_MCP_IDLE_TIMEOUT", "").strip()
    if raw == "":
        return DEFAULT_IDLE_TIMEOUT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        _log.warning(
            "MOMMY_MCP_IDLE_TIMEOUT 非法（%r），回退默认 %.0fs", raw, DEFAULT_IDLE_TIMEOUT_S
        )
        return DEFAULT_IDLE_TIMEOUT_S


def _start_idle_watchdog(
    timeout_s: float,
    on_exit: Callable[[str], None],
) -> Callable[[], None]:
    """启动空闲看门狗线程，返回 touch（每次收到 MCP 请求时调用）。

    看门狗是独立 daemon 线程而非 asyncio task：event loop 在 shutdown 阶段会
    取消剩余 task，且线程池里卡死的网络 IO 会让 ``asyncio.run`` 的清理永远
    挂住——超时退出必须发生在 loop 生命周期之外。
    """
    last_activity = time.monotonic()

    def touch() -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

    def watch() -> None:
        while True:
            time.sleep(min(60.0, timeout_s))
            idle = time.monotonic() - last_activity
            if idle >= timeout_s:
                on_exit(f"idle {idle:.0f}s >= {timeout_s:.0f}s")
                return

    threading.Thread(target=watch, name="mommy-mcp-idle-watchdog", daemon=True).start()
    return touch


MCP_INSTRUCTIONS = """
mommy-chaogu is a local investing toolbox. The host Agent is the only reasoner; never call a second
project LLM. Prefer high-level research_* tools over recomposing primitives. Respect the active
privacy profile; never bypass MCP to read personal SQLite databases. Any write (saving a Strategy
Card, recording a conclusion) and any monitor activation requires explicit user consent. Separate
tool facts, Agent inference, and stale or missing data; do not claim a spec, backtest, or check
proves profitability.

Installation of this server only makes the toolbox reachable; it does not by itself complete an
investing or research goal. After a verified connection, invite free-form exploration across market
data, research, Strategy Cards, and monitoring. Do not force the user to pick a research, strategy,
indicator, or monitoring path before serving a request.

When the user defines an indicator or workflow, preserve its exact formula, inputs, time semantics,
and intent. Claim support only when published tools can compute every required part. Mark the rest
manual or unavailable; never replace it with a convenient proxy.

For Strategy Distillation, show a human-readable card before any write. Call strategy_save only
after the user explicitly asks to save the final card. Applying a card requires fresh research
evidence and a per-condition result of met, not met, or unknown. Never rewrite unsupported rules to
make them automatable. Preparing a monitor is read-only; strategy_activate_monitor requires a
separate, explicit user confirmation.
""".strip()


def _new_server(**callbacks: Any) -> Server:
    """Create a server with workflow instructions when the installed SDK supports them."""
    try:
        return Server("mommy-chaogu", instructions=MCP_INSTRUCTIONS, **callbacks)
    except TypeError:  # pragma: no cover - compatibility with older MCP 1.x builds
        return Server("mommy-chaogu", **callbacks)


def _build_llm() -> tuple[Any | None, str | None, str | None]:
    """容错地构造 LLM client，返回 (client, chat_model, embedding_model)。

    无可用 provider key / 构造失败时返回 (None, None, None)，
    调用方走降级路径。embedding_model 为 None 表示 provider 无
    embedding 接口（向量检索显式降级为关键词搜索）。
    """
    from mommy_chaogu.agent import llm
    from mommy_chaogu.config import load_runtime_env

    load_runtime_env()
    provider = llm.detect_provider()
    if provider is None:
        return None, None, None
    try:
        return (
            llm.create_client(provider),
            llm.resolve_model(provider),
            llm.embedding_model_for(provider),
        )
    except Exception as e:
        _log.warning("mcp: LLM client 构造失败，记忆工具走降级模式: %s", e)
        return None, None, None


def _build_context() -> ToolContext:
    """从项目默认配置构造 ToolContext（含记忆服务 + LLM client）。"""
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import create_adapter_chain
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    base = create_adapter_chain()
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)

    client, model, embedding_model = _build_llm()

    # 构造记忆服务（MCP 外部 agent 也能获得记忆注入）
    memory_service = _build_memory_service(client, model, embedding_model)

    return ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
        client=client,
        model=model,
        embedding_model=embedding_model,
        memory_service=memory_service,
    )


def _build_memory_service(
    client: Any | None = None,
    model: str | None = None,
    embedding_model: str | None = None,
) -> Any:
    """构造 MemoryService（用于 MCP 等非 AgentService 入口）。

    client 为 None（无 LLM key）时 pipeline 不带 LLM（get_context 仍可用，
    record_analysis 跳过提取）；embedding_model 非 None 时接向量检索。
    """
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.memory import ConversationMemory
    from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
    from mommy_chaogu.agent.memory_service import MemoryService
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.db_paths import AGENT_DB

    episodic = EpisodicMemory(AGENT_DB)
    tracker = PredictionTracker(AGENT_DB)
    semantic = SemanticMemory(AGENT_DB)
    memory = ConversationMemory(AGENT_DB)

    vector_search = None
    if client is not None and embedding_model is not None:
        from mommy_chaogu.agent.vector_search import VectorSearch

        try:
            vector_search = VectorSearch(episodic, client, model=embedding_model)
        except Exception as e:
            _log.warning("mcp: 向量检索初始化失败，降级关键词搜索: %s", e)

    pipeline = MemoryPipeline(
        episodic=episodic,
        tracker=tracker,
        semantic=semantic,
        vector_search=vector_search,
        client=client,
        model=model,
    )

    return MemoryService(pipeline=pipeline, memory=memory)


def create_mcp_server(
    ctx: ToolContext | None = None,
    *,
    profile: McpProfile | str = DEFAULT_MCP_PROFILE,
    touch: Callable[[], None] | None = None,
) -> Server:
    """创建 MCP Server 实例。

    Args:
        ctx: ToolContext（None 则用默认配置）
        profile: ``market-only`` 只开放公共行情；``personal`` 额外开放
            持仓、记忆和写操作。
        touch: 收到任何 MCP 请求时调用（空闲看门狗的活性信号）。
    """
    mark_activity = touch if touch is not None else (lambda: None)
    selected_profile = normalize_mcp_profile(profile)
    # Discovery must be cheap and read-only. Build database/data-source services
    # only when a tool is actually called, not during initialize/tools-list.
    runtime_ctx = ctx
    definition_ctx = ctx or ToolContext(adapter=None)  # type: ignore[arg-type]
    registry = ToolRegistry(definition_ctx)
    research = ResearchToolCatalog(definition_ctx, registry, selected_profile)
    allowed_base = allowed_base_tool_names(selected_profile)
    base_defs = [
        item for item in registry.definitions() if item["function"]["name"] in allowed_base
    ]
    research_defs = research.definitions()
    allowed_research = {tool.name for tool in research_defs}

    def _annotations(name: str) -> ToolAnnotations:
        auto_records_research = (
            selected_profile == "personal"
            and name in allowed_research
            and name != "record_research_conclusion"
        )
        is_write = name in WRITE_TOOL_NAMES or auto_records_research
        return ToolAnnotations(
            readOnlyHint=not is_write,
            destructiveHint=False,
            idempotentHint=not is_write,
            openWorldHint=name not in {"get_memory_context", "get_prediction_history"},
        )

    async def list_tools() -> list[Tool]:
        mark_activity()
        tools: list[Tool] = []
        for td in base_defs:
            fn = td["function"]
            tools.append(
                Tool(
                    name=fn["name"],
                    description=fn["description"],
                    inputSchema=fn["parameters"],
                    annotations=_annotations(fn["name"]),
                )
            )
        for tool_def in research_defs:
            tools.append(
                Tool(
                    name=tool_def.name,
                    description=tool_def.description,
                    inputSchema=tool_def.parameters,
                    annotations=_annotations(tool_def.name),
                )
            )
        return tools

    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        mark_activity()
        nonlocal runtime_ctx, registry, research
        if name not in allowed_base and name not in allowed_research:
            result = (
                '{"error":"该工具未在当前 MCP profile 中开放。'
                '如确需个人数据，请由用户重新连接并选择 personal。"}'
            )
            return [TextContent(type="text", text=result)]
        if runtime_ctx is None:
            runtime_ctx = _build_context()
            registry = ToolRegistry(runtime_ctx)
            research = ResearchToolCatalog(runtime_ctx, registry, selected_profile)
        # registry.call 里是同步阻塞网络 IO（行情拉取等），直接跑会把
        # 整个 MCP 会话的 event loop 卡死——挪到线程池执行。
        if name in allowed_base:
            result = await asyncio.to_thread(registry.call, name, arguments or {})
        else:
            result = await asyncio.to_thread(research.call, name, arguments or {})
        return [TextContent(type="text", text=result)]

    # MCP Python SDK 2.0 removed the low-level Server decorator API in favour
    # of constructor callbacks.  Keep both paths because installed uv tools
    # resolve dependencies independently: existing lockfiles can still use
    # MCP 1.x while a fresh ``uv tool install`` may resolve MCP 2.x.
    if hasattr(Server, "list_tools"):
        server = _new_server()
        server.list_tools()(list_tools)  # type: ignore[no-untyped-call]
        server.call_tool()(call_tool)
        return server

    async def on_list_tools(
        _request_context: Any,
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        return ListToolsResult(tools=await list_tools())

    async def on_call_tool(
        _request_context: Any,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        # list[TextContent] → SDK 的联合 content 类型：list 不变性需要显式宽化
        content = cast(
            "list[TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource]",
            await call_tool(params.name, params.arguments),
        )
        return CallToolResult(content=content)

    return _new_server(
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def run_stdio(
    profile: McpProfile | str = DEFAULT_MCP_PROFILE,
    *,
    idle_timeout_s: float | None = None,
) -> None:
    """stdio 模式启动（MCP 标准 transport）。

    idle_timeout_s 覆盖空闲看门狗超时（None 时读 MOMMY_MCP_IDLE_TIMEOUT，
    默认 30 分钟；0 禁用）——宿主断开会话后不回收本子进程时自杀退出。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    selected_profile = normalize_mcp_profile(profile)
    timeout_s = _resolve_idle_timeout(idle_timeout_s)
    touch: Callable[[], None] | None = None
    if timeout_s > 0:

        def bail(reason: str) -> None:
            _log.warning(
                "mommy-chaogu MCP server 空闲退出（%s）——宿主未回收的 stdio 子进程兜底", reason
            )
            logging.shutdown()
            os._exit(0)

        touch = _start_idle_watchdog(timeout_s, bail)
    server = create_mcp_server(profile=selected_profile, touch=touch)
    async with stdio_server() as (read_stream, write_stream):
        _log.info(
            "mommy-chaogu MCP server started (profile=%s, idle_timeout=%.0fs)",
            selected_profile,
            timeout_s,
        )
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main_mcp() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(prog="mommy-mcp", description="mommy-chaogu MCP server")
    parser.add_argument(
        "--profile",
        choices=("market-only", "personal"),
        default=os.environ.get("MOMMY_MCP_PROFILE", DEFAULT_MCP_PROFILE),
        help="隐私权限：market-only（默认）或 personal",
    )
    args = parser.parse_args()
    asyncio.run(run_stdio(args.profile))


if __name__ == "__main__":
    main_mcp()
