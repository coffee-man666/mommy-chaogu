"""narrative 单测：市场脉络生成。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.narrative import MarketNarrative


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test.db")


def make_mock_client(response_text: str = "测试叙述文本") -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = response_text
    client.chat.completions.create.return_value = resp
    return client


def seed_events(episodic: EpisodicMemory, n: int = 5) -> None:
    """写入 n 个测试事件。"""
    for i in range(n):
        episodic.write(
            event_type="analysis_record",
            scope="market",
            code="603662",
            name="柯力传感",
            summary=f"第{i + 1}天：柯力传感涨了{i}%",
            data={"price": 80 + i},
            tags=["test"],
        )


class TestGenerateNarrative:
    def test_with_events(self, episodic: EpisodicMemory) -> None:
        """有事件时调用 LLM 生成叙述。"""
        seed_events(episodic, 5)
        client = make_mock_client("过去5天柯力传感持续上涨")

        nar = MarketNarrative(episodic, client, "test-model")
        text = nar.generate_narrative(days=30)

        assert "柯力传感" in text or "持续上涨" in text
        client.chat.completions.create.assert_called_once()

    def test_no_events(self, episodic: EpisodicMemory) -> None:
        """无事件时返回提示。"""
        client = make_mock_client()

        nar = MarketNarrative(episodic, client, "test-model")
        text = nar.generate_narrative(days=30)

        assert "没有" in text
        client.chat.completions.create.assert_not_called()

    def test_llm_failure_graceful(self, episodic: EpisodicMemory) -> None:
        """LLM 调用失败不崩溃。"""
        seed_events(episodic, 2)
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API error")

        nar = MarketNarrative(episodic, client, "test-model")
        text = nar.generate_narrative(days=30)

        assert "失败" in text


class TestDetectChanges:
    def test_with_data(self, episodic: EpisodicMemory) -> None:
        """有数据时检测变化。"""
        seed_events(episodic, 5)
        client = make_mock_client("风格从防守转向进攻")

        nar = MarketNarrative(episodic, client, "test-model")
        text = nar.detect_changes()

        assert "风格" in text or "进攻" in text
        client.chat.completions.create.assert_called_once()

    def test_no_data(self, episodic: EpisodicMemory) -> None:
        """无数据时返回提示。"""
        client = make_mock_client()

        nar = MarketNarrative(episodic, client, "test-model")
        text = nar.detect_changes()

        assert "不足" in text
        client.chat.completions.create.assert_not_called()


class TestComparePeriods:
    def test_compare(self, episodic: EpisodicMemory) -> None:
        """对比两个时间段。"""
        # 写一些事件（都在今天）
        episodic.write(event_type="analysis_record", scope="market", summary="今天的事件", data={})
        episodic.write(event_type="signal_event", scope="market", summary="信号", data={})

        nar = MarketNarrative(episodic, make_mock_client(), "test-model")
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = nar.compare_periods("market", today, "2026-06-01")

        assert result["date1"] == today
        assert result["date1_events"] >= 0
        assert result["date2_events"] == 0  # 6/1 没数据

    def test_compare_empty(self, episodic: EpisodicMemory) -> None:
        """空库对比。"""
        nar = MarketNarrative(episodic, make_mock_client(), "test-model")
        result = nar.compare_periods("market", "2026-07-01", "2026-07-02")

        assert result["date1_events"] == 0
        assert result["date2_events"] == 0
