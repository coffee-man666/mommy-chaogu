"""prompt_builder 单测：动态 system prompt 构建。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.prompt import SYSTEM_PROMPT
from mommy_chaogu.agent.prompt_builder import build_system_prompt


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test.db")


@pytest.fixture
def tracker(tmp_path: Path) -> PredictionTracker:
    return PredictionTracker(tmp_path / "test.db")


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
