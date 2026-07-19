"""AgentService 容错回归测试：工具异常恢复 + LLM 瞬时错误重试。"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIConnectionError, BadRequestError, RateLimitError

from mommy_chaogu.agent.service import AgentService
from mommy_chaogu.agent.tools import ToolContext


@pytest.fixture
def mock_ctx() -> ToolContext:
    """minimal ToolContext with mock adapter."""
    adp = MagicMock()
    adp.get_quote.return_value = None
    return ToolContext(adapter=adp)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def _rate_limit_err() -> RateLimitError:
    resp = httpx.Response(429, request=_request())
    return RateLimitError("rate limited", response=resp, body=None)


def _conn_err() -> APIConnectionError:
    return APIConnectionError(message="connection reset", request=_request())


def _text_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    return resp


def _tool_call_response(name: str = "get_quote", args: str = '{"code": "600519"}') -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = [MagicMock()]
    msg.tool_calls[0].id = "tc_1"
    msg.tool_calls[0].function.name = name
    msg.tool_calls[0].function.arguments = args
    msg.model_dump.return_value = {"role": "assistant", "content": None}
    msg.content = None
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    return resp


def _make_broken_tools(svc: AgentService, exc: Exception) -> None:
    """把 svc 的工具注册表换成一个 call 必抛异常的 mock。"""
    broken = MagicMock()
    broken.definitions.return_value = []
    broken.call.side_effect = exc
    svc._tools = broken


class TestToolErrorRecovery:
    """工具执行抛异常时不应中断整轮对话，错误应回传给 LLM。"""

    @patch("openai.OpenAI")
    def test_tool_exception_does_not_kill_turn(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """工具炸了，LLM 看到错误后仍给出降级回答，整轮不抛异常。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _tool_call_response(),
            _text_response("行情接口暂时不可用，请稍后再试。"),
        ]
        _make_broken_tools(svc, RuntimeError("东财接口超时"))

        resp = svc.chat("茅台多少钱")

        assert "暂时不可用" in resp.text
        assert resp.rounds == 2
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_quote"
        assert "工具执行异常" in resp.tool_calls[0].result

    @patch("openai.OpenAI")
    def test_tool_error_fed_back_as_tool_message(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """工具异常以 {"error": ...} JSON 形式作为 tool 消息回传给 LLM。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _tool_call_response(),
            _text_response("抱歉，查询失败"),
        ]
        _make_broken_tools(svc, RuntimeError("东财接口超时"))

        svc.chat("茅台多少钱")

        create_mock = svc._client.chat.completions.create
        second_call_messages: list[dict[str, Any]] = create_mock.call_args_list[1].kwargs[
            "messages"
        ]
        tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        payload = json.loads(tool_msgs[0]["content"])
        assert "东财接口超时" in payload["error"]

    @patch("openai.OpenAI")
    def test_tool_error_invokes_on_tool_result_with_failure(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """TUI 的 on_tool_result 回调收到 ok=False，用于渲染工具失败状态。"""
        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [
            _tool_call_response(),
            _text_response("降级回答"),
        ]
        _make_broken_tools(svc, RuntimeError("东财接口超时"))

        events: list[tuple[str, bool, int, str]] = []
        svc.chat(
            "茅台多少钱",
            on_tool_result=lambda name, ok, ms, res: events.append((name, ok, ms, res)),
        )

        assert len(events) == 1
        name, ok, _elapsed_ms, detail = events[0]
        assert name == "get_quote"
        assert ok is False
        assert "超时" in detail


class TestLLMRetry:
    """LLM 调用的瞬时错误按指数退避重试；非瞬时错误立即抛出。"""

    @patch("openai.OpenAI")
    def test_rate_limit_retries_then_succeeds(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """429 限流 → 退避后重试成功。"""
        svc = AgentService(mock_ctx, api_key="sk-test", retry_base_delay=0)
        svc._client.chat.completions.create.side_effect = [
            _rate_limit_err(),
            _text_response("你好！"),
        ]

        with patch("time.sleep") as mock_sleep:
            resp = svc.chat("你好")

        assert resp.text == "你好！"
        assert svc._client.chat.completions.create.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("openai.OpenAI")
    def test_retry_exhaustion_raises(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        """持续连接失败：重试 max_retries 次后抛出最后一次异常。"""
        svc = AgentService(mock_ctx, api_key="sk-test", max_retries=2, retry_base_delay=0)
        svc._client.chat.completions.create.side_effect = _conn_err()

        with patch("time.sleep"), pytest.raises(APIConnectionError):
            svc.chat("你好")

        # 1 次原始调用 + 2 次重试
        assert svc._client.chat.completions.create.call_count == 3

    @patch("openai.OpenAI")
    def test_non_retryable_error_raises_immediately(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """400 参数错误不属于瞬时错误，不重试、不退避，直接抛出。"""
        svc = AgentService(mock_ctx, api_key="sk-test", retry_base_delay=0)
        bad_req = BadRequestError(
            "invalid messages", response=httpx.Response(400, request=_request()), body=None
        )
        svc._client.chat.completions.create.side_effect = bad_req

        with patch("time.sleep") as mock_sleep, pytest.raises(BadRequestError):
            svc.chat("你好")

        assert svc._client.chat.completions.create.call_count == 1
        mock_sleep.assert_not_called()
