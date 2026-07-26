"""MCP Server：把 agent 工具暴露为 MCP 协议。

任何支持 MCP 的客户端（🦞 / Claude Desktop / Kimi Code / 等）
都可以直接连接这个 server，调用 25 个数据工具。

用法：
    # stdio 模式（最简单，Claude Desktop 等用）
    uv run mommy-mcp

    # 在 Claude Desktop config.json 里配：
    {
      "mcpServers": {
        "mommy-chaogu": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/mommy-chaogu", "mommy-mcp"]
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

_log = logging.getLogger(__name__)


def _build_llm() -> tuple[Any | None, str | None, str | None]:
    """容错地构造 LLM client，返回 (client, chat_model, embedding_model)。

    无可用 provider key / 构造失败时返回 (None, None, None)，
    调用方走降级路径。embedding_model 为 None 表示 provider 无
    embedding 接口（向量检索显式降级为关键词搜索）。
    """
    from mommy_chaogu.agent import llm

    provider = llm.detect_provider()
    if provider is None:
        return None, None, None
    try:
        config = llm.provider_config(provider)
        return (
            llm.create_client(provider),
            str(config["default_model"]),
            llm.embedding_model_for(provider),
        )
    except Exception as e:
        _log.warning("mcp: LLM client 构造失败，记忆工具走降级模式: %s", e)
        return None, None, None


def _build_context() -> ToolContext:
    """从项目默认配置构造 ToolContext（含记忆服务 + LLM client）。"""
    from mommy_chaogu.cache import CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import build_default_adapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    store = CacheStore(MARKET_DB)
    adapter = build_default_adapter(with_cache=True, cache_store=store)

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


def create_mcp_server(ctx: ToolContext | None = None) -> Server:
    """创建 MCP Server 实例。

    Args:
        ctx: ToolContext（None 则用默认配置）
    """
    if ctx is None:
        ctx = _build_context()

    registry = ToolRegistry(ctx)
    server = Server("mommy-chaogu")

    # 把 ToolDef 转成 MCP Tool 格式
    tool_defs = registry.definitions()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []
        for td in tool_defs:
            fn = td["function"]
            tools.append(
                Tool(
                    name=fn["name"],
                    description=fn["description"],
                    inputSchema=fn["parameters"],
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # registry.call 里是同步阻塞网络 IO（行情拉取等），直接跑会把
        # 整个 MCP 会话的 event loop 卡死——挪到线程池执行。
        result = await asyncio.to_thread(registry.call, name, arguments or {})
        return [TextContent(type="text", text=result)]

    return server


async def run_stdio() -> None:
    """stdio 模式启动（MCP 标准 transport）。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    ctx = _build_context()
    server = create_mcp_server(ctx)
    async with stdio_server() as (read_stream, write_stream):
        _log.info("mommy-chaogu MCP server started (25 tools)")
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main_mcp() -> None:
    """CLI 入口。"""
    asyncio.run(run_stdio())
