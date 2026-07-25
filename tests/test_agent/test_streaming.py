"""AgentService 流式输出 / 取消 / usage 累加单测（PLAN #4/#5/#6）。

覆盖：
- on_chunk 流式：最终回答轮直接走 stream=True（带 tools）调用，
  文本 delta 逐段回调，tool_calls delta 同步拼接——「得出答案」与
  「流式输出」是同一次调用（不再非流式出答案后重发全量 messages，
  双重计费已消除，EVALUATION-2026-07-18 L1）
- cancel_event：每轮 LLM 前 + 每个工具前 + 流式输出途中检查 is_set()
- usage 累加：response.usage 累加到 AgentResponse.usage；流式调用的
  usage 通过 stream_options=include_usage 取回后计入
- usage_out：调用方传入的 dict 作为共享容器原地累加（UI 实时读取）
- 流式不可用（create 抛错 / 迭代零收集失败）时回退非流式调用
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
    """模拟 OpenAI stream 对象：迭代出 N 个 chunk（纯文本 delta）。"""
    chunks = []
    for d in deltas:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = d
        chunk.choices[0].delta.tool_calls = None
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
        """on_chunk 时最终回答轮直接走 stream=True（带 tools），逐 delta 输出。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = _stream_response(
            ["你", "好", "世", "界"]
        )

        chunks: list[str] = []
        resp = svc.chat("hi", on_chunk=chunks.append)

        assert "".join(chunks) == "你好世界"
        assert resp.text == "你好世界"
        # 单次调用即完成「出答案 + 流式输出」（双重调用已消除）：
        # stream=True 且带 tools
        create = svc._client.chat.completions.create
        assert create.call_count == 1
        call = create.call_args_list[0]
        assert call.kwargs.get("stream") is True
        assert call.kwargs.get("tools") is not None

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
        """stream create 抛异常时回退非流式调用（此时未流出任何内容）。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            RuntimeError("provider 不支持 stream"),
            _text_response("非流式答案"),
        ]

        chunks: list[str] = []
        resp = svc.chat("hi", on_chunk=chunks.append)

        # 流式失败 → chunks 为空，回退非流式拿到完整答案
        assert chunks == []
        assert resp.text == "非流式答案"

    @patch("openai.OpenAI")
    def test_stream_usage_counted_via_include_usage(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """流式调用的 usage 通过 stream_options=include_usage 取回并计入统计。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = _stream_response(
            ["你", "好"], usage=_usage(100, 50)
        )

        resp = svc.chat("hi", on_chunk=lambda d: None)

        # 单次流式调用的 usage 计入
        assert resp.usage["prompt_tokens"] == 100
        assert resp.usage["completion_tokens"] == 50
        assert resp.usage["total_tokens"] == 150

        # 流式调用带 stream_options=include_usage
        call = svc._client.chat.completions.create.call_args_list[0]
        assert call.kwargs.get("stream_options") == {"include_usage": True}

    @patch("openai.OpenAI")
    def test_stream_iter_error_before_first_chunk_keeps_fallback(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """流式迭代在第一个 chunk 前异常 → 零收集，回退非流式调用。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        broken_stream = MagicMock()
        broken_stream.__iter__ = MagicMock(side_effect=RuntimeError("连接中断"))
        svc._client.chat.completions.create.side_effect = [
            broken_stream,
            _text_response("完整的非流式答案"),
        ]

        chunks: list[str] = []
        resp = svc.chat("hi", on_chunk=chunks.append)

        assert chunks == []
        assert resp.text == "完整的非流式答案"

    @patch("openai.OpenAI")
    def test_stream_usage_without_usage_chunk_unchanged(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """provider 不回传 usage chunk 时 usage 保持空（不崩、不虚构）。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = _stream_response(
            ["你", "好"], usage=None
        )

        resp = svc.chat("hi", on_chunk=lambda d: None)

        assert resp.text == "你好"
        assert resp.usage == {}

    @patch("openai.OpenAI")
    def test_stream_tool_calls_collected_and_executed(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """流式 chunk 里的 tool_calls delta 按 index 拼接并照常执行。"""
        # 第一轮：流式返回 tool_call（arguments 分两片到达）
        tc_delta1 = MagicMock()
        tc_delta1.index = 0
        tc_delta1.id = "tc_1"
        tc_delta1.function.name = "get_quote"
        tc_delta1.function.arguments = '{"code": '
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = None
        chunk1.choices[0].delta.tool_calls = [tc_delta1]
        chunk1.usage = None

        tc_delta2 = MagicMock()
        tc_delta2.index = 0
        tc_delta2.id = None
        tc_delta2.function.name = None
        tc_delta2.function.arguments = '"600519"}'
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = None
        chunk2.choices[0].delta.tool_calls = [tc_delta2]
        chunk2.usage = None

        stream1 = MagicMock()
        stream1.__iter__ = lambda self: iter([chunk1, chunk2])  # type: ignore[misc]

        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            stream1,
            _stream_response(["茅台", "1680"]),
        ]
        svc._tools = MagicMock()
        svc._tools.definitions.return_value = []
        svc._tools.call.return_value = '{"price": 1680}'

        chunks: list[str] = []
        resp = svc.chat("hi", on_chunk=chunks.append)

        # tool_calls 拼接正确并执行
        svc._tools.call.assert_called_once_with("get_quote", {"code": "600519"})
        assert resp.text == "茅台1680"


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
        """LLM 返回 tool_calls，工具执行期间 cancel 被 set → 下一轮 LLM 前退出。"""
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

        # cancel_event 在工具执行期间 set
        event = threading.Event()

        def fake_call(name: str, args: dict[str, Any]) -> str:
            event.set()
            return "{}"

        svc._tools.call.side_effect = fake_call

        resp = svc.chat("hi", cancel_event=event)

        assert resp.interrupted is True
        # 唯一的工具执行了一次（set 发生在执行期间），
        # 之后循环在「下一轮 LLM 调用前」的检查点退出
        assert svc._tools.call.call_count == 1
        assert svc._client.chat.completions.create.call_count == 1

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

    @patch("openai.OpenAI")
    def test_cancel_during_stream_marks_interrupted(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """流式输出途中 cancel → 返回 interrupted=True（不再被吞成完整回答）。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = _stream_response(
            ["你", "好", "世", "界"]
        )

        event = threading.Event()
        chunks: list[str] = []

        def on_chunk(delta: str) -> None:
            chunks.append(delta)
            # 收到第一个 delta 后取消
            event.set()

        resp = svc.chat("hi", on_chunk=on_chunk, cancel_event=event)

        assert resp.interrupted is True
        # 已流出的部分保留
        assert "".join(chunks) == "你"
        assert resp.text == "你"


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

    @patch("openai.OpenAI")
    def test_usage_out_shared_container(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """usage_out 传入的 dict 被原地累加，且与 resp.usage 是同一对象。

        TUI 的 WorkingIndicator 靠这个共享 dict 在对话进行中实时显示 token。
        """
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _text_response("回答", usage=_usage(100, 50)),
        ]

        shared: dict[str, int] = {}
        resp = svc.chat("hi", usage_out=shared)

        assert resp.usage is shared
        assert shared["total_tokens"] == 150
