"""AgentService 写操作确认（on_confirm）单测。

覆盖：
- requires_confirmation 的工具/action 白名单语义
- 拒绝：工具不执行、拒绝结果回传 LLM、on_tool_result(ok=False, DENIAL_RESULT_MESSAGE)
- 允许 / 会话放行由 UI 层实现，这里只测回调返回 True 时正常执行
- 回调抛异常 fail-closed（按拒绝）
- 只读工具不触发确认
- 不传 on_confirm 时行为与旧版一致
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent.service import (
    DENIAL_RESULT_MESSAGE,
    AgentService,
    requires_confirmation,
)
from mommy_chaogu.agent.tools import ToolContext


@pytest.fixture
def mock_ctx() -> ToolContext:
    adp = MagicMock()
    adp.get_quote.return_value = None
    return ToolContext(adapter=adp)


@pytest.fixture(autouse=True)
def isolated_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL", "")


def _tc_message(name: str, args_json: str) -> MagicMock:
    """构造一个带单个 tool_call 的 LLM 响应消息。"""
    msg = MagicMock()
    msg.tool_calls = [MagicMock()]
    msg.tool_calls[0].id = "tc_1"
    msg.tool_calls[0].function.name = name
    msg.tool_calls[0].function.arguments = args_json
    msg.model_dump.return_value = {"role": "assistant", "content": None}
    msg.content = None
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    return resp


def _text_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    return resp


def _make_service(mock_ctx: ToolContext) -> AgentService:
    with patch("openai.OpenAI"):
        svc = AgentService(mock_ctx, api_key="sk-test")
    svc._tools = MagicMock()
    svc._tools.definitions.return_value = []
    svc._tools.call.return_value = '{"ok": true}'
    return svc


class TestRequiresConfirmation:
    def test_strategy_tools_always(self) -> None:
        assert requires_confirmation("strategy_save", {})
        assert requires_confirmation("strategy_archive", {})
        assert requires_confirmation("strategy_activate_monitor", {})

    def test_manage_tools_by_action(self) -> None:
        assert requires_confirmation("manage_alert", {"action": "add"})
        assert requires_confirmation("manage_alert", {"action": "remove"})
        assert not requires_confirmation("manage_alert", {"action": "list"})
        assert not requires_confirmation("manage_alert", {})
        assert requires_confirmation("manage_watchlist", {"action": "add"})
        assert not requires_confirmation("manage_watchlist", {"action": "list"})

    def test_read_tools_never(self) -> None:
        assert not requires_confirmation("get_quote", {})
        assert not requires_confirmation("get_bars", {"code": "600519"})
        assert not requires_confirmation("unknown_tool", {})


class TestOnConfirmDeny:
    @patch("openai.OpenAI")
    def test_denied_tool_not_executed(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("strategy_save", '{"card": {"name": "均值回归"}}'),
            _text_response("好的，已取消保存"),
        ]
        results: list[bool] = []

        def on_confirm(name: str, _args: dict) -> bool:
            results.append(True)
            return False

        resp = svc.chat("存个策略卡", on_confirm=on_confirm)

        assert results == [True]
        svc._tools.call.assert_not_called()
        assert resp.text == "好的，已取消保存"
        # 拒绝结果回传 LLM：tool_calls 记录里是拒绝 JSON
        assert len(resp.tool_calls) == 1
        denial = json.loads(resp.tool_calls[0].result)
        assert denial["error"] == DENIAL_RESULT_MESSAGE

    @patch("openai.OpenAI")
    def test_denied_fires_tool_callbacks(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("manage_watchlist", '{"action": "add", "code": "600519"}'),
            _text_response("已拒绝添加"),
        ]
        calls: list[tuple[str, bool, str]] = []
        resp = svc.chat(
            "把茅台加入自选",
            on_tool_call=lambda n, a: calls.append((n, "start", "")),
            on_tool_result=lambda n, ok, _ms, r: calls.append((n, "end" if ok else "denied", r)),
            on_confirm=lambda n, a: False,
        )

        assert ("manage_watchlist", "start", "") in calls
        denied = [c for c in calls if c[1] == "denied"]
        assert len(denied) == 1
        assert denied[0][2] == DENIAL_RESULT_MESSAGE
        assert resp.rounds == 2

    @patch("openai.OpenAI")
    def test_confirm_exception_fail_closed(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("strategy_save", "{}"),
            _text_response("已取消"),
        ]

        def on_confirm(_name: str, _args: dict) -> bool:
            raise RuntimeError("UI 挂了")

        resp = svc.chat("存策略卡", on_confirm=on_confirm)
        svc._tools.call.assert_not_called()
        assert resp.text == "已取消"


class TestOnConfirmAllow:
    @patch("openai.OpenAI")
    def test_allowed_tool_executes(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("strategy_save", '{"card": {"name": "均值回归"}}'),
            _text_response("已保存"),
        ]
        resp = svc.chat("存策略卡", on_confirm=lambda n, a: True)
        svc._tools.call.assert_called_once()
        assert resp.text == "已保存"

    @patch("openai.OpenAI")
    def test_read_tool_skips_confirm(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("get_quote", '{"code": "600519"}'),
            _text_response("1680"),
        ]
        confirm_calls: list[str] = []
        resp = svc.chat(
            "茅台多少钱",
            on_confirm=lambda n, a: confirm_calls.append(n) or True,
        )
        assert confirm_calls == []
        svc._tools.call.assert_called_once()
        assert resp.text == "1680"

    @patch("openai.OpenAI")
    def test_manage_alert_list_skips_confirm(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("manage_alert", '{"action": "list"}'),
            _text_response("无告警"),
        ]
        confirm_calls: list[str] = []
        svc.chat("看下告警", on_confirm=lambda n, a: confirm_calls.append(n) or True)
        assert confirm_calls == []

    @patch("openai.OpenAI")
    def test_no_on_confirm_backward_compat(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """不传 on_confirm：写工具直接执行（MCP / CLI 旧路径不变）。"""
        svc = _make_service(mock_ctx)
        svc._client.chat.completions.create.side_effect = [
            _tc_message("strategy_save", "{}"),
            _text_response("已保存"),
        ]
        resp = svc.chat("存策略卡")
        svc._tools.call.assert_called_once()
        assert resp.text == "已保存"
