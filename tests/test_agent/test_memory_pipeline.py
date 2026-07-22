"""MemoryPipeline 单测：统一记忆管道 facade。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.semantic_memory import SemanticMemory


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test.db")


@pytest.fixture
def tracker(tmp_path: Path) -> PredictionTracker:
    return PredictionTracker(tmp_path / "test.db")


@pytest.fixture
def semantic(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path / "test.db")


def make_mock_client(
    response_content: str = '{"observations": [], "predictions": []}',
) -> MagicMock:
    """构造一个 mock OpenAI client，chat.completions.create 返回固定内容。"""
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = response_content
    client.chat.completions.create.return_value = resp
    return client


class TestBuildPrompt:
    def test_returns_string(self, episodic: EpisodicMemory, tracker: PredictionTracker) -> None:
        """build_prompt 返回字符串。"""
        pipe = MemoryPipeline(episodic, tracker, None)
        prompt = pipe.build_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_memory_when_present(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
        semantic: SemanticMemory,
    ) -> None:
        """有事件 / 知识时 prompt 包含注入的记忆段落。"""
        episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            code="603662",
            name="柯力传感",
            summary="底部放量反转",
            data={"price": 80.0},
        )
        semantic.upsert(
            knowledge_type="stock_insight",
            scope="stock:603662",
            content="柯力传感机器人传感器龙头",
            confidence=0.8,
        )

        pipe = MemoryPipeline(episodic, tracker, semantic)
        prompt = pipe.build_prompt(query="柯力传感")

        assert "柯力传感" in prompt
        assert "已有认知" in prompt or "近期事件" in prompt

    def test_all_none_returns_base_prompt(self) -> None:
        """所有组件 None 时返回基础 prompt（非空字符串）。"""
        pipe = MemoryPipeline(None, None, None)
        prompt = pipe.build_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestRecordAnalysis:
    def test_with_client_calls_extractor(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
    ) -> None:
        """有 client 时调用 extract_from_conversation + store_extraction。"""
        client = make_mock_client(
            response_content=(
                '{"observations": [{"event_type": "analysis_record", '
                '"scope": "stock:603662", "code": "603662", "name": "柯力传感", '
                '"summary": "底部放量", "data": {"price": 80.0}}], "predictions": []}'
            )
        )

        with (
            patch("mommy_chaogu.agent.memory_pipeline.extract_from_conversation") as mock_extract,
            patch("mommy_chaogu.agent.memory_pipeline.store_extraction") as mock_store,
        ):
            mock_extract.return_value = {"observations": [{"code": "603662"}], "predictions": []}
            pipe = MemoryPipeline(episodic, tracker, None, client=client, model="test-model")
            pipe.record_analysis("user msg", "assistant resp")

            mock_extract.assert_called_once_with("user msg", "assistant resp", client, "test-model")
            mock_store.assert_called_once()

    def test_no_client_skips(self, episodic: EpisodicMemory, tracker: PredictionTracker) -> None:
        """无 client 时跳过，不调 LLM。"""
        pipe = MemoryPipeline(episodic, tracker, None, client=None, model=None)

        with (
            patch("mommy_chaogu.agent.memory_pipeline.extract_from_conversation") as mock_extract,
            patch("mommy_chaogu.agent.memory_pipeline.store_extraction") as mock_store,
        ):
            pipe.record_analysis("user", "assistant")
            mock_extract.assert_not_called()
            mock_store.assert_not_called()

    def test_extraction_none_skips_store(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
    ) -> None:
        """extract 返回 None 时不调 store_extraction。"""
        client = make_mock_client()

        with (
            patch("mommy_chaogu.agent.memory_pipeline.extract_from_conversation") as mock_extract,
            patch("mommy_chaogu.agent.memory_pipeline.store_extraction") as mock_store,
        ):
            mock_extract.return_value = None
            pipe = MemoryPipeline(episodic, tracker, None, client=client, model="m")
            pipe.record_analysis("u", "a")

            mock_extract.assert_called_once()
            mock_store.assert_not_called()

    def test_extract_failure_silent(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
    ) -> None:
        """extract 抛异常时静默降级，不向上抛。"""
        client = make_mock_client()

        with patch(
            "mommy_chaogu.agent.memory_pipeline.extract_from_conversation",
            side_effect=Exception("API down"),
        ):
            pipe = MemoryPipeline(episodic, tracker, None, client=client, model="m")
            # 不抛异常
            pipe.record_analysis("u", "a")


class TestVerifyPredictions:
    def test_returns_stats(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
    ) -> None:
        """verify_predictions 返回统计 dict。"""
        adapter = MagicMock()
        adapter.get_quote.return_value = None

        pipe = MemoryPipeline(episodic, tracker, None)
        stats = pipe.verify_predictions(adapter)

        assert isinstance(stats, dict)
        assert "total" in stats
        assert "hit" in stats
        assert "missed" in stats
        assert stats["total"] == 0  # 空 tracker

    def test_no_tracker_returns_empty(self) -> None:
        """无 tracker 时返回空统计。"""
        pipe = MemoryPipeline(None, None, None)
        adapter = MagicMock()
        stats = pipe.verify_predictions(adapter)

        assert stats == {
            "total": 0,
            "hit": 0,
            "missed": 0,
            "data_unavailable": 0,
            "expired": 0,
            "unverifiable": 0,
        }


class TestConsolidate:
    def test_no_client_skips(self) -> None:
        """无 client 时 consolidate 直接跳过，不抛异常。"""
        pipe = MemoryPipeline(None, None, None, client=None, model=None)
        # 不抛
        pipe.consolidate()

    def test_with_client_calls_consolidator(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
        semantic: SemanticMemory,
    ) -> None:
        """有全部组件时调用 MemoryConsolidator.consolidate_all。"""
        client = make_mock_client(response_content="测试知识")

        with patch("mommy_chaogu.agent.memory_pipeline.MemoryConsolidator") as mock_cons_class:
            mock_instance = mock_cons_class.return_value
            pipe = MemoryPipeline(episodic, tracker, semantic, client=client, model="m")
            pipe.consolidate()

            mock_cons_class.assert_called_once_with(episodic, semantic, tracker, client, "m")
            mock_instance.consolidate_all.assert_called_once()

    def test_consolidator_failure_silent(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
        semantic: SemanticMemory,
    ) -> None:
        """consolidate_all 抛异常时静默降级。"""
        client = make_mock_client()

        with patch("mommy_chaogu.agent.memory_pipeline.MemoryConsolidator") as mock_cons_class:
            mock_cons_class.return_value.consolidate_all.side_effect = Exception("boom")
            pipe = MemoryPipeline(episodic, tracker, semantic, client=client, model="m")
            # 不抛
            pipe.consolidate()


class TestStats:
    def test_format(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
        semantic: SemanticMemory,
    ) -> None:
        """stats 返回正确格式与字段。"""
        episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            summary="事件A",
            data={},
        )
        tracker.create(
            code="603662", name="柯力传感", prediction="涨", direction="bullish", timeframe="5d"
        )
        semantic.upsert(
            knowledge_type="stock_insight",
            scope="stock:603662",
            content="龙头",
            confidence=0.8,
        )

        pipe = MemoryPipeline(episodic, tracker, semantic)
        snapshot = pipe.stats()

        assert snapshot["episodic_count"] == 1
        assert isinstance(snapshot["prediction_stats"], dict)
        assert snapshot["prediction_stats"]["total"] == 1
        assert snapshot["semantic_count"] == 1
        assert snapshot["insight_count"] == 0  # 没有 insight

    def test_insight_count(
        self,
        episodic: EpisodicMemory,
        tracker: PredictionTracker,
        semantic: SemanticMemory,
    ) -> None:
        """写入 insight_summary 后 insight_count 递增。"""
        semantic.save_insight(
            {
                "period_start": "2026-07-01",
                "period_end": "2026-07-05",
                "summary": "周复盘",
                "key_observations": ["观察1"],
                "predictions_reviewed": 0,
                "hit_rate": None,
                "confidence_adjustment": 0.0,
            }
        )

        pipe = MemoryPipeline(episodic, tracker, semantic)
        snapshot = pipe.stats()
        assert snapshot["insight_count"] == 1

    def test_all_none(self) -> None:
        """所有组件 None 时 stats 返回零值快照。"""
        pipe = MemoryPipeline(None, None, None)
        snapshot = pipe.stats()

        assert snapshot == {
            "episodic_count": 0,
            "prediction_stats": {},
            "semantic_count": 0,
            "insight_count": 0,
        }
