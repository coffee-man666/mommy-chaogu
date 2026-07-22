"""AgentService：LLM + 工具调用循环。

使用 OpenAI SDK（兼容 deepseek / kimi / 其他 provider）。

核心循环：
    用户消息 → LLM
      ↓ LLM 返回 tool_calls?
      ├─ 是 → 执行每个 tool_call → 结果回传 → 再给 LLM
      └─ 否 → 返回最终文本
循环最多 max_tool_calls 次

容错：
- 工具执行抛异常时不中断对话，错误以 {"error": ...} 形式回传给 LLM 自行恢复
- LLM 调用的瞬时错误（连接 / 限流 / 5xx）按指数退避重试，最多 max_retries 次
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
from mommy_chaogu.agent.memory_service import MemoryService
from mommy_chaogu.agent.prompt import SYSTEM_PROMPT
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

_log = logging.getLogger(__name__)


class ConversationMemoryLike(Protocol):
    """Minimal conversation-memory interface consumed by AgentService."""

    def recent(self, limit: int = 20) -> list[dict[str, Any]]: ...

    def add(self, role: str, content: str) -> int: ...


# 支持的 provider 配置
SUPPORTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "temperature": 0.2,
    },
    "openai": {
        "base_url": None,  # OpenAI 默认
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "temperature": 0.2,
    },
    "kimi": {
        "base_url": "https://api.kimi.com/coding/v1",
        "default_model": "kimi-k2.6",
        "env_key": "MOONSHOT_API_KEY",
        "temperature": 1.0,
    },
    "zai": {
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "default_model": "glm-4.7",
        "env_key": "ZAI_API_KEY",
        "temperature": 0.2,
    },
    "nova": {
        "base_url": "http://127.0.0.1:9999/v1",
        "default_model": "nova-bridge",
        "env_key": "NOVA_API_KEY",
        "temperature": None,
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
    usage: dict[str, int] = field(default_factory=dict)  # prompt/completion/total tokens
    interrupted: bool = False  # 被 cancel_event 中断


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
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        episodic: Any | None = None,
        tracker: Any | None = None,
        semantic: Any | None = None,
        vector_search: Any | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._tools = ToolRegistry(ctx)
        self._max_tool_calls = max_tool_calls
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._ctx = ctx

        # 解析 provider 配置
        provider = provider or os.environ.get("AGENT_PROVIDER", "deepseek")
        provider = provider.strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            supported = ", ".join(SUPPORTED_PROVIDERS)
            raise ValueError(f"Unsupported agent provider {provider!r}; choose one of: {supported}")
        config = SUPPORTED_PROVIDERS[provider]
        self._provider = provider
        self._completion_options = (
            {"temperature": config["temperature"]} if config["temperature"] is not None else {}
        )

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

        # 记忆服务：优先使用外部传入的，否则从 episodic/tracker/semantic 构造
        if memory_service is not None:
            self._memory_service = memory_service
        else:
            # 向后兼容：从散件构造 MemoryPipeline → MemoryService
            pipeline: MemoryPipeline | None = None
            if episodic is not None and tracker is not None:
                pipeline = MemoryPipeline(
                    episodic=episodic,
                    tracker=tracker,
                    semantic=semantic,
                    vector_search=vector_search,
                    client=self._client,
                    model=self._model,
                )
            self._memory_service = MemoryService(pipeline=pipeline, memory=None)

    def chat(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        system_override: str | None = None,
        memory: ConversationMemoryLike | None = None,
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_result: Callable[[str, bool, int, str], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        usage_out: dict[str, int] | None = None,
    ) -> AgentResponse:
        """单轮对话（可带历史），返回最终文本 + 工具调用日志。

        记忆行为：
        - 如果传入 *memory*，用它做跨轮次对话上下文 + 持久化
        - 如果 *memory_service* 存在（构造时传入），对话前注入历史事件/预测/知识，
          对话后提取 observations/predictions

        流式：
        - 如果传入 *on_chunk*，工具循环结束后会发起一次 stream=True 的最终回答调用，
          逐 delta 调 on_chunk；provider 不支持 stream 时自动回退非流式。

        取消：
        - 如果传入 *cancel_event*，每轮 LLM 调用前 + 每个工具执行前 + 流式输出途中
          检查 is_set()，命中即立即返回 interrupted=True。

        token 统计：
        - 如果传入 *usage_out*，它会被直接用作累加容器（worker 线程原地累加），
          调用方可在对话进行中实时读取——TUI 的 WorkingIndicator 靠它显示
          实时 token 数。resp.usage 与 usage_out 是同一个 dict。
        """
        ms = self._memory_service

        # 1. 构造 system prompt（注入记忆）
        if system_override:
            system_prompt = system_override
        elif ms is not None:
            system_prompt = ms.get_context(query=user_message)
        else:
            system_prompt = SYSTEM_PROMPT

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # 2. 对话历史上下文
        if memory is not None:
            # 用传入的 memory（向后兼容）
            for h in memory.recent():
                messages.append({"role": h["role"], "content": h["content"]})
        elif ms is not None and ms.has_memory:
            # 用 MemoryService 内部的对话记忆
            for h in ms.get_recent_messages():
                messages.append({"role": h["role"], "content": h["content"]})
        elif history:
            for h in history:
                messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": user_message})

        resp = self._run_loop(
            messages,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            usage_out=usage_out,
        )

        # 3. 对话后记录 + 提取
        adapter = self._ctx.adapter if self._ctx else None
        if memory is not None:
            # 向后兼容：直接用传入的 memory
            memory.add("user", user_message)
            memory.add("assistant", resp.text)
            if ms is not None:
                # 同时走 MemoryService 的提取管道
                ms.record_conversation(user_message, resp.text, adapter=adapter)
        elif ms is not None:
            ms.record_conversation(user_message, resp.text, adapter=adapter)

        return resp

    def chat_raw(
        self,
        messages: list[dict[str, Any]],
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_result: Callable[[str, bool, int, str], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        usage_out: dict[str, int] | None = None,
    ) -> AgentResponse:
        """直接传入完整 messages 列表（灵活但需自己构造格式）。"""
        return self._run_loop(
            messages,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            usage_out=usage_out,
        )

    def _create_with_retry(self, messages: list[dict[str, Any]]) -> Any:
        """调用 LLM，对瞬时错误（连接 / 限流 / 5xx）按指数退避重试。

        重试 max_retries 次后仍失败则抛出最后一次异常（上游 CLI / TUI / Web
        均有 try/except 兜底展示）。认证、参数等非瞬时错误不重试，直接抛出。
        """
        from openai import APIConnectionError, InternalServerError, RateLimitError

        retryable = (APIConnectionError, RateLimitError, InternalServerError)

        for attempt in range(self._max_retries + 1):
            try:
                return self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools.definitions(),
                    **self._completion_options,
                )
            except retryable as exc:
                if attempt >= self._max_retries:
                    _log.error("LLM 调用重试 %d 次后仍失败: %s", self._max_retries, exc)
                    raise
                delay = self._retry_base_delay * (2**attempt) + random.uniform(0, 0.5)
                _log.warning(
                    "LLM 调用失败（第 %d/%d 次）: %s — %.1fs 后重试",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _run_loop(
        self,
        messages: list[dict[str, Any]],
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_result: Callable[[str, bool, int, str], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        usage_out: dict[str, int] | None = None,
    ) -> AgentResponse:
        """核心 agent 循环：LLM → tool_calls → execute → LLM → ...

        on_tool_call 在每次工具执行前触发；on_tool_result 在执行后触发，
        签名为 (fn_name, ok, elapsed_ms, result_or_error)——TUI 用它做
        dexter 风格的 tool_start/tool_end 实时渲染。

        on_chunk：工具循环结束后，若有则发起一次 stream=True 的最终回答调用，
        逐 delta 调用。provider 不支持 stream 时回退非流式。

        cancel_event：每轮 LLM 调用前 + 每个工具执行前 + 流式输出途中检查
        is_set()，命中即返回 interrupted=True 的 AgentResponse。

        usage_out：若提供，直接作为 usage 累加容器（引用共享），调用方可在
        对话进行中实时读取累加值；AgentResponse.usage 即此 dict。
        """
        all_tool_calls: list[ToolCallRecord] = []
        rounds = 0
        total_usage: dict[str, int] = usage_out if usage_out is not None else {}

        while rounds < self._max_tool_calls:
            # 取消检查（每轮 LLM 调用前）
            if cancel_event is not None and cancel_event.is_set():
                return AgentResponse(
                    text="（已中断）",
                    tool_calls=all_tool_calls,
                    rounds=rounds,
                    usage=total_usage,
                    interrupted=True,
                )

            rounds += 1

            response = self._create_with_retry(messages)
            self._accumulate_usage(total_usage, response)

            msg = response.choices[0].message

            # 如果没有 tool_calls，说明 LLM 已经准备好回复
            if not msg.tool_calls:
                text = msg.content or ""
                # 流式最终回答：发起一次 stream=True 调用以逐 delta 输出。
                # 仅在 on_chunk 提供时启用；provider 不支持 stream 或失败时
                # _stream_final_answer 返回 None，保留非流式 text 兜底。
                if on_chunk is not None and text:
                    streamed = self._stream_final_answer(
                        messages, on_chunk, cancel_event, total_usage
                    )
                    if streamed is not None:
                        text = streamed
                # 流式输出途中被取消：已流出的部分保留，但标记 interrupted，
                # 让 UI 层按「已中断」而非「完整回答」收尾。
                if cancel_event is not None and cancel_event.is_set():
                    return AgentResponse(
                        text=text or "（已中断）",
                        tool_calls=all_tool_calls,
                        rounds=rounds,
                        usage=total_usage,
                        interrupted=True,
                    )
                return AgentResponse(
                    text=text,
                    tool_calls=all_tool_calls,
                    rounds=rounds,
                    usage=total_usage,
                )

            # 把 LLM 的 tool_call 消息加入历史
            messages.append(msg.model_dump())  # type: ignore[arg-type]

            # 执行每个 tool_call
            for tc in msg.tool_calls:
                # 取消检查（每个工具执行前）
                if cancel_event is not None and cancel_event.is_set():
                    return AgentResponse(
                        text="（已中断）",
                        tool_calls=all_tool_calls,
                        rounds=rounds,
                        usage=total_usage,
                        interrupted=True,
                    )

                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    fn_args = {}

                _log.info("tool_call: %s(%s)", fn_name, fn_args)

                if on_tool_call is not None:
                    on_tool_call(fn_name, fn_args)

                started = time.monotonic()
                try:
                    result = self._tools.call(fn_name, fn_args)
                except Exception as exc:
                    # 工具异常不中断整轮对话：把错误作为 tool 结果回传，
                    # 让 LLM 决定换工具重试，或在回答中向用户说明。
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    _log.warning("工具 %s 抛异常，错误将回传给 LLM: %s", fn_name, exc)
                    result = json.dumps({"error": f"工具执行异常: {exc}"}, ensure_ascii=False)
                    if on_tool_result is not None:
                        with contextlib.suppress(Exception):
                            on_tool_result(fn_name, False, elapsed_ms, str(exc))
                    all_tool_calls.append(ToolCallRecord(fn_name, fn_args, result))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
                    continue
                if on_tool_result is not None:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    with contextlib.suppress(Exception):
                        on_tool_result(
                            fn_name,
                            True,
                            elapsed_ms,
                            result if isinstance(result, str) else str(result),
                        )
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
            usage=total_usage,
        )

    # ------------------------------------------------------------------
    # 流式 + usage 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _accumulate_usage(total: dict[str, int], response: Any) -> None:
        """把单次 response.usage 累加到 total dict。"""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = getattr(usage, key, None)
            if val is not None:
                total[key] = total.get(key, 0) + int(val)

    def _stream_final_answer(
        self,
        messages: list[dict[str, Any]],
        on_chunk: Callable[[str], None],
        cancel_event: threading.Event | None,
        total_usage: dict[str, int] | None = None,
    ) -> str | None:
        """发起一次 stream=True 的无 tools 调用，逐 delta 调 on_chunk。

        学 dexter：工具循环已由上一轮非流式调用得出最终回答方向，这里重新发
        一次相同 messages 的流式调用（不绑 tools），把完整文本流式输出给前端。

        token 统计：流式调用是一次独立的真实计费调用（provider 照常收费），
        通过 ``stream_options={"include_usage": True}`` 让最后一个 chunk 带
        usage，计入 total_usage——之前刻意不计，导致 token 统计系统性偏低。
        provider 不支持 stream_options 时 create 直接报错，走 except 返回 None。

        返回 None 表示流式不可用（provider 不支持 / 出错 / 零 chunk），
        调用方用上一轮非流式 text 兜底；返回 str 为实际流式收集到的完整文本。
        """
        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                **self._completion_options,
            )
        except Exception as exc:
            _log.warning("stream 调用失败，回退非流式: %s", exc)
            return None

        collected: list[str] = []
        try:
            for chunk in stream:
                if cancel_event is not None and cancel_event.is_set():
                    break
                # usage 只挂在最后一个 chunk 上（include_usage），其余为 None
                if total_usage is not None:
                    self._accumulate_usage(total_usage, chunk)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    collected.append(text)
                    with contextlib.suppress(Exception):
                        on_chunk(text)
        except Exception as exc:
            _log.warning("stream 迭代中断: %s", exc)
            # 已收集的部分仍有价值，返回已得文本（可能不完整）
        # 零 chunk（迭代前即失败 / 空流）视为流式不可用，不得用空串
        # 覆盖非流式兜底答案
        return "".join(collected) if collected else None

    @property
    def tools(self) -> ToolRegistry:
        return self._tools
