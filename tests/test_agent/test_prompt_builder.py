"""prompt_builder 单测：动态 system prompt 构建。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.prompt import SYSTEM_PROMPT
from mommy_chaogu.agent.prompt_builder import build_system_prompt
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


class TestBuildPromptEmpty:
    def test_empty_returns_base_prompt(self) -> None:
        """无任何数据时返回原始 SYSTEM_PROMPT。"""
        prompt = build_system_prompt()
        assert prompt == SYSTEM_PROMPT

    def test_empty_episodic(self, episodic: EpisodicMemory) -> None:
        """空 episodic 返回原始 prompt。"""
        prompt = build_system_prompt(episodic=episodic)
        assert prompt == SYSTEM_PROMPT

    def test_empty_tracker(self, tracker: PredictionTracker) -> None:
        """空 tracker 返回原始 prompt。"""
        prompt = build_system_prompt(tracker=tracker)
        assert prompt == SYSTEM_PROMPT

    def test_both_empty(self, episodic: EpisodicMemory, tracker: PredictionTracker) -> None:
        """两者都空返回原始 prompt。"""
        prompt = build_system_prompt(episodic=episodic, tracker=tracker)
        assert prompt == SYSTEM_PROMPT


class TestBuildPromptWithEvents:
    def test_with_events(self, episodic: EpisodicMemory) -> None:
        """有事件时包含 ## 近期事件。"""
        episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            code="603662",
            name="柯力传感",
            summary="主力5日净流入1.79亿，底部反转",
            data={"price": 80.0},
        )

        prompt = build_system_prompt(episodic=episodic)
        assert "## 近期事件" in prompt
        assert "底部反转" in prompt
        assert prompt.startswith(SYSTEM_PROMPT[:50])  # base 保留

    def test_with_predictions(self, tracker: PredictionTracker) -> None:
        """有验证结果时包含 ## 最近判断回顾。"""

        pred_id = tracker.create(
            code="603662",
            name="柯力传感",
            prediction="底部反转看涨",
            direction="bullish",
            timeframe="5d",
        )

        # 模拟已验证
        tracker.update_status(
            pred_id,
            status="hit",
            actual_price=82.5,
            actual_change_pct=3.1,
            accuracy_score=0.7,
        )

        prompt = build_system_prompt(tracker=tracker)
        assert "## 最近判断回顾" in prompt
        assert "柯力传感" in prompt
        assert "✅" in prompt

    def test_full(self, episodic: EpisodicMemory, tracker: PredictionTracker) -> None:
        """两者都有 → 两部分都包含。"""
        episodic.write(
            event_type="market_snapshot",
            scope="market",
            summary="上证 4043 +0.37%",
            data={},
        )

        pred_id = tracker.create(
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
        )
        tracker.update_status(pred_id, status="hit", accuracy_score=0.7)

        prompt = build_system_prompt(episodic=episodic, tracker=tracker)
        assert "## 近期事件" in prompt
        assert "## 最近判断回顾" in prompt


class TestBuildPromptWithInsight:
    def test_empty_semantic_no_insight(self, semantic: SemanticMemory) -> None:
        """空 semantic 不注入复盘段落。"""
        prompt = build_system_prompt(semantic=semantic)
        assert prompt == SYSTEM_PROMPT

    def test_with_insight(self, semantic: SemanticMemory) -> None:
        """有 insight_summary 时注入 ## 最近复盘。"""
        semantic.save_insight(
            {
                "period_start": "2026-06-23",
                "period_end": "2026-06-29",
                "summary": "本周复盘：4 条预测命中 3 条",
                "key_observations": ["半导体板块走强", "消费板块走弱"],
                "predictions_reviewed": 4,
                "hit_rate": 0.75,
            }
        )

        prompt = build_system_prompt(semantic=semantic)
        assert "## 最近复盘（2026-06-23 ~ 2026-06-29）" in prompt
        assert "本周复盘：4 条预测命中 3 条" in prompt
        assert "半导体板块走强" in prompt
        assert prompt.startswith(SYSTEM_PROMPT[:50])

    def test_insight_before_knowledge(self, semantic: SemanticMemory) -> None:
        """insight 段落在已有认知之前。"""
        semantic.upsert("sector_thesis", "sector:创新药", "创新药上行")
        semantic.save_insight(
            {
                "period_start": "2026-06-23",
                "period_end": "2026-06-29",
                "summary": "复盘",
            }
        )

        prompt = build_system_prompt(semantic=semantic)
        insight_pos = prompt.find("## 最近复盘")
        knowledge_pos = prompt.find("## 已有认知")
        assert insight_pos != -1
        assert knowledge_pos != -1
        assert insight_pos < knowledge_pos

    def test_no_insight_falls_back_to_knowledge_only(
        self, semantic: SemanticMemory
    ) -> None:
        """semantic 有知识但无 insight → 只注入已有认知，不报错。"""
        semantic.upsert("sector_thesis", "sector:创新药", "创新药上行")

        prompt = build_system_prompt(semantic=semantic)
        assert "## 最近复盘" not in prompt
        assert "## 已有认知" in prompt


