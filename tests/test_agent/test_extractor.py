"""extractor 单测：事实抽取。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.extractor import extract_from_conversation, store_extraction
from mommy_chaogu.agent.prediction_tracker import PredictionTracker


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test.db")


@pytest.fixture
def tracker(tmp_path: Path) -> PredictionTracker:
    return PredictionTracker(tmp_path / "test.db")


def make_mock_llm(response_content: str) -> MagicMock:
    """构造 mock OpenAI client。"""
    client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = response_content
    client.chat.completions.create.return_value = mock_resp
    return client


VALID_RESPONSE = """\
{
  "observations": [
    {
      "event_type": "analysis_record",
      "scope": "stock:603662",
      "code": "603662",
      "name": "柯力传感",
      "summary": "主力5日净流入1.79亿，底部反转初期信号",
      "data": {"price": 80.0, "change_pct": 8.37},
      "data_coverage": {"quote": true, "flow_today": true, "flow_5d": false, "news": false},
      "confidence": 0.7,
      "tags": ["底部反转", "放量"]
    }
  ],
  "predictions": [
    {
      "code": "603662",
      "name": "柯力传感",
      "prediction": "底部反转初期，5日内看涨",
      "direction": "bullish",
      "timeframe": "5d",
      "target_price": 84.49,
      "rationale": "业绩催化+放量流入"
    }
  ]
}
"""

EMPTY_RESPONSE = '{"observations": [], "predictions": []}'

CODE_FENCE_RESPONSE = """\
```json
{
  "observations": [
    {
      "event_type": "analysis_record",
      "scope": "stock:600519",
      "code": "600519",
      "name": "贵州茅台",
      "summary": "现价1194，小幅回调",
      "data": {"price": 1194.0},
      "data_coverage": {"quote": true, "flow_today": false},
      "confidence": 0.6
    }
  ],
  "predictions": []
}
```
"""


class TestExtraction:
    def test_extract_valid(self, episodic: EpisodicMemory, tracker: PredictionTracker) -> None:
        """LLM 返回有效数据 → 正确存入。"""
        client = make_mock_llm(VALID_RESPONSE)

        result = extract_from_conversation("柯力传感怎么样", "涨了8%", client, "test-model")
        assert result is not None
        assert len(result["observations"]) == 1
        assert len(result["predictions"]) == 1

        store_extraction(result, episodic, tracker)

        events = episodic.query()
        assert len(events) == 1
        assert "底部反转" in events[0]["summary"]

        preds = tracker.all()
        assert len(preds) == 1
        assert preds[0]["code"] == "603662"
        assert preds[0]["direction"] == "bullish"

    def test_extract_empty(self) -> None:
        """LLM 返回空 → None。"""
        client = make_mock_llm(EMPTY_RESPONSE)

        result = extract_from_conversation("你好", "你好！", client, "test-model")
        assert result is None

    def test_extract_failure_graceful(self) -> None:
        """LLM 调用失败 → None，不崩溃。"""
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API timeout")

        result = extract_from_conversation("test", "test", client, "test-model")
        assert result is None

    def test_extract_invalid_json(self) -> None:
        """LLM 返回无效 JSON → None。"""
        client = make_mock_llm("这不是JSON")

        result = extract_from_conversation("test", "test", client, "test-model")
        assert result is None

    def test_code_fence_response(self) -> None:
        """LLM 返回带 ```json fence 的 JSON → 正确解析。"""
        client = make_mock_llm(CODE_FENCE_RESPONSE)

        result = extract_from_conversation("茅台怎么样", "1194元", client, "test-model")
        assert result is not None
        assert len(result["observations"]) == 1
        assert result["observations"][0]["code"] == "600519"


class TestStoreExtraction:
    def test_entry_price_auto_fill(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """adapter 有报价 → 自动填 entry_price。"""
        extraction = {
            "observations": [],
            "predictions": [
                {
                    "code": "603662",
                    "name": "柯力传感",
                    "prediction": "看涨",
                    "direction": "bullish",
                    "timeframe": "5d",
                }
            ],
        }

        adapter = MagicMock()
        quote = MagicMock()
        quote.price = 80.0
        quote.change_pct = 3.5
        adapter.get_quote.return_value = quote

        store_extraction(extraction, episodic, tracker, adapter=adapter)

        preds = tracker.all()
        assert len(preds) == 1
        assert preds[0]["entry_price"] == 80.0
        assert preds[0]["change_pct_at_creation"] == 3.5

    def test_no_adapter_no_entry_price(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """无 adapter → entry_price = None。"""
        extraction = {
            "observations": [],
            "predictions": [
                {
                    "code": "603662",
                    "prediction": "看涨",
                    "direction": "bullish",
                    "timeframe": "5d",
                }
            ],
        }

        store_extraction(extraction, episodic, tracker, adapter=None)

        preds = tracker.all()
        assert len(preds) == 1
        assert preds[0]["entry_price"] is None

    def test_data_coverage_stored(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """data_coverage 字段正确存入 episodic。"""
        extraction = {
            "observations": [
                {
                    "event_type": "analysis_record",
                    "scope": "stock:603662",
                    "code": "603662",
                    "summary": "底部反转",
                    "data": {"price": 80.0},
                    "data_coverage": {"quote": True, "flow_today": False},
                    "confidence": 0.8,
                }
            ],
            "predictions": [],
        }

        store_extraction(extraction, episodic, tracker)

        events = episodic.query()
        assert len(events) == 1
        assert events[0]["data_coverage"]["quote"] is True
        assert events[0]["data_coverage"]["flow_today"] is False

    def test_prediction_links_to_source_event(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """同 code 的 observation → prediction 的 source_event_id 正确关联。"""
        extraction = {
            "observations": [
                {
                    "event_type": "analysis_record",
                    "scope": "stock:603662",
                    "code": "603662",
                    "name": "柯力传感",
                    "summary": "底部反转",
                    "data": {"price": 80.0},
                    "confidence": 0.8,
                }
            ],
            "predictions": [
                {
                    "code": "603662",
                    "name": "柯力传感",
                    "prediction": "5日内看涨",
                    "direction": "bullish",
                    "timeframe": "5d",
                }
            ],
        }

        store_extraction(extraction, episodic, tracker)

        events = episodic.query(code="603662")
        assert len(events) == 1
        source_event_id = events[0]["id"]

        preds = tracker.all()
        assert len(preds) == 1
        assert preds[0]["source_event_id"] == source_event_id

    def test_prediction_no_source_event_when_no_observation(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """无对应 observation 时，prediction 的 source_event_id 为 None。"""
        extraction = {
            "observations": [],
            "predictions": [
                {
                    "code": "603662",
                    "prediction": "看涨",
                    "direction": "bullish",
                    "timeframe": "5d",
                }
            ],
        }

        store_extraction(extraction, episodic, tracker)

        preds = tracker.all()
        assert len(preds) == 1
        assert preds[0]["source_event_id"] is None

    def test_multiple_codes_traceability(
        self, episodic: EpisodicMemory, tracker: PredictionTracker
    ) -> None:
        """多 code 场景下，每条 prediction 关联到正确 code 的 observation。"""
        extraction = {
            "observations": [
                {
                    "event_type": "analysis_record",
                    "scope": "stock:603662",
                    "code": "603662",
                    "summary": "底部反转",
                    "data": {},
                },
                {
                    "event_type": "analysis_record",
                    "scope": "stock:600519",
                    "code": "600519",
                    "summary": "回调",
                    "data": {},
                },
            ],
            "predictions": [
                {
                    "code": "603662",
                    "prediction": "看涨",
                    "direction": "bullish",
                    "timeframe": "5d",
                },
                {
                    "code": "600519",
                    "prediction": "看跌",
                    "direction": "bearish",
                    "timeframe": "5d",
                },
            ],
        }

        store_extraction(extraction, episodic, tracker)

        events_603662 = episodic.query(code="603662")
        events_600519 = episodic.query(code="600519")
        assert len(events_603662) == 1
        assert len(events_600519) == 1

        preds = tracker.all()
        assert len(preds) == 2
        by_code = {p["code"]: p for p in preds}
        assert by_code["603662"]["source_event_id"] == events_603662[0]["id"]
        assert by_code["600519"]["source_event_id"] == events_600519[0]["id"]
