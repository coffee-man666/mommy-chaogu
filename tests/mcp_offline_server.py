"""Test-only stdio entry point with deterministic injected market dependencies."""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent import mcp_server
from mommy_chaogu.agent.tools import ToolContext
from mommy_chaogu.agent.tools import intel as intel_tools
from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
from mommy_chaogu.portfolio.store import PortfolioStore
from mommy_chaogu.watchlist.store import WatchlistStore
from tests.offline_market_adapter import OfflineMarketDataAdapter


def _fundamentals(code: str) -> dict[str, Any]:
    return {
        "code": code,
        "name": "离线测试标的",
        "pe": 20.0,
        "pb": 3.0,
        "ps": 5.0,
        "roe": 15.0,
        "gross_margin": 40.0,
        "net_margin": 20.0,
        "total_market_cap": 1_000_000_000_000,
        "circulating_market_cap": 800_000_000_000,
        "industry": "离线测试行业",
    }


def _build_test_context() -> ToolContext:
    client, model, embedding_model = mcp_server._build_llm()
    return ToolContext(
        adapter=CachedMarketDataAdapter(OfflineMarketDataAdapter(), CacheStore(MARKET_DB)),
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
        client=client,
        model=model,
        embedding_model=embedding_model,
        memory_service=mcp_server._build_memory_service(client, model, embedding_model),
    )


def main() -> None:
    # Injection lives in the test process; the installed MCP server has no
    # environment switch capable of returning fixture market data.
    mcp_server._build_context = _build_test_context
    intel_tools.get_fundamentals = _fundamentals
    mcp_server.main_mcp()


if __name__ == "__main__":
    main()
