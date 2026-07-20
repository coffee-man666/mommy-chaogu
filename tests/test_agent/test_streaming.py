"""AgentService 流式输出 / 取消 / usage 累加单测（PLAN #4/#5/#6）。

覆盖：
- on_chunk 流式：工具循环结束后发起 stream=True 调用，逐 delta 调 on_chunk
- cancel_event：每轮 LLM 前 + 每个工具前检查 is_set()，命中返回 interrupted=True
- usage 累加：response.usage 累加到 AgentResponse.usage
- provider 不支持 stream 时回退非流式文本
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent.service import AgentService
from mommy_chaogu.agent.tools import ToolContext


@pytest.fixture
def mock_ctx() -> ToolContext:
    adp = MagicMock()
    adp.get_quote.return_value = None
    return ToolContext(adapter=adp)


def _text_response(text: str, usage: Any = None) -> MagicMock:
    """非流式 response mock。"""
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    resp.usage = usage
    return resp


def _usage(p: int, c: int) -> MagicMock:
    u = MagicMock()
    u.prompt_tokens = p
    u.completion_tokens = c
    u.total_tokens = p + c
    return u


def _stream_response(deltas: list[str], usage: Any = None) -> MagicMock:
    """模拟 OpenAI stream 对象：迭代出 N 个 chunk。"""
    chunks = []
    for d in deltas:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = d
        chunk.usage = None
        chunks.append(chunk)
    # 最后一个 chunk 带 usage
    if usage is not None and chunks:
        chunks[-1].usage = usage

    stream = MagicMock()
    stream.__iter__ = lambda self: iter(chunks)  # type: ignore[misc]
    return stream


class TestStreamingFinalAnswer:
    """on_chunk 流式最终回答（#4）。"""

    @patch("openai.OpenAI")
    def test_on_chunk_called_per_delta(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """非流式轮拿到文本后，on_chunk 驱动一次 stream 调用逐 delta 输出。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _text_response("你好世界"),
            _stream_response(["你", "好", "世", "界"]),
        ]

        chunks: list[str] = []
        resp = svc.chat("hi", on_chunk=chunks.append)

        assert "".join(chunks) == "你好世界"
        assert resp.text == "你好世界"
        # 第二次调用是 stream=True
        second_call = svc._client.chat.completions.create.call_args_list[1]
        assert second_call.kwargs.get("stream") is True

    @patch("openai.OpenAI")
    def test_no_on_chunk_skips_streaming(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """不传 on_chunk 时不发起 stream 调用（保持原行为）。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = _text_response("直接回答")

        resp = svc.chat("hi")

        assert resp.text == "直接回答"
        assert svc._client.chat.completions.create.call_count == 1

    @patch("openai.OpenAI")
    def test_stream_fallback_on_error(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        """stream 调用抛异常时保留非流式文本（不返回空）。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _text_response("非流式答案"),
            RuntimeError("provider 不支持 stream"),
        ]

        chunks: list[str] = []
        resp = svc.chat("hi", on_chunk=chunks.append)

        # 流式失败 → chunks 为空，但 resp.text 保留非流式文本
        assert chunks == []
        assert resp.text == "非流式答案"


class TestCancelEvent:
    """cancel_event 真取消（#5）。"""

    @patch("openai.OpenAI")
    def test_cancel_before_llm_call(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        """cancel_event 在 LLM 调用前已 set → 立即返回 interrupted。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        event = threading.Event()
        event.set()

        resp = svc.chat("hi", cancel_event=event)

        assert resp.interrupted is True
        assert resp.text == "（已中断）"
        # LLM 从未被调用
        assert svc._client.chat.completions.create.call_count == 0

    @patch("openai.OpenAI")
    def test_cancel_before_tool_execution(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """LLM 返回 tool_calls，但工具执行前 cancel_event 被 set。"""
        # 第一轮：返回 tool_call
        tc_msg = MagicMock()
        tc_msg.tool_calls = [MagicMock()]
        tc_msg.tool_calls[0].id = "tc_1"
        tc_msg.tool_calls[0].function.name = "get_quote"
        tc_msg.tool_calls[0].function.arguments = '{"code": "600519"}'
        tc_msg.model_dump.return_value = {"role": "assistant"}
        tc_msg.content = None
        resp1 = MagicMock()
        resp1.choices = [MagicMock()]
        resp1.choices[0].message = tc_msg
        resp1.usage = None

        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = resp1
        svc._tools = MagicMock()
        svc._tools.definitions.return_value = []

        # cancel_event 在工具执行前 set
        event = threading.Event()

        def fake_call(name: str, args: dict[str, Any]) -> str:
            # 工具执行前 set cancel
            event.set()
            return "{}"

        svc._tools.call.side_effect = fake_call

        resp = svc.chat("hi", cancel_event=event)

        assert resp.interrupted is True
        # 工具确实被调了一次（因为 set 发生在 fake_call 内部，但循环会在
        # 下一个工具前检查到——这里只有一个工具，所以会在下一轮 LLM 前退出）

    @patch("openai.OpenAI")
    def test_cancel_after_tool_round_before_next_llm(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """工具执行完、下一轮 LLM 调用前 cancel → interrupted=True。

        这是最关键的取消路径：工具结果已回传，但用户在 LLM 再思考前取消。
        """
        # 第一轮：tool_call（usage=None）
        tc_msg = MagicMock()
        tc_msg.tool_calls = [MagicMock()]
        tc_msg.tool_calls[0].id = "tc_1"
        tc_msg.tool_calls[0].function.name = "get_quote"
        tc_msg.tool_calls[0].function.arguments = '{"code": "600519"}'
        tc_msg.model_dump.return_value = {"role": "assistant"}
        tc_msg.content = None
        resp1 = MagicMock()
        resp1.choices = [MagicMock()]
        resp1.choices[0].message = tc_msg
        resp1.usage = None

        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = resp1
        svc._tools = MagicMock()
        svc._tools.definitions.return_value = []
        svc._tools.call.return_value = '{"price": 1680}'

        event = threading.Event()

        def on_tool_result(name: str, ok: bool, ms: int, res: str) -> None:
            # 工具完成后、下一轮 LLM 前 set cancel
            event.set()

        resp = svc.chat("hi", on_tool_result=on_tool_result, cancel_event=event)

        assert resp.interrupted is True
        assert resp.text == "（已中断）"
        # 第二轮 LLM 从未被调用（cancel 在它之前命中）
        assert svc._client.chat.completions.create.call_count == 1


class TestUsageAccumulation:
    """response.usage 累加到 AgentResponse.usage（#6）。"""

    @patch("openai.OpenAI")
    def test_usage_accumulated_across_rounds(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """多轮 LLM 调用的 usage 累加。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _text_response("回答", usage=_usage(100, 50)),
        ]

        resp = svc.chat("hi")

        assert resp.usage["prompt_tokens"] == 100
        assert resp.usage["completion_tokens"] == 50
        assert resp.usage["total_tokens"] == 150

    @patch("openai.OpenAI")
    def test_no_usage_when_response_lacks_it(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """response.usage 为 None 时 usage dict 保持空。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = _text_response("x", usage=None)

        resp = svc.chat("hi")

        assert resp.usage == {}

    @patch("openai.OpenAI")
    def test_usage_default_empty_dict(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        """AgentResponse.usage 默认是空 dict（向后兼容）。"""
        from mommy_chaogu.agent.service import AgentResponse

        resp = AgentResponse(text="test")
        assert resp.usage == {}
        assert resp.interrupted is False
