"""AgentService 单测：Mock LLM client 测试 agent 循环。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent.service import SUPPORTED_PROVIDERS, AgentService
from mommy_chaogu.agent.tools import ToolContext


@pytest.fixture
def mock_ctx() -> ToolContext:
    """minimal ToolContext with mock adapter."""
    adp = MagicMock()
    adp.get_quote.return_value = None
    return ToolContext(adapter=adp)


class TestProviderConfig:
    def test_deepseek_is_default(self) -> None:
        assert "deepseek" in SUPPORTED_PROVIDERS
        assert SUPPORTED_PROVIDERS["deepseek"]["default_model"] == "deepseek-chat"

    def test_all_providers_have_env_key(self) -> None:
        for name, config in SUPPORTED_PROVIDERS.items():
            assert "env_key" in config, f"{name} missing env_key"
            assert "default_model" in config, f"{name} missing default_model"
            assert "base_url" in config, f"{name} missing base_url"

    def test_kimi_k26_configuration(self) -> None:
        assert SUPPORTED_PROVIDERS["kimi"]["base_url"] == "https://api.kimi.com/coding/v1"
        assert SUPPORTED_PROVIDERS["kimi"]["default_model"] == "kimi-k2.6"

    def test_nova_bridge_configuration(self) -> None:
        assert SUPPORTED_PROVIDERS["nova"] == {
            "base_url": "http://127.0.0.1:9999/v1",
            "default_model": "nova-bridge",
            "env_key": "NOVA_API_KEY",
            "temperature": None,
        }

    def test_minimax_configuration(self) -> None:
        assert SUPPORTED_PROVIDERS["minimax"] == {
            "base_url": "https://api.minimaxi.com/v1",
            "default_model": "MiniMax-M2.7",
            "env_key": "MINIMAX_API_KEY",
            "temperature": 1.0,
        }

    def test_temperatures_are_provider_aware(self) -> None:
        assert SUPPORTED_PROVIDERS["kimi"]["temperature"] == 1.0
        assert SUPPORTED_PROVIDERS["openai"]["temperature"] == 0.2


class TestAgentServiceInit:
    def test_missing_api_key_raises(self, mock_ctx: ToolContext) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="未找到 API key"),
        ):
            AgentService(mock_ctx)

    def test_invalid_provider_raises(self, mock_ctx: ToolContext) -> None:
        with pytest.raises(ValueError, match="Unsupported agent provider"):
            AgentService(mock_ctx, provider="mystery", api_key="sk-test")

    @patch("openai.OpenAI")
    def test_init_with_explicit_key(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        svc = AgentService(mock_ctx, api_key="sk-test")
        assert svc._model == "deepseek-chat"

    @patch("openai.OpenAI")
    def test_init_with_provider(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        svc = AgentService(mock_ctx, provider="openai", api_key="sk-test")
        assert svc._model == "gpt-4o-mini"

    @patch("openai.OpenAI")
    def test_init_with_minimax_provider(
        self, mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = AgentService(mock_ctx, provider="minimax", api_key="minimax-test")
        assert svc._model == "MiniMax-M2.7"
        mock_openai.assert_called_once_with(
            api_key="minimax-test", base_url="https://api.minimaxi.com/v1"
        )


class TestAgentLoop:
    """测试 agent 的 tool-calling 循环逻辑。"""

    @patch("openai.OpenAI")
    def test_no_tool_calls_returns_text(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        """LLM 不调工具，直接返回文本。"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "你好！"

        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = mock_response

        resp = svc.chat("你好")

        assert resp.text == "你好！"
        assert resp.tool_calls == []
        assert resp.rounds == 1

    @patch("openai.OpenAI")
    def test_tool_call_then_text(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        """LLM 先调一次工具，再返回文本。"""
        # 第一次响应：tool_call
        mock_tc_message = MagicMock()
        mock_tc_message.tool_calls = [MagicMock()]
        mock_tc_message.tool_calls[0].id = "tc_1"
        mock_tc_message.tool_calls[0].function.name = "get_quote"
        mock_tc_message.tool_calls[0].function.arguments = '{"code": "600519"}'
        mock_tc_message.model_dump.return_value = {"role": "assistant", "content": None}
        mock_tc_message.content = None

        mock_resp_1 = MagicMock()
        mock_resp_1.choices = [MagicMock()]
        mock_resp_1.choices[0].message = mock_tc_message

        # 第二次响应：最终文本
        mock_final_message = MagicMock()
        mock_final_message.tool_calls = None
        mock_final_message.content = "茅台现价 1680 元"

        mock_resp_2 = MagicMock()
        mock_resp_2.choices = [MagicMock()]
        mock_resp_2.choices[0].message = mock_final_message

        svc = AgentService(mock_ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = [mock_resp_1, mock_resp_2]
        # 让 get_quote 返回有效数据
        svc._tools = MagicMock()
        svc._tools.definitions.return_value = []
        svc._tools.call.return_value = '{"code": "600519", "price": 1680.0}'

        resp = svc.chat("茅台多少钱")

        assert resp.text == "茅台现价 1680 元"
        assert resp.rounds == 2
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_quote"

    @patch("openai.OpenAI")
    def test_max_tool_calls_limit(self, _mock_openai: MagicMock, mock_ctx: ToolContext) -> None:
        """超过 max_tool_calls 时返回兜底文本。"""
        # 每次都返回 tool_calls（无限循环模拟）
        mock_infinite_tc = MagicMock()
        mock_infinite_tc.tool_calls = [MagicMock()]
        mock_infinite_tc.tool_calls[0].id = "tc_x"
        mock_infinite_tc.tool_calls[0].function.name = "get_quote"
        mock_infinite_tc.tool_calls[0].function.arguments = '{"code": "600519"}'
        mock_infinite_tc.model_dump.return_value = {"role": "assistant"}
        mock_infinite_tc.content = None

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_infinite_tc

        svc = AgentService(mock_ctx, api_key="sk-test", max_tool_calls=3)
        svc._client.chat.completions.create.return_value = mock_resp
        # 替换为 mock 工具注册表
        mock_tools = MagicMock()
        mock_tools.definitions.return_value = []
        mock_tools.call.return_value = '{"code": "600519"}'
        svc._tools = mock_tools

        resp = svc.chat("test")

        assert "工具调用次数过多" in resp.text
        assert resp.rounds == 3
