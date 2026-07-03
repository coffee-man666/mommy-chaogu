"""consolidator 单测：语义记忆提炼。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.consolidator import MemoryConsolidator
from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.semantic_memory import SemanticMemory


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test.db")


@pytest.fixture
def semantic(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path / "test.db")


@pytest.fixture
def tracker(tmp_path: Path) -> PredictionTracker:
    return PredictionTracker(tmp_path / "test.db")


def make_mock_client(response_text: str = "测试知识内容") -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = response_text
    client.chat.completions.create.return_value = resp
    return client


class TestConsolidateSectorTheses:
    def test_with_events(self, episodic: EpisodicMemory, semantic: SemanticMemory) -> None:
        """有事件时提炼板块叙事。"""
        for i in range(3):
            episodic.write(
                event_type="analysis_record",
                scope="stock:603662",
                code="603662",
                name="柯力传感",
                summary=f"第{i + 1}天：底部放量",
                data={"price": 80 + i},
            )

        client = make_mock_client("柯力传感底部反转，机器人传感器龙头")
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")

        results = cons.consolidate_all()
        assert results["sector_theses"] >= 1

        knowledge = semantic.query(scope="stock:603662")
        assert len(knowledge) == 1
        assert knowledge[0]["knowledge_type"] == "stock_insight"
        assert knowledge[0]["status"] == "active"

    def test_too_few_events(self, episodic: EpisodicMemory, semantic: SemanticMemory) -> None:
        """事件太少（<2）不提炼。"""
        episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            code="603662",
            summary="只有一条",
            data={},
        )

        client = make_mock_client()
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        assert results["sector_theses"] == 0


class TestConsolidateMarketRegime:
    def test_with_market_events(self, episodic: EpisodicMemory, semantic: SemanticMemory) -> None:
        """有 market scope 事件时判断市场状态。"""
        for i in range(3):
            episodic.write(
                event_type="market_snapshot",
                scope="market",
                summary=f"上证 +{i}%",
                data={},
            )

        client = make_mock_client("震荡上行，小盘成长占优")
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        assert results["market_regime"] == 1
        regime = semantic.query(knowledge_type="market_regime")
        assert len(regime) == 1

    def test_no_market_events(self, episodic: EpisodicMemory, semantic: SemanticMemory) -> None:
        """无 market 事件不判断。"""
        episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            summary="个股事件",
            data={},
        )

        client = make_mock_client()
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        assert results["market_regime"] == 0


class TestConsolidatePatterns:
    def test_with_enough_predictions(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        tracker: PredictionTracker,
    ) -> None:
        """有足够预测时归纳规律。"""
        for i in range(6):
            pid = tracker.create(
                code=f"00000{i}",
                name=f"股票{i}",
                prediction="看涨",
                direction="bullish",
                timeframe="5d",
            )
            tracker.update_status(pid, status="hit" if i < 4 else "missed", accuracy_score=0.8)

        client = make_mock_client("flow_signal 类 bullish 预测命中率 67%")
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        assert results["patterns"] == 1
        patterns = semantic.query(knowledge_type="pattern_observed")
        assert len(patterns) == 1

    def test_too_few_predictions(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        tracker: PredictionTracker,
    ) -> None:
        """预测太少不归纳。"""
        tracker.create(
            code="000001", name="A", prediction="涨", direction="bullish", timeframe="5d"
        )

        client = make_mock_client()
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        assert results["patterns"] == 0


class TestConsolidateAll:
    def test_all_failures_graceful(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        tracker: PredictionTracker,
    ) -> None:
        """LLM 全部失败不崩溃。"""
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API down")

        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        # 所有步骤都应该返回 0，不抛异常
        assert results["sector_theses"] == 0
        assert results["market_regime"] == 0
        assert results["patterns"] == 0

    def test_empty_db(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        tracker: PredictionTracker,
    ) -> None:
        """空库不崩溃。"""
        client = make_mock_client()
        cons = MemoryConsolidator(episodic, semantic, tracker, client, "test-model")
        results = cons.consolidate_all()

        assert results["sector_theses"] == 0
        assert results["market_regime"] == 0
        assert results["patterns"] == 0


class TestUpsertSupersede:
    def test_upsert_supersedes_old(self, semantic: SemanticMemory) -> None:
        """同 type+scope 的 upsert 会 supersede 旧的。"""
        semantic.upsert("market_regime", "market", "牛市", confidence=0.8)
        semantic.upsert("market_regime", "market", "转熊市", confidence=0.7)

        active = semantic.get_active()
        assert len(active) == 1
        assert "熊市" in active[0]["content"]

        all_entries = semantic.query(status=None)
        assert len(all_entries) == 2  # 旧的 superseded + 新的 active
