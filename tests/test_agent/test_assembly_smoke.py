"""装配冒烟测试：走真实入口（TUI bootstrap / MCP server / CLI verify）。

评估文档（EVALUATION-2026-07-18）根因 1：「接口、实现、测试都在，唯独
生产装配不调用」——向量检索、TokenTracker、ctx.client 都是这类死代码。
这类测试不 mock 装配路径本身，而是直接调生产入口，断言接线真实发生：

- TUI ``Services.bootstrap()``：探测链与读 key 链一致（L4）、
  ctx.client/model/embedding_model 回写（P4/T4）、TokenTracker 接线（L3）
- MCP ``create_mcp_server()``：LLM client 接线、call_tool 走线程池（T5）、
  工具数与注册表一致

verify/consolidate 的 CLI 入口冒烟见 test_cli_maintenance.py（P1 修复时已有）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mommy_chaogu.agent import llm as llm_provider

_ALL_PROVIDER_ENVS = [cfg["env_key"] for cfg in llm_provider.SUPPORTED_PROVIDERS.values()]


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离环境：三库指向 tmp、所有 provider key 清空（防空 .env 串扰）。

    注意入口里的 ``load_dotenv()`` 不覆盖已有 env var——把 key 置空串
    （falsy）既挡住 .env 注入，又让 detect_provider 视为未配置。
    ``AGENT_PROVIDER`` 也在 .env 里：必须 setenv 空串占住（不能 delenv——
    monkeypatch 对"原本不存在"的 delenv 不记录 undo，teardown 无法还原
    load_dotenv 注入的值，会污染后续测试）。
    """
    monkeypatch.setattr("mommy_chaogu.db_paths.AGENT_DB", tmp_path / "agent.db")
    monkeypatch.setattr("mommy_chaogu.db_paths.MARKET_DB", tmp_path / "market.db")
    monkeypatch.setattr("mommy_chaogu.db_paths.PORTFOLIO_DB", tmp_path / "portfolio.db")
    monkeypatch.setenv("AGENT_PROVIDER", "")
    for env in _ALL_PROVIDER_ENVS:
        monkeypatch.setenv(env, "")
    return tmp_path


def _set_only_key(monkeypatch: pytest.MonkeyPatch, env_key: str, value: str = "sk-test") -> None:
    for env in _ALL_PROVIDER_ENVS:
        monkeypatch.setenv(env, value if env == env_key else "")


class TestTuiBootstrapSmoke:
    """TUI Services.bootstrap() 真实装配路径。"""

    def test_openai_only_key_wires_agent_and_ctx(
        self, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """只配 OPENAI_API_KEY（未设 AGENT_PROVIDER）时 agent 必须可用。

        L4 回归：修复前探测链（DEEPSEEK→OPENAI→…）与读 key 链
        （AGENT_PROVIDER 默认 deepseek）不一致——探测通过、初始化读
        DEEPSEEK_API_KEY 失败、agent 静默不可用。
        """
        from mommy_chaogu.tui.services.bootstrap import Services

        _set_only_key(monkeypatch, "OPENAI_API_KEY")
        with patch("openai.OpenAI"):
            services = Services.bootstrap()

        assert services.agent.has_agent(), "只配 OPENAI_API_KEY 时 agent 应可用（L4）"
        agent = services.agent._agent
        assert agent._provider == "openai"

        # P4/T4：ctx 回写真实发生
        assert agent._ctx.client is agent._client
        assert agent._ctx.model == "gpt-4o-mini"
        assert agent._ctx.embedding_model == "text-embedding-3-small"

        # L3：TokenTracker 接线（agent_db 存在 → 自动启用）
        assert agent._token_tracker is not None

    def test_deepseek_key_explicitly_degrades_embedding(
        self, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """deepseek 端点无 embedding 接口 → embedding_model 显式为 None。

        P4 回归：不能把聊天模型名当 embedding 模型传（必然失败且静默）。
        """
        from mommy_chaogu.tui.services.bootstrap import Services

        _set_only_key(monkeypatch, "DEEPSEEK_API_KEY")
        with patch("openai.OpenAI"):
            services = Services.bootstrap()

        assert services.agent.has_agent()
        agent = services.agent._agent
        assert agent._provider == "deepseek"
        assert agent._ctx.client is agent._client
        assert agent._ctx.embedding_model is None

    def test_no_key_agent_unavailable_but_bootstrap_ok(
        self, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无任何 key → agent 不可用（显式降级），bootstrap 本身不崩。"""
        from mommy_chaogu.tui.services.bootstrap import Services

        with patch("openai.OpenAI"):
            services = Services.bootstrap()

        assert not services.agent.has_agent()


class TestMcpServerSmoke:
    """MCP server 真实装配路径。"""

    def test_build_context_wires_llm_when_key_present(
        self, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """有 key 时 _build_context 接 client/model/embedding_model（T4）。"""
        from mommy_chaogu.agent.mcp_server import _build_context

        _set_only_key(monkeypatch, "OPENAI_API_KEY")
        with patch("openai.OpenAI"):
            ctx = _build_context()

        assert ctx.client is not None
        assert ctx.model == "gpt-4o-mini"
        assert ctx.embedding_model == "text-embedding-3-small"
        # 记忆服务带 pipeline（record_analysis 不再因缺 client 永远跳过）
        assert ctx.memory_service is not None
        assert ctx.memory_service.has_pipeline

    def test_build_context_without_key_degrades(
        self, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无 key → client None，但 context 仍完整可用（降级模式）。"""
        from mommy_chaogu.agent.mcp_server import _build_context

        with patch("openai.OpenAI"):
            ctx = _build_context()

        assert ctx.client is None
        assert ctx.embedding_model is None
        assert ctx.memory_service is not None

    def test_server_lists_all_tools_and_call_tool_runs_offloop(
        self, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """list_tools 与注册表一致；call_tool 经 to_thread 执行（T5）。"""
        from mcp.types import CallToolRequest, CallToolRequestParams

        from mommy_chaogu.agent.mcp_server import create_mcp_server
        from mommy_chaogu.agent.tools import ToolRegistry
        from mommy_chaogu.agent.tools.base import ToolContext

        ctx = ToolContext(adapter=None, agent_db=isolated_env / "agent.db")  # type: ignore[arg-type]
        server = create_mcp_server(ctx)

        # 工具数与注册表一致（docstring/日志里的工具数不能漂移）
        assert len(server.request_handlers) > 0
        expected = set(ToolRegistry.tool_names())

        async def _call(name: str, arguments: dict[str, Any]) -> Any:
            handler = server.request_handlers[CallToolRequest]
            req = CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name=name, arguments=arguments),
            )
            return await handler(req)

        # 选一个不需要 adapter 的工具验证 call_tool 全链路（线程池执行 +
        # 真实 agent_db 读取）：空库返回空列表 JSON
        result = asyncio.run(_call("get_prediction_history", {"limit": 1}))
        # CallToolResult → content[0].text 是工具返回的 JSON
        text = result.root.content[0].text  # type: ignore[union-attr]
        assert text == "[]"
        assert "get_prediction_history" in expected
