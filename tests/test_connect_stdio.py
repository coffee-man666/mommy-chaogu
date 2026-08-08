"""Real personal-profile MCP stdio acceptance test (network-free)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mommy_chaogu.agent.episodic_memory import EpisodicMemory


def _text(result: Any) -> dict[str, Any]:
    assert result.content
    return json.loads(result.content[0].text)


def test_personal_mcp_stdio_full_loop_without_llm_or_network(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    market_db = tmp_path / "market.db"
    portfolio_db = tmp_path / "portfolio.db"
    agent_db = tmp_path / "agent.db"
    reference_db = tmp_path / "reference.db"
    EpisodicMemory(agent_db).write(
        "analysis_record",
        "stock:600519",
        "stdio 预置历史事实",
        {},
        code="600519",
        name="贵州茅台",
        source="stdio-acceptance",
    )

    env = dict(os.environ)
    env.update(
        {
            "MOMMY_CONFIG_DIR": str(config_dir),
            "MOMMY_MARKET_DB": str(market_db),
            "MOMMY_PORTFOLIO_DB": str(portfolio_db),
            "MOMMY_AGENT_DB": str(agent_db),
            "MOMMY_REFERENCE_DB": str(reference_db),
            "MOMMY_OFFLINE_MARKET_DATA": "1",
            "PYTHONPATH": str(Path.cwd() / "src"),
        }
    )
    for key in (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "MOONSHOT_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "AGENT_PROVIDER",
        "AGENT_MODEL",
    ):
        env[key] = ""

    async def exercise() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mommy_chaogu.agent.mcp_server", "--profile", "personal"],
            env=env,
            cwd=str(Path.cwd()),
        )
        async with (
            stdio_client(params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "research_stock",
                "record_research_conclusion",
                "get_memory_context",
                "get_memory_health",
            } <= names

            research = _text(
                await session.call_tool("research_stock", {"code": "600519", "days": 5})
            )
            assert research["research_session_id"]
            assert research["memory_recorded"] is True
            assert any(
                event["event_type"] == "external_research_session"
                for event in EpisodicMemory(agent_db).query(code="600519", limit=20)
            )

            saved = _text(
                await session.call_tool(
                    "record_research_conclusion",
                    {
                        "summary": "stdio 结论可召回",
                        "scope": "stock",
                        "code": "600519",
                        "name": "贵州茅台",
                        "research_session_id": research["research_session_id"],
                        "idempotency_key": "stdio-conclusion-1",
                    },
                )
            )
            assert saved["saved"] is True
            recalled = _text(await session.call_tool("get_memory_context", {"query": "600519"}))
            context = recalled["context"]
            assert any(item["summary"] == "stdio 结论可召回" for item in context["recent_events"])
            assert context["retrieval_mode"] == "exact+keyword"

            health = _text(await session.call_tool("get_memory_health", {}))
            assert health["status"] in {"degraded", "ok"}
            assert health["retrieval_mode"] == "exact+keyword"
            assert "maintenance" in health

    asyncio.run(exercise())
