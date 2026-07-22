"""MCP Server：把 agent 工具暴露为 MCP 协议。

任何支持 MCP 的客户端（🦞 / Claude Desktop / Kimi Code / 等）
都可以直接连接这个 server，调用 14 个数据工具。

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

import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

_log = logging.getLogger(__name__)


def _build_context() -> ToolContext:
    """从项目默认配置构造 ToolContext（含记忆服务）。"""
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)

    # 构造记忆服务（MCP 外部 agent 也能获得记忆注入）
    memory_service = _build_memory_service()

    return ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
        memory_service=memory_service,
    )


def _build_memory_service() -> Any:
    """构造 MemoryService（用于 MCP 等非 AgentService 入口）。

    如果 LLM API key 未配置，pipeline 不带 client（get_context 仍可用，
    record_analysis 会跳过 LLM 提取）。
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

    pipeline = MemoryPipeline(
        episodic=episodic,
        tracker=tracker,
        semantic=semantic,
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
        result = registry.call(name, arguments or {})
        return [TextContent(type="text", text=result)]

    return server


async def run_stdio() -> None:
    """stdio 模式启动（MCP 标准 transport）。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    ctx = _build_context()
    server = create_mcp_server(ctx)
    async with stdio_server() as (read_stream, write_stream):
        _log.info("mommy-chaogu MCP server started (24 tools)")
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main_mcp() -> None:
    """CLI 入口。"""
    import asyncio

    asyncio.run(run_stdio())
