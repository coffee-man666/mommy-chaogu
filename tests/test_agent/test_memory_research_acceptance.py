"""Acceptance tests for the personal-memory research loop.

These tests use the real SQLite stores, context service, research catalog and
memory pipeline.  Only the market adapter is deterministic fixture data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
from mommy_chaogu.agent.memory_service import MemoryService
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.research_context import ResearchContextService
from mommy_chaogu.agent.research_tools import ResearchToolCatalog
from mommy_chaogu.agent.semantic_memory import SemanticMemory
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
from mommy_chaogu.market_data.offline_adapter import OfflineMarketDataAdapter
from mommy_chaogu.portfolio.store import PortfolioStore
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.watchlist.store import WatchlistStore


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("MOMMY_OFFLINE_MARKET_DATA", "1")
    agent_db = tmp_path / "agent.db"
    portfolio_db = tmp_path / "portfolio.db"
    market_db = tmp_path / "market.db"
    portfolio = PortfolioStore(portfolio_db)
    watchlist = WatchlistStore(portfolio_db)
    group = watchlist.add_group("研究池")
    assert group.name == "研究池"
    watchlist.add_entry("600519", "研究池", note="核心仓，等待业绩验证")
    watchlist.add_entry("000001", "研究池", note="另一只股票，不应泄漏")
    position = portfolio.add_position("600519", "贵州茅台", Decimal("1700"), 100)
    portfolio.add_adjustment(position.id, "buy", Decimal("1750"), 50, note="突破加仓")
    portfolio.add_adjustment(position.id, "sell", Decimal("1800"), 20, note="减仓锁盈")
    other = portfolio.add_position("000001", "平安银行", Decimal("10"), 1000)
    portfolio.add_adjustment(other.id, "buy", Decimal("11"), 100)
    CustomAlertStore(portfolio_db).add("600519", "贵州茅台", "price_below", Decimal("1600"))
    CustomAlertStore(portfolio_db).add("000001", "平安银行", "price_below", Decimal("8"))
    return {
        "agent": agent_db,
        "portfolio": portfolio_db,
        "market": market_db,
        "portfolio_store": portfolio,
        "watchlist_store": watchlist,
    }


def _memory_context(stores: dict[str, Any]) -> ResearchContextService:
    return ResearchContextService(
        stores["agent"],
        portfolio_store=stores["portfolio_store"],
        watchlist_store=stores["watchlist_store"],
        portfolio_db=stores["portfolio"],
    )


def _catalog(stores: dict[str, Any]) -> ResearchToolCatalog:
    episodic = EpisodicMemory(stores["agent"])
    tracker = PredictionTracker(stores["agent"])
    semantic = SemanticMemory(stores["agent"])
    memory_service = MemoryService(MemoryPipeline(episodic, tracker, semantic))
    ctx = ToolContext(
        adapter=CachedMarketDataAdapter(OfflineMarketDataAdapter(), CacheStore(stores["market"])),
        watchlist_store=stores["watchlist_store"],
        portfolio_store=stores["portfolio_store"],
        agent_db=stores["agent"],
        market_db=stores["market"],
        portfolio_db=stores["portfolio"],
        memory_service=memory_service,
    )
    return ResearchToolCatalog(ctx, ToolRegistry(ctx), "personal")


def _seed_history(stores: dict[str, Any]) -> None:
    episodic = EpisodicMemory(stores["agent"])
    episodic.write(
        "analysis_record",
        "stock:600519",
        "贵州茅台估值回归但基本面稳定",
        {"kind": "history"},
        code="600519",
        name="贵州茅台",
        source="acceptance",
    )
    episodic.write(
        "analysis_record",
        "stock:000001",
        "平安银行资产质量观察",
        {"kind": "other"},
        code="000001",
        name="平安银行",
        source="acceptance",
    )
    tracker = PredictionTracker(stores["agent"])
    tracker.create(
        "600519",
        "贵州茅台",
        "未来反弹",
        "up",
        "5d",
        rationale="估值和资金流改善",
    )
    tracker.create("000001", "平安银行", "继续震荡", "neutral", "5d", rationale="另一标的")
    semantic = SemanticMemory(stores["agent"])
    semantic.upsert("stock_insight", "stock:600519", "贵州茅台是高端白酒龙头", confidence=0.9)
    semantic.upsert("stock_insight", "stock:000001", "平安银行是银行股", confidence=0.8)


def test_first_stock_research_returns_complete_scoped_personal_context(
    stores: dict[str, Any],
) -> None:
    _seed_history(stores)
    context = _memory_context(stores).get(query="600519 贵州茅台")

    assert context["subject"] == {"type": "stock", "code": "600519"}
    assert context["position"] == {
        "code": "600519",
        "name": "贵州茅台",
        "shares": 130,
        "average_cost": "1716.6667",
        "lots": 1,
    }
    assert context["watchlist"]["notes"] == ["核心仓，等待业绩验证"]
    assert [item["code"] for item in context["alerts"]] == ["600519"]
    assert all(item.get("code") in {None, "600519"} for item in context["recent_events"])
    assert all(item["code"] == "600519" for item in context["predictions"])
    assert all(item["scope"] == "stock:600519" for item in context["semantic_knowledge"])
    encoded = json.dumps(context, ensure_ascii=False)
    assert "平安银行" not in encoded
    assert context["retrieval_mode"] == "exact+keyword"

    # Exercise the high-level workflow against the same real stores and fixture adapter.
    payload = json.loads(_catalog(stores).call("research_stock", {"code": "600519", "days": 5}))
    assert payload["research_session_id"]
    personal_evidence = next(
        item for item in payload["evidence"] if item["tool"] == "get_memory_context"
    )
    assert personal_evidence["ok"] is True
    assert personal_evidence["data"]["context"]["subject"]["code"] == "600519"


def test_conclusion_writeback_is_idempotent_and_recalled(stores: dict[str, Any]) -> None:
    catalog = _catalog(stores)
    args = {
        "summary": "结论：现金流稳定，回撤后仍值得跟踪",
        "scope": "stock",
        "code": "600519",
        "name": "贵州茅台",
        "research_session_id": "session-acceptance-1",
        "idempotency_key": "acceptance-conclusion-1",
        "analysis_type": "stock-research",
    }
    first = json.loads(catalog.call("record_research_conclusion", args))
    second = json.loads(catalog.call("record_research_conclusion", args))
    assert first["saved"] is True
    assert first.get("reused") is not True
    assert second["reused"] is True
    assert second["event_id"] == first["event_id"]
    events = EpisodicMemory(stores["agent"]).query(code="600519", limit=50)
    assert [event for event in events if event["id"] == first["event_id"]].__len__() == 1
    recalled = _memory_context(stores).get(code="600519")
    assert any(item["summary"] == args["summary"] for item in recalled["recent_events"])


def test_prediction_creation_verification_and_feedback_loop(stores: dict[str, Any]) -> None:
    catalog = _catalog(stores)
    result = json.loads(
        catalog.call(
            "record_research_conclusion",
            {
                "summary": "短期趋势向上，等待价格确认",
                "scope": "stock",
                "code": "600519",
                "name": "贵州茅台",
                "prediction": "未来上涨",
                "direction": "up",
                "timeframe": "1d",
                "rationale": "离线确定性证据显示价格高于入场价",
                "entry_price": 1700,
                "idempotency_key": "acceptance-prediction-1",
            },
        )
    )
    prediction_id = result["prediction_id"]
    assert prediction_id is not None
    tracker = PredictionTracker(stores["agent"])
    prediction = tracker.get_by_id(prediction_id)
    assert prediction is not None
    assert prediction["source_event_id"] == result["event_id"]
    with tracker.engine.begin() as conn:
        conn.execute(
            text("UPDATE predictions SET verify_after = :due WHERE id = :id"),
            {"due": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(), "id": prediction_id},
        )

    episodic = EpisodicMemory(stores["agent"])
    pipeline = MemoryPipeline(episodic, tracker, SemanticMemory(stores["agent"]))
    maintenance = pipeline.maintain(adapter=OfflineMarketDataAdapter())
    assert maintenance["verification"]["total"] == 1
    assert maintenance["verification"]["hit"] == 1
    verified = tracker.get_by_id(prediction_id)
    assert verified is not None and verified["status"] == "hit"
    verification_events = episodic.query(code="600519", limit=50)
    assert any(event["prediction_id"] == prediction_id for event in verification_events)
    recalled = _memory_context(stores).get(code="600519")
    assert any(
        item["id"] == prediction_id and item["status"] == "hit" for item in recalled["predictions"]
    )
    health = pipeline.health()
    assert health["maintenance"]["prediction_verification"]["status"] == "ok"


def test_memory_health_status_matrix_and_observability(stores: dict[str, Any]) -> None:
    assert MemoryService().health() == {"status": "disabled", "retrieval_mode": "disabled"}
    episodic = EpisodicMemory(stores["agent"])
    tracker = PredictionTracker(stores["agent"])
    semantic = SemanticMemory(stores["agent"])
    episodic.write("acceptance", "stock:600519", "健康矩阵写入证据", {}, code="600519")
    degraded = MemoryPipeline(episodic, tracker, semantic)
    context = _memory_context(stores).get(code="600519")
    assert context["retrieval_mode"] == "exact+keyword"
    degraded_health = degraded.health()
    assert degraded_health["status"] == "degraded"
    assert degraded_health["last_read_at"] is not None
    assert degraded_health["last_write_at"] is not None
    assert "maintenance" in degraded_health

    episodic.record_maintenance("embedding", status="failed", error="fixture failure")
    failed_health = MemoryPipeline(episodic, tracker, semantic).health()
    assert failed_health["status"] == "failed"
    assert "embedding" in failed_health["reason"]

    clean_db = stores["agent"].with_name("ok-agent.db")
    ok_episodic = EpisodicMemory(clean_db)
    ok_tracker = PredictionTracker(clean_db)
    ok_semantic = SemanticMemory(clean_db)
    ok_health = MemoryPipeline(
        ok_episodic, ok_tracker, ok_semantic, client=object(), model="fixture"
    ).health()
    assert ok_health["status"] == "ok"
    assert ok_health["retrieval_mode"] == "exact+keyword"