def _make_mock_vector_search(results: list[dict[str, object]] | None = None) -> MagicMock:
    """构造一个 mock VectorSearch，search_similar 返回固定结果。"""
    vs = MagicMock()
    vs.search_similar.return_value = results if results is not None else []
    return vs


class TestBuildPromptVectorSearch:
    def test_injects_similar_events(self) -> None:
        """有 vector_search + query 时注入 ## 相似历史事件。"""
        results = [
            {
                "id": 1,
                "timestamp": "2026-06-10T10:00:00",
                "scope": "sector:半导体",
                "summary": "半导体板块暴跌，主力大幅流出",
                "distance": 0.12,
            },
            {
                "id": 2,
                "timestamp": "2026-05-01T09:30:00",
                "scope": "stock:603662",
                "summary": "柯力传感底部放量反弹",
                "distance": 0.45,
            },
        ]
        vs = _make_mock_vector_search(results)

        prompt = build_system_prompt(query="半导体暴跌", vector_search=vs)

        assert "## 相似历史事件" in prompt
        assert "半导体板块暴跌" in prompt
        assert "柯力传感底部放量反弹" in prompt
        vs.search_similar.assert_called_once_with("半导体暴跌", top_k=3)

    def test_no_vector_search_no_injection(self) -> None:
        """vector_search 为 None 时不注入（向后兼容）。"""
        prompt = build_system_prompt(query="半导体暴跌")
        assert "## 相似历史事件" not in prompt
        assert prompt == SYSTEM_PROMPT

    def test_vector_search_without_query_no_injection(self) -> None:
        """只有 vector_search 没有 query 时不注入。"""
        vs = _make_mock_vector_search([])
        prompt = build_system_prompt(vector_search=vs)
        assert "## 相似历史事件" not in prompt
        vs.search_similar.assert_not_called()

    def test_empty_results_no_injection(self) -> None:
        """search_similar 返回空列表时不注入。"""
        vs = _make_mock_vector_search([])
        prompt = build_system_prompt(query="半导体暴跌", vector_search=vs)
        assert "## 相似历史事件" not in prompt

    def test_search_similar_raises_graceful_degrade(self) -> None:
        """search_similar 抛异常时优雅降级，不注入。"""
        vs = MagicMock()
        vs.search_similar.side_effect = RuntimeError("sqlite-vec not installed")

        # 不应抛异常
        prompt = build_system_prompt(query="半导体暴跌", vector_search=vs)

        assert "## 相似历史事件" not in prompt
        # 仍返回合法 prompt
        assert prompt.startswith(SYSTEM_PROMPT[:50])

    def test_vector_search_with_other_sections(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """向量检索与其他段落共存。"""
        episodic.write(
            event_type="market_snapshot",
            scope="market",
            summary="上证 4043 +0.37%",
            data={},
        )
        pred_id = tracker.create(
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
        )
        tracker.update_status(pred_id, status="hit", accuracy_score=0.7)

        vs = _make_mock_vector_search(
            [
                {
                    "id": 1,
                    "timestamp": "2026-06-10T10:00:00",
                    "scope": "sector:半导体",
                    "summary": "半导体暴跌",
                    "distance": 0.1,
                }
            ]
        )

        prompt = build_system_prompt(
            episodic=episodic,
            tracker=tracker,
            query="半导体",
            vector_search=vs,
        )
        assert "## 近期事件" in prompt
        assert "## 最近判断回顾" in prompt
        assert "## 相似历史事件" in prompt
