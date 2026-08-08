"""MCP Server：把 agent 工具暴露为 MCP 协议。

任何支持 MCP 的客户端（🦞 / Claude Desktop / Kimi Code / 等）
都可以直接连接这个 server。默认 ``personal`` profile 开放按任务读取的
个人上下文；显式 ``market-only`` 才只开放公共行情。

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
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
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
    from mommy_chaogu.market_data.offline_adapter import OfflineMarketDataAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    # Explicitly opt-in fixture used by offline subprocess smoke tests.  It is
    # intentionally environment-gated so production keeps the normal adapter chain.
    base = (
        OfflineMarketDataAdapter()
        if os.environ.get("MOMMY_OFFLINE_MARKET_DATA") == "1"
        else create_adapter_chain()
    )
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
) -> Server:
    """创建 MCP Server 实例。

    Args:
        ctx: ToolContext（None 则用默认配置）
        profile: ``market-only`` 只开放公共行情；``personal`` 额外开放
            持仓、记忆和写操作。
    """
    if ctx is None:
        ctx = _build_context()

    selected_profile = normalize_mcp_profile(profile)
    registry = ToolRegistry(ctx)
    research = ResearchToolCatalog(ctx, registry, selected_profile)
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
        if name not in allowed_base and name not in allowed_research:
            result = (
                '{"error":"该工具未在当前 MCP profile 中开放。'
                '如确需个人数据，请由用户重新连接并选择 personal。"}'
            )
            return [TextContent(type="text", text=result)]
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
        server = Server("mommy-chaogu")
        server.list_tools()(list_tools)  # type: ignore[attr-defined]
        server.call_tool()(call_tool)  # type: ignore[attr-defined]
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
        return CallToolResult(content=await call_tool(params.name, params.arguments))

    return Server(
        "mommy-chaogu",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )  # type: ignore[call-overload]


async def run_stdio(profile: McpProfile | str = DEFAULT_MCP_PROFILE) -> None:
    """stdio 模式启动（MCP 标准 transport）。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    selected_profile = normalize_mcp_profile(profile)
    ctx = _build_context()
    server = create_mcp_server(ctx, profile=selected_profile)
    async with stdio_server() as (read_stream, write_stream):
        _log.info("mommy-chaogu MCP server started (profile=%s)", selected_profile)
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main_mcp() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(prog="mommy-mcp", description="mommy-chaogu MCP server")
    parser.add_argument(
        "--profile",
        choices=("market-only", "personal"),
        default=os.environ.get("MOMMY_MCP_PROFILE", DEFAULT_MCP_PROFILE),
        help="隐私权限：personal（默认）或 market-only",
    )
    args = parser.parse_args()
    asyncio.run(run_stdio(args.profile))


if __name__ == "__main__":
    main_mcp()
