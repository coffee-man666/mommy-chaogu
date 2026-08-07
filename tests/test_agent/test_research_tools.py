from __future__ import annotations

import hashlib
import json
import threading
from decimal import Decimal
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
    adapter: Any | None = None,
    memory_service: Any | None = None,
) -> tuple[ResearchToolCatalog, FakeRegistry]:
    registry = FakeRegistry(results)
    ctx = ToolContext(
        adapter=adapter,
        agent_db=agent_db,
        memory_service=memory_service,
    )  # type: ignore[arg-type]
    catalog = ResearchToolCatalog(ctx, registry, normalize_mcp_profile(profile))  # type: ignore[arg-type]
    return catalog, registry


def test_profiles_default_to_personal_but_keep_public_profile() -> None:
    assert normalize_mcp_profile(None) == "personal"
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


def test_personal_stock_research_supports_single_call_opt_out(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    catalog, registry = _catalog("personal", agent_db=db_path)
    result = json.loads(
        catalog.call(
            "research_stock",
            {
                "code": "600519",
                "use_personal_context": False,
                "record_session": False,
            },
        )
    )

    assert result["memory_recorded"] is False
    assert all(name != "get_memory_context" for name, _ in registry.calls)
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    assert EpisodicMemory(db_path).query() == []


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
    assert prediction["source_event_id"] == result["event_id"]


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


def test_successful_personal_research_records_fact_session(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    catalog, _ = _catalog("personal", agent_db=db_path)
    result = json.loads(catalog.call("research_stock", {"code": "600519"}))

    assert result["memory_recorded"] is True
    assert result["research_session_id"]
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    events = EpisodicMemory(db_path).query(code="600519")
    assert len(events) == 1
    assert events[0]["event_type"] == "external_research_session"
    assert events[0]["data"]["research_session_id"] == result["research_session_id"]


def test_conclusion_write_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    catalog, _ = _catalog("personal", agent_db=db_path)
    args = {
        "summary": "量价配合",
        "scope": "stock",
        "code": "600519",
        "prediction": "未来 5 日偏强",
        "direction": "up",
        "timeframe": "5d",
        "idempotency_key": "turn-1",
    }
    first = json.loads(catalog.call("record_research_conclusion", args))
    second = json.loads(catalog.call("record_research_conclusion", args))

    assert first["saved"] is True
    assert second["reused"] is True
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    assert len(EpisodicMemory(db_path).query(code="600519")) == 1
    assert len(PredictionTracker(db_path).by_code("600519")) == 1


def test_idempotent_retry_repairs_missing_prediction(tmp_path: Path) -> None:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    db_path = tmp_path / "agent.db"
    key = "turn-after-event-commit"
    content_hash = hashlib.sha256(f"research-conclusion:{key}".encode()).hexdigest()
    episodic = EpisodicMemory(db_path)
    event_id = episodic.write(
        event_type="external_research",
        scope="stock:600519",
        summary="量价配合",
        data={},
        code="600519",
        content_hash=content_hash,
    )
    catalog, _ = _catalog("personal", agent_db=db_path)

    result = json.loads(
        catalog.call(
            "record_research_conclusion",
            {
                "summary": "量价配合",
                "scope": "stock",
                "code": "600519",
                "prediction": "未来 5 日偏强",
                "direction": "up",
                "timeframe": "5d",
                "idempotency_key": key,
            },
        )
    )

    assert result["event_id"] == event_id
    assert result["prediction_id"] > 0
    assert len(episodic.query(code="600519")) == 1
    assert len(PredictionTracker(db_path).by_code("600519")) == 1


def test_structured_context_uses_exact_code_scope_without_embedding(tmp_path: Path) -> None:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.research_context import ResearchContextService

    db_path = tmp_path / "agent.db"
    episodic = EpisodicMemory(db_path)
    episodic.write("analysis_record", "stock:600519", "贵州茅台走势偏强", {}, code="600519")
    episodic.write(
        "analysis_record", "stock:000519", "其他股票摘要包含 600519 数字", {}, code="000519"
    )

    context = ResearchContextService(db_path).get(query="600519")

    assert context["retrieval_mode"] == "exact+keyword"
    assert [item["code"] for item in context["recent_events"]] == ["600519"]
    assert episodic.maintenance_status()["memory_read"]["status"] == "ok"


def test_structured_context_aggregates_current_cost_basis(tmp_path: Path) -> None:
    from mommy_chaogu.agent.research_context import ResearchContextService
    from mommy_chaogu.portfolio.store import PortfolioStore

    agent_db = tmp_path / "agent.db"
    portfolio_db = tmp_path / "portfolio.db"
    store = PortfolioStore(portfolio_db)
    first = store.add_position("600519", "贵州茅台", Decimal("100"), 10)
    store.add_adjustment(first.id, "buy", Decimal("200"), 10)
    store.add_position("600519", "贵州茅台", Decimal("300"), 10)

    context = ResearchContextService(
        agent_db,
        portfolio_store=store,
        portfolio_db=portfolio_db,
    ).get(query="600519")

    assert context["position"] == {
        "code": "600519",
        "name": "贵州茅台",
        "shares": 30,
        "average_cost": "200.0000",
        "lots": 2,
    }


def test_structured_context_recognizes_us_ticker_position(tmp_path: Path) -> None:
    from mommy_chaogu.agent.research_context import ResearchContextService
    from mommy_chaogu.portfolio.store import PortfolioStore

    store = PortfolioStore(tmp_path / "portfolio.db")
    store.add_position("AAPL", "Apple", Decimal("180"), 5)

    context = ResearchContextService(
        tmp_path / "agent.db",
        portfolio_store=store,
    ).get(query="分析 AAPL")

    assert context["subject"] == {"type": "stock", "code": "AAPL"}
    assert context["position"]["shares"] == 5


def test_personal_research_schedules_daily_maintenance_once(tmp_path: Path) -> None:
    class FakeMemoryService:
        def __init__(self) -> None:
            self.finished = threading.Event()
            self.calls = 0

        def maintain(self, adapter: Any) -> dict[str, Any]:
            self.calls += 1
            self.finished.set()
            return {"status": "degraded", "consolidation": "deferred_no_llm"}

    memory_service = FakeMemoryService()
    catalog, _ = _catalog(
        "personal",
        agent_db=tmp_path / "agent.db",
        adapter=object(),
        memory_service=memory_service,
    )

    json.loads(catalog.call("research_stock", {"code": "600519"}))
    assert memory_service.finished.wait(timeout=2)
    memory_service.finished.clear()
    json.loads(catalog.call("research_stock", {"code": "600519"}))

    assert memory_service.calls == 1
    assert not memory_service.finished.wait(timeout=0.05)
