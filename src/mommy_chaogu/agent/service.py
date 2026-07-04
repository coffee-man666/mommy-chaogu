"""AgentService：LLM + 工具调用循环。

使用 OpenAI SDK（兼容 deepseek / kimi / 其他 provider）。

核心循环：
    用户消息 → LLM
      ↓ LLM 返回 tool_calls?
      ├─ 是 → 执行每个 tool_call → 结果回传 → 再给 LLM
      └─ 否 → 返回最终文本
循环最多 max_tool_calls 次
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from mommy_chaogu.agent.extractor import extract_from_conversation, store_extraction
from mommy_chaogu.agent.memory import ConversationMemory
from mommy_chaogu.agent.prompt import SYSTEM_PROMPT
from mommy_chaogu.agent.prompt_builder import build_system_prompt
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

_log = logging.getLogger(__name__)

# 支持的 provider 配置
SUPPORTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "base_url": None,  # OpenAI 默认
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "env_key": "MOONSHOT_API_KEY",
    },
    "zai": {
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "default_model": "glm-4.7",
        "env_key": "ZAI_API_KEY",
    },
}


@dataclass
class ToolCallRecord:
    """单次工具调用记录。"""

    name: str
    arguments: dict[str, Any]
    result: str


@dataclass
class AgentResponse:
    """agent 单次对话的完整响应。"""

    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    rounds: int = 0  # LLM 调用轮数


class AgentService:
    """LLM agent 服务。

    用法：
        ctx = ToolContext(adapter=..., watchlist_store=...)
        agent = AgentService(ctx, model="deepseek-chat")
        resp = agent.chat("上证指数今天多少点？")
        print(resp.text)
    """

    def __init__(
        self,
        ctx: ToolContext,
        model: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        max_tool_calls: int = 10,
        episodic: Any | None = None,
        tracker: Any | None = None,
        semantic: Any | None = None,
    ) -> None:
        self._tools = ToolRegistry(ctx)
        self._max_tool_calls = max_tool_calls
        self._episodic = episodic
        self._tracker = tracker
        self._semantic = semantic
        self._ctx = ctx

        # 解析 provider 配置
        provider = provider or os.environ.get("AGENT_PROVIDER", "deepseek")
        config = SUPPORTED_PROVIDERS.get(provider, SUPPORTED_PROVIDERS["deepseek"])

        self._model = model or config["default_model"]

        # 解析 API key
        if api_key is None:
            api_key = os.environ.get(config["env_key"], "")
        if not api_key:
            raise ValueError(
                f"未找到 API key。请设置环境变量 {config['env_key']} 或传入 api_key 参数。"
            )

        # 构造 OpenAI client（兼容 deepseek / kimi）
        from openai import OpenAI

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if config["base_url"]:
            client_kwargs["base_url"] = config["base_url"]
        self._client = OpenAI(**client_kwargs)

    def chat(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        system_override: str | None = None,
        memory: ConversationMemory | None = None,
    ) -> AgentResponse:
        """单轮对话（可带历史），返回最终文本 + 工具调用日志。

        如果传入 *memory*，会先从中加载最近对话作为上下文，
        完成后将本轮 user / assistant 消息持久化到 memory。

        如果配置了 *episodic* + *tracker*，会：
        1. 用 build_system_prompt() 注入历史事件和判断回顾
        2. 对话结束后提取结构化 observations + predictions
        """
        # 动态构建 system prompt（注入历史事件 + 判断回顾 + 知识）
        if self._episodic is not None or self._tracker is not None:
            system_prompt = system_override or build_system_prompt(
                episodic=self._episodic, tracker=self._tracker, semantic=self._semantic
            )
        else:
            system_prompt = system_override or SYSTEM_PROMPT
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if memory is not None:
            # 用持久化记忆作为对话上下文
            for h in memory.recent():
                messages.append({"role": h["role"], "content": h["content"]})
        elif history:
            for h in history:
                messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": user_message})

        resp = self._run_loop(messages)

        if memory is not None:
            memory.add("user", user_message)
            memory.add("assistant", resp.text)

        # 后置 hook：事实抽取（失败不 block 主流程）
        if self._episodic is not None and self._tracker is not None:
            try:
                extraction = extract_from_conversation(
                    user_message, resp.text, self._client, self._model
                )
                if extraction is not None:
                    store_extraction(
                        extraction,
                        self._episodic,
                        self._tracker,
                        adapter=self._ctx.adapter if self._ctx else None,
                    )
            except Exception as e:
                _log.warning("extractor hook failed: %s", e)

        return resp

    def chat_raw(
        self,
        messages: list[dict[str, Any]],
    ) -> AgentResponse:
        """直接传入完整 messages 列表（灵活但需自己构造格式）。"""
        return self._run_loop(messages)

    def _run_loop(self, messages: list[dict[str, Any]]) -> AgentResponse:
        """核心 agent 循环：LLM → tool_calls → execute → LLM → ..."""
        all_tool_calls: list[ToolCallRecord] = []
        rounds = 0

        while rounds < self._max_tool_calls:
            rounds += 1

            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=self._tools.definitions(),
                temperature=0.3,  # 偏低温度，减少幻觉
            )

            msg = response.choices[0].message

            # 如果没有 tool_calls，说明 LLM 已经准备好回复
            if not msg.tool_calls:
                return AgentResponse(
                    text=msg.content or "",
                    tool_calls=all_tool_calls,
                    rounds=rounds,
                )

            # 把 LLM 的 tool_call 消息加入历史
            messages.append(msg.model_dump())  # type: ignore[arg-type]

            # 执行每个 tool_call
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    fn_args = {}

                _log.info("tool_call: %s(%s)", fn_name, fn_args)
                result = self._tools.call(fn_name, fn_args)
                all_tool_calls.append(ToolCallRecord(fn_name, fn_args, result))

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

            # 继续循环，让 LLM 看到 tool 结果后继续推理

        # 超过 max_tool_calls，强制返回最后一轮
        _log.warning("agent hit max_tool_calls=%d", self._max_tool_calls)
        return AgentResponse(
            text="（分析过程中工具调用次数过多，请缩小问题范围后重试）",
            tool_calls=all_tool_calls,
            rounds=rounds,
        )

    @property
    def tools(self) -> ToolRegistry:
        return self._tools
