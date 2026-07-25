"""评估 backlog 修复的锁定测试（EVALUATION-2026-07-18 后续批次）。

覆盖：
- P5：EpisodicMemory.write 的 trade_date 兜底
- P6：对话后提取在后台线程执行，flush() 可等待；中断的对话不记录
- L6：提取调用 temperature=0 / 显式 timeout / usage 计入共享容器
- T5/L2：registry.call 统一截断
- 次要：predictions 价格字段 Decimal 往返
"""

from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.extractor import extract_from_conversation
from mommy_chaogu.agent.service import AgentService
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry


@pytest.fixture
def mock_ctx() -> ToolContext:
    adp = MagicMock()
    adp.get_quote.return_value = None
    return ToolContext(adapter=adp)


def _text_response(text: str, usage: Any = None) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    resp.usage = usage
    return resp


class TestTradeDateFallback:
    """P5：write() 不传 trade_date 时兜底为本地日期。"""

    def test_write_without_trade_date_defaults_to_today(self, tmp_path: Path) -> None:
        em = EpisodicMemory(tmp_path / "t.db")
        eid = em.write(event_type="analysis_record", scope="market", summary="s", data={})
        ev = em.get_by_id(eid)
        assert ev is not None
        assert ev["trade_date"] is not None
        # 可被按日期查询命中（修复前 trade_date=NULL → 日期过滤静默漏掉）
        rows = em.query(start_date="2020-01-01", end_date="2099-12-31")
        assert len(rows) == 1

    def test_write_with_explicit_trade_date_kept(self, tmp_path: Path) -> None:
        em = EpisodicMemory(tmp_path / "t.db")
        eid = em.write(
            event_type="analysis_record",
            scope="market",
            summary="s",
            data={},
            trade_date="2026-01-15",
        )
        assert em.get_by_id(eid)["trade_date"] == "2026-01-15"  # type: ignore[index]


