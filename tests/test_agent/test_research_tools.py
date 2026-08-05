from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.agent.research_tools import (
    MARKET_ONLY_BASE_TOOLS,
    ResearchToolCatalog,
    allowed_research_tool_names,
    normalize_mcp_profile,
)
from mommy_chaogu.agent.tools.base import ToolContext


class FakeRegistry:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append((name, args))
        value = self.results.get(name, {"source": name})
        return json.dumps(value, ensure_ascii=False)


def _catalog(
    profile: str = "market-only",
    *,
    results: dict[str, Any] | None = None,
    agent_db: Path | None = None,
) -> tuple[ResearchToolCatalog, FakeRegistry]:
    registry = FakeRegistry(results)
    ctx = ToolContext(adapter=None, agent_db=agent_db)  # type: ignore[arg-type]
    catalog = ResearchToolCatalog(ctx, registry, normalize_mcp_profile(profile))  # type: ignore[arg-type]
    return catalog, registry


def test_profiles_default_to_public_market_data() -> None:
    assert normalize_mcp_profile(None) == "market-only"
    assert "get_portfolio" not in MARKET_ONLY_BASE_TOOLS
    assert "get_memory_context" not in MARKET_ONLY_BASE_TOOLS
    assert allowed_research_tool_names("market-only") == {
        "research_market_brief",
        "research_us_market",
        "research_stock",
        "research_sector",
        "research_money_flow",
    }
    assert "record_research_conclusion" in allowed_research_tool_names("personal")
    with pytest.raises(ValueError, match="market-only"):
        normalize_mcp_profile("everything")


def test_stock_research_returns_evidence_without_personal_memory() -> None:
    catalog, registry = _catalog()
    result = json.loads(catalog.call("research_stock", {"code": "600519", "days": 20}))

    assert result["research_type"] == "stock"
    assert result["profile"] == "market-only"
    assert [item["tool"] for item in result["evidence"]] == [
        "get_quote",
        "get_bars",
        "get_money_flow_today",
        "get_money_flow_history",
        "get_fundamentals",
    ]
    assert all(name != "get_memory_context" for name, _ in registry.calls)


def test_us_market_brief_queries_indexes() -> None:
    catalog, registry = _catalog()
    result = json.loads(catalog.call("research_us_market", {}))

    assert result["research_type"] == "us_market_brief"
    assert result["profile"] == "market-only"
    assert result["subject"]["indexes"] == ["^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX"]
    assert [item["tool"] for item in result["evidence"]] == [
        "get_quote",
        "get_quote",
        "get_quote",
        "get_quote",
        "get_quote",
    ]
    codes = [args["code"] for name, args in registry.calls if name == "get_quote"]
    assert codes == ["^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX"]


def test_personal_stock_research_includes_memory_first() -> None:
    catalog, registry = _catalog("personal")
    result = json.loads(catalog.call("research_stock", {"code": "600519"}))

    assert result["evidence"][0]["tool"] == "get_memory_context"
    assert registry.calls[0] == ("get_memory_context", {"query": "600519"})


def test_sector_research_chains_board_code() -> None:
    catalog, registry = _catalog(
        results={"search_sector": [{"board_code": "BK0475", "name": "半导体"}]}
    )
    result = json.loads(catalog.call("research_sector", {"keyword": "半导体", "limit": 8}))

    assert result["subject"]["board_code"] == "BK0475"
    assert (
        "get_sector_stocks",
        {"board_code": "BK0475", "limit": 8, "sort_by": "change_pct"},
    ) in registry.calls


def test_market_profile_rejects_personal_tool() -> None:
    catalog, _ = _catalog()
    result = json.loads(catalog.call("research_portfolio", {}))
    assert "error" in result
    assert "personal" in result["hint"]


def test_personal_profile_records_conclusion_and_prediction(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    catalog, _ = _catalog("personal", agent_db=db_path)
    result = json.loads(
        catalog.call(
            "record_research_conclusion",
            {
                "summary": "量价配合，但资金强度仍需观察",
                "scope": "stock",
                "code": "600519",
                "name": "贵州茅台",
                "confidence": 0.7,
                "prediction": "未来 5 日偏强",
                "direction": "up",
                "timeframe": "5d",
                "rationale": "放量上涨",
                "entry_price": 1680,
            },
        )
    )

    assert result["saved"] is True
    assert result["event_id"] > 0
    assert result["prediction_id"] > 0

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    events = EpisodicMemory(db_path).query(code="600519")
    prediction = PredictionTracker(db_path).get_by_id(result["prediction_id"])
    assert events[0]["source"] == "mcp-external-agent"
    assert prediction is not None
    assert prediction["direction"] == "up"


def test_invalid_prediction_does_not_partially_write_event(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    catalog, _ = _catalog("personal", agent_db=db_path)
    result = json.loads(
        catalog.call(
            "record_research_conclusion",
            {
                "summary": "待验证结论",
                "scope": "stock",
                "code": "600519",
                "prediction": "偏强",
                "direction": "up",
                "timeframe": "forever",
            },
        )
    )
    assert "error" in result

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    assert EpisodicMemory(db_path).query() == []