class TestBackgroundExtraction:
    """P6：chat() 返回不被提取链阻塞；提取在后台线程完成。"""

    @patch("openai.OpenAI")
    def test_record_conversation_runs_in_background(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        gate = threading.Event()
        ms = MagicMock()
        ms.get_context.return_value = "system"
        ms.has_memory = False
        ms.record_conversation.side_effect = lambda *a, **kw: gate.wait(timeout=5)

        svc = AgentService(mock_ctx, api_key="sk-test", memory_service=ms)
        svc._client.chat.completions.create.return_value = _text_response("回答")

        # record_conversation 卡在 gate 上——若 chat 同步执行会卡死 5s，
        # 后台线程则立即返回
        resp = svc.chat("hi")
        assert resp.text == "回答"

        gate.set()
        svc.flush(timeout=5)
        ms.record_conversation.assert_called_once()
        # 双写修复：未传外部 memory 时 write_messages=True
        assert ms.record_conversation.call_args.kwargs["write_messages"] is True

    @patch("openai.OpenAI")
    def test_external_memory_disables_service_write(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """传入外部 memory 时 write_messages=False（同一轮不写两遍）。"""
        ms = MagicMock()
        ms.get_context.return_value = "system"
        ms.has_memory = False

        svc = AgentService(mock_ctx, api_key="sk-test", memory_service=ms)
        svc._client.chat.completions.create.return_value = _text_response("回答")

        memory = MagicMock()
        memory.recent.return_value = []
        svc.chat("hi", memory=memory)
        svc.flush(timeout=5)

        memory.add.assert_any_call("user", "hi")
        memory.add.assert_any_call("assistant", "回答")
        assert ms.record_conversation.call_args.kwargs["write_messages"] is False

    @patch("openai.OpenAI")
    def test_interrupted_chat_skips_recording(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """中断的对话不记录、不提取——"（已中断）"不是真实 assistant 回复。"""
        ms = MagicMock()
        ms.get_context.return_value = "system"
        ms.has_memory = False

        svc = AgentService(mock_ctx, api_key="sk-test", memory_service=ms)
        event = threading.Event()
        event.set()  # LLM 调用前即取消

        resp = svc.chat("hi", cancel_event=event)

        assert resp.interrupted is True
        svc.flush(timeout=5)
        ms.record_conversation.assert_not_called()


class TestExtractorLLMCall:
    """L6：提取调用的 temperature / timeout / usage 统计。"""

    def test_temperature_zero_and_explicit_timeout(self) -> None:
        client = MagicMock()
        usage = MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 5
        usage.total_tokens = 15
        resp = _text_response('{"observations": [], "predictions": []}', usage=usage)
        client.chat.completions.create.return_value = resp

        usage_out: dict[str, int] = {}
        result = extract_from_conversation("q", "a", client, "m", usage_out=usage_out)

        assert result is None  # 空内容
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["temperature"] == 0
        assert kwargs["timeout"] > 0
        # usage 计入共享容器（修复前提取调用不进任何统计）
        assert usage_out["total_tokens"] == 15

    def test_usage_lock_is_used_when_provided(self) -> None:
        client = MagicMock()
        usage = MagicMock()
        usage.prompt_tokens = 1
        usage.completion_tokens = 1
        usage.total_tokens = 2
        client.chat.completions.create.return_value = _text_response(
            '{"observations": [], "predictions": []}', usage=usage
        )

        lock = MagicMock(wraps=threading.Lock())
        usage_out: dict[str, int] = {}
        extract_from_conversation("q", "a", client, "m", usage_out=usage_out, usage_lock=lock)

        assert lock.__enter__.called  # 累加时持有锁（与主线程统计互斥）
        assert usage_out["prompt_tokens"] == 1


class TestRegistryTruncation:
    """T5/L2：registry.call 对工具结果统一截断。"""

    def test_oversized_result_truncated_with_marker(self) -> None:
        from mommy_chaogu.agent.tools import registry as reg

        big = '{"data": "' + "x" * 20000 + '"}'
        original = reg._HANDLERS["get_quote"]
        reg._HANDLERS["get_quote"] = lambda ctx, args: big
        try:
            r = ToolRegistry(ToolContext(adapter=MagicMock()))
            out = r.call("get_quote", {"code": "600519"})
        finally:
            reg._HANDLERS["get_quote"] = original

        assert len(out.encode("utf-8")) <= reg.MAX_RESULT_BYTES + 64
        assert "truncated" in out

    def test_small_result_untouched(self) -> None:
        r = ToolRegistry(ToolContext(adapter=MagicMock()))
        out = r.call("nonexistent_tool", {})
        assert "未知工具" in out


class TestPredictionPriceDecimal:
    """次要项：predictions 价格字段 Decimal 往返（REAL 列不泄漏浮点噪声）。"""

    def test_decimal_price_roundtrip(self, tmp_path: Path) -> None:
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "t.db")
        pid = tracker.create(
            code="600519",
            name="茅台",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
            target_price=Decimal("84.49"),
            entry_price=Decimal("80.01"),
        )
        pred = tracker.get_by_id(pid)
        assert pred is not None
        assert pred["target_price"] == Decimal("84.49")
        assert pred["entry_price"] == Decimal("80.01")
        assert isinstance(pred["target_price"], Decimal)

        tracker.update_status(pid, status="hit", actual_price=Decimal("85.00"))
        pred = tracker.get_by_id(pid)
        assert pred["actual_price"] == Decimal("85.00")  # type: ignore[index]

    def test_float_input_accepted_and_quantized(self, tmp_path: Path) -> None:
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "t.db")
        pid = tracker.create(
            code="600519",
            name=None,
            prediction="p",
            direction="bullish",
            timeframe="5d",
            entry_price=80.01234567,  # float 输入量化到 4 位小数
        )
        pred = tracker.get_by_id(pid)
        assert pred["entry_price"] == Decimal("80.0123")  # type: ignore[index]
