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
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from mommy_chaogu.agent import llm as llm_provider
from mommy_chaogu.agent.llm import SUPPORTED_PROVIDERS  # noqa: F401  (re-export, 向后兼容)
from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
from mommy_chaogu.agent.memory_service import MemoryService
from mommy_chaogu.agent.prompt import SYSTEM_PROMPT
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

_log = logging.getLogger(__name__)


class _RetryCancelledError(Exception):
    """重试等待期间被 cancel_event 中断（内部使用，_run_loop 捕获）。"""


class ConversationMemoryLike(Protocol):
    """Minimal conversation-memory interface consumed by AgentService."""

    def recent(self, limit: int = 20) -> list[dict[str, Any]]: ...

    def add(self, role: str, content: str) -> int: ...


@dataclass
class _LoopToolCall:
    """agent 循环内部统一的 tool_call 形态（非流式 / 流式收集共用）。"""

    id: str
    name: str
    arguments: str  # JSON 字符串（可能不完整，由调用方 json.loads 容错）


@dataclass
class _LoopMessage:
    """agent 循环内部统一的 assistant 消息形态。"""

    content: str | None
    tool_calls: list[_LoopToolCall] | None

    @classmethod
    def from_response(cls, response: Any) -> _LoopMessage:
        """从非流式 ChatCompletion 提取。"""
        msg = response.choices[0].message
        tool_calls = (
            [
                _LoopToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
                for tc in msg.tool_calls
            ]
            if msg.tool_calls
            else None
        )
        return cls(content=msg.content, tool_calls=tool_calls)

    def to_history(self) -> dict[str, Any]:
        """转成可追加进 messages 历史的 dict。

        只保留 OpenAI 协议字段（role/content/tool_calls），不带
        ``model_dump()`` 里的多余字段（refusal / annotations 等），
        避免严格 provider 拒收。
        """
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in self.tool_calls or []
            ],
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
        timeout: float = llm_provider.DEFAULT_TIMEOUT,
        episodic: Any | None = None,
        tracker: Any | None = None,
        semantic: Any | None = None,
        vector_search: Any | None = None,
        memory_service: MemoryService | None = None,
        token_tracker: Any | None = None,
    ) -> None:
        self._tools = ToolRegistry(ctx)
        self._max_tool_calls = max_tool_calls
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._ctx = ctx

        # 解析 provider 配置（单一真相源：agent/llm.py）
        provider = llm_provider.resolve_provider(provider)
        self._provider = provider
        self._completion_options = llm_provider.completion_options(provider)

        self._model = llm_provider.resolve_model(provider, model)

        # 构造 OpenAI client（显式 timeout + 关闭 SDK 内置重试，重试由
        # _create_with_retry 统一负责，避免双层重试叠加）
        self._client = llm_provider.create_client(provider, api_key, timeout=timeout)

        # 把 LLM client 回写到 ToolContext：记忆工具（search_similar_events /
        # get_market_narrative）以 ctx.client 为门，装配处不再单独赋值。
        # embedding_model 为 None 表示 provider 无 embedding 接口，
        # 向量检索据此显式降级（而不是把聊天模型名当 embedding 模型传）。
        ctx.client = self._client
        ctx.model = self._model
        ctx.embedding_model = llm_provider.embedding_model_for(provider)

        # TokenTracker：显式传入优先；否则有 agent_db 时自建（成本可观测性
        # 默认开启）。初始化失败不阻塞 agent（降级为不追踪）。
        self._token_tracker = token_tracker
        if self._token_tracker is None:
            agent_db = ctx.resolved_agent_db
            if agent_db is not None:
                try:
                    from mommy_chaogu.agent.token_tracker import TokenTracker

                    self._token_tracker = TokenTracker(agent_db)
                except Exception as e:
                    _log.warning("TokenTracker 初始化失败，token 追踪降级关闭: %s", e)

        # usage 累加锁：后台提取线程（P6 异步化）与主线程可能同时累加
        # 同一个 usage dict，必须串行化。
        self._usage_lock = threading.Lock()
        # 后台记忆任务（对话后提取）线程句柄，供 flush() 等待。
        self._bg_threads: list[threading.Thread] = []

        # 记忆服务：优先使用外部传入的，否则从 episodic/tracker/semantic 构造
        if memory_service is not None:
            self._memory_service = memory_service
        else:
            # 向量检索：显式传入优先；未传但有 embedding 模型 + episodic 时
            # 自建（CLI/TUI/Web 入口经此自动接线；provider 无 embedding
            # 接口时 embedding_model=None，保持关键词降级）。构造失败
            # 不阻塞对话，降级为 None。
            if vector_search is None and episodic is not None and ctx.embedding_model is not None:
                from mommy_chaogu.agent.vector_search import VectorSearch

                try:
                    vector_search = VectorSearch(episodic, self._client, model=ctx.embedding_model)
                except Exception as e:
                    _log.warning("VectorSearch 初始化失败，向量检索降级关闭: %s", e)
                    vector_search = None

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
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
        system_addendum: str | None = None,
        on_predictions_created: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> AgentResponse:
        """单轮对话（可带历史），返回最终文本 + 工具调用日志。

        记忆行为：
        - 如果传入 *memory*，用它做跨轮次对话上下文 + 持久化
        - 如果 *memory_service* 存在（构造时传入），对话前注入历史事件/预测/知识，
          对话后提取 observations/predictions

        流式：
        - 如果传入 *on_chunk*，每轮 LLM 调用直接走 stream=True（带 tools），
          最终回答的文本逐 delta 调 on_chunk——「出答案」与「流式输出」是
          同一次调用；provider 不支持 stream 时自动回退非流式。

        取消：
        - 如果传入 *cancel_event*，每轮 LLM 调用前 + 每个工具执行前 + 流式输出途中
          + 重试等待期间检查 is_set()，命中即立即返回 interrupted=True
          （中断的对话不写入记忆）。

        状态：
        - 如果传入 *on_status*，LLM 重试时回调 ("retry", {attempt, max, delay})，
          供 UI 展示重试进度（而不是静止的"思考中"）。

        记忆：
        - 对话后的记录 + 提取（LLM 调用 + 报价补全）在后台 daemon 线程执行，
          不阻塞本次响应；单发进程（CLI 单次查询）退出前应调 flush() 等待完成。
        - 如果传入 *on_predictions_created*，后台提取线程在 record_conversation
          完成且本轮确实创建了预测时回调它（参数为 [{"id", "code", "name"}, ...]）；
          回调本身抛异常只记日志，不影响后台线程。

        token 统计：
        - 如果传入 *usage_out*，它会被直接用作累加容器（worker 线程原地累加），
          调用方可在对话进行中实时读取——TUI 的 WorkingIndicator 靠它显示
          实时 token 数。resp.usage 与 usage_out 是同一个 dict。后台提取
          线程的 token 消耗也会累加进来（同一把锁保护）。
        """
        ms = self._memory_service

        # 1. 构造 system prompt（注入记忆）
        if system_override:
            system_prompt = system_override
        elif ms is not None:
            system_prompt = ms.get_context(query=user_message)
        else:
            system_prompt = SYSTEM_PROMPT

        if system_addendum:
            system_prompt = f"{system_prompt.rstrip()}\n\n{system_addendum.strip()}"

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # 2. 对话历史上下文（带字符预算：跨轮历史按条数注入会把长回答
        # 反复灌进 context 且每轮重复计费——从最新往回装，超出预算丢弃
        # 最旧的消息，L2）
        if memory is not None:
            # 用传入的 memory（向后兼容）
            self._append_history(messages, memory.recent())
        elif ms is not None and ms.has_memory:
            # 用 MemoryService 内部的对话记忆
            self._append_history(messages, ms.get_recent_messages())
        elif history:
            self._append_history(messages, history)

        messages.append({"role": "user", "content": user_message})

        resp = self._run_loop(
            messages,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            usage_out=usage_out,
            on_status=on_status,
        )

        # 3. 对话后记录 + 提取
        # 中断的对话不记录、不提取——"（已中断）"不是真实 assistant 回复，
        # 写入记忆会污染上下文与提取管道。
        if resp.interrupted:
            return resp

        adapter = self._ctx.adapter if self._ctx else None
        if memory is not None:
            # 向后兼容：直接用传入的 memory 写入对话历史
            memory.add("user", user_message)
            memory.add("assistant", resp.text)
        if ms is not None:
            # 提取链（LLM 调用 + 逐条预测实时报价）是慢操作，放后台线程跑，
            # 不阻塞响应（P6）。write_messages=False 避免与上面 memory.add
            # 双写（外部 memory 与 MemoryService 内部 memory 并存时）。
            def _record_and_notify() -> None:
                created = ms.record_conversation(
                    user_message,
                    resp.text,
                    adapter=adapter,
                    write_messages=memory is None,
                    usage_out=resp.usage,
                    usage_lock=self._usage_lock,
                )
                if created and on_predictions_created is not None:
                    try:
                        on_predictions_created(created)
                    except Exception:
                        _log.warning("on_predictions_created 回调失败", exc_info=True)

            self._spawn_background(_record_and_notify)

        return resp

    def flush(self, timeout: float | None = None) -> None:
        """等待所有后台记忆任务（对话后提取）完成。

        *timeout* 是**每个**线程的 join 上限（不是总预算）——N 个存活线程
        最坏等待 N × timeout。测试用它保证提取落库后再断言；单发进程
        （CLI 单次查询）退出前必须调用，否则 daemon 线程随进程退出被
        静默丢弃。长驻进程（TUI / Web）依赖 daemon 语义，可不调用。
        """
        for t in list(self._bg_threads):
            t.join(timeout=timeout)
        self._bg_threads = [t for t in self._bg_threads if t.is_alive()]

    def _spawn_background(self, fn: Any, *args: Any, **kwargs: Any) -> threading.Thread:
        """在 daemon 线程里跑后台任务，异常只记日志不上抛。"""
        # 顺手清理已结束的线程句柄，避免长驻进程无界累积
        self._bg_threads = [t for t in self._bg_threads if t.is_alive()]

        def _run() -> None:
            try:
                fn(*args, **kwargs)
            except Exception:
                _log.warning("后台记忆任务失败: %s", fn, exc_info=True)

        t = threading.Thread(target=_run, daemon=True)
        self._bg_threads.append(t)
        t.start()
        return t

    def chat_raw(
        self,
        messages: list[dict[str, Any]],
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_result: Callable[[str, bool, int, str], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        usage_out: dict[str, int] | None = None,
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> AgentResponse:
        """直接传入完整 messages 列表（灵活但需自己构造格式）。"""
        return self._run_loop(
            messages,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            usage_out=usage_out,
            on_status=on_status,
        )

    def _create_with_retry(
        self,
        messages: list[dict[str, Any]],
        cancel_event: threading.Event | None = None,
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> Any:
        """调用 LLM，对瞬时错误（连接 / 限流 / 5xx）按指数退避重试。

        重试 max_retries 次后仍失败则抛出最后一次异常（上游 CLI / TUI / Web
        均有 try/except 兜底展示）。认证、参数等非瞬时错误不重试，直接抛出。
        RateLimitError 带 Retry-After 响应头时按服务器要求等待。
        重试等待用 ``cancel_event.wait``——Esc 在等待期间也能即时中断
        （抛 _RetryCancelledError，由 _run_loop 转成 interrupted 响应）。
        *on_status* 在每次重试前回调 ``("retry", {attempt, max, delay})``，
        供 UI 展示「正在重试 (1/3)」，而不是让用户对着静止屏幕猜。
        """
        from openai import APIConnectionError, InternalServerError, RateLimitError

        retryable = (APIConnectionError, RateLimitError, InternalServerError)

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools.definitions(),
                    **self._completion_options,
                )
                self._track_usage(response)
                return response
            except retryable as exc:
                if attempt >= self._max_retries:
                    _log.error("LLM 调用重试 %d 次后仍失败: %s", self._max_retries, exc)
                    raise
                delay = self._retry_delay(exc, attempt)
                _log.warning(
                    "LLM 调用失败（第 %d/%d 次）: %s — %.1fs 后重试",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )
                if on_status is not None:
                    with contextlib.suppress(Exception):
                        on_status(
                            "retry",
                            {
                                "attempt": attempt + 1,
                                "max": self._max_retries + 1,
                                "delay": delay,
                                "error": str(exc),
                            },
                        )
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise _RetryCancelledError from None
                else:
                    time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _retry_delay(self, exc: Exception, attempt: int) -> float:
        """计算重试等待：限流时优先读 Retry-After 响应头，否则指数退避 + jitter。"""
        from openai import RateLimitError

        if isinstance(exc, RateLimitError):
            response = getattr(exc, "response", None)
            headers = getattr(response, "headers", None)
            if headers is not None:
                retry_after = headers.get("retry-after")
                if retry_after is not None:
                    try:
                        return max(0.0, float(retry_after))
                    except (TypeError, ValueError):
                        pass
        return self._retry_base_delay * (2**attempt) + random.uniform(0, 0.5)

    def _track_usage(self, response: Any, phase: str = "agent") -> None:
        """把一次 LLM 调用记进 TokenTracker（成本可观测性）。失败不阻塞主流程。"""
        if self._token_tracker is None:
            return
        try:
            self._token_tracker.record_from_response(response, model=self._model, phase=phase)
        except Exception as e:
            _log.warning("TokenTracker 记录失败: %s", e)

    def _run_loop(
        self,
        messages: list[dict[str, Any]],
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_result: Callable[[str, bool, int, str], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        usage_out: dict[str, int] | None = None,
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> AgentResponse:
        """核心 agent 循环：LLM → tool_calls → execute → LLM → ...

        on_tool_call 在每次工具执行前触发；on_tool_result 在执行后触发，
        签名为 (fn_name, ok, elapsed_ms, result_or_error)——TUI 用它做
        dexter 风格的 tool_start/tool_end 实时渲染。

        on_chunk：若提供，每轮 LLM 调用直接走 stream=True（带 tools）——
        文本 delta 逐段回调，tool_calls delta 同步拼接；最终回答的「出答案」
        与「流式输出」是同一次调用。provider 不支持 stream 时回退非流式。

        cancel_event：每轮 LLM 调用前 + 每个工具执行前 + 流式输出途中 +
        重试等待期间检查 is_set()，命中即返回 interrupted=True 的 AgentResponse。

        on_status：重试等状态变化回调（("retry", {attempt, max, delay})），
        供 UI 展示重试进度。

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

            try:
                msg = self._next_message(
                    messages,
                    on_chunk=on_chunk,
                    cancel_event=cancel_event,
                    total_usage=total_usage,
                    on_status=on_status,
                )
            except _RetryCancelledError:
                # 重试等待期间被 Esc 中断
                return AgentResponse(
                    text="（已中断）",
                    tool_calls=all_tool_calls,
                    rounds=rounds,
                    usage=total_usage,
                    interrupted=True,
                )

            # 如果没有 tool_calls，说明 LLM 已经准备好回复
            if not msg.tool_calls:
                text = msg.content or ""
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

            # 把 LLM 的 tool_call 消息加入历史（只保留协议字段，不带
            # model_dump() 的多余字段，严格 provider 也能收）
            messages.append(msg.to_history())

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

                fn_name = tc.name
                try:
                    fn_args = json.loads(tc.arguments)
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
    def _append_history(
        messages: list[dict[str, Any]],
        items: Any,
        budget: int = 6000,
    ) -> None:
        """把历史消息注入 messages，总字符不超过 *budget*（≈3k tokens）。

        从最新消息往回装：超预算时丢弃最旧的消息（最新上下文价值最高）。
        至少保留最新一条（即使它自己就超预算——截断单条不如整条保留
        让 LLM 看到最近说了什么）。
        """
        picked: list[dict[str, str]] = []
        remaining = budget
        for h in reversed(list(items)):
            cost = len(h["content"])
            if picked and remaining - cost < 0:
                break
            picked.append({"role": h["role"], "content": h["content"]})
            remaining -= cost
        messages.extend(reversed(picked))

    def _next_message(
        self,
        messages: list[dict[str, Any]],
        on_chunk: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
        total_usage: dict[str, int],
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> _LoopMessage:
        """发起一轮 LLM 调用并返回统一形态的消息。

        传了 *on_chunk* 时这一轮直接走 stream=True（带 tools）：最终回答的
        文本边收边回调，tool_calls deltas 同步拼接——「得出答案」与「流式
        输出」是同一次调用，不再像旧实现那样非流式出答案后再把全量
        messages 重发一次流式（双重计费，EVALUATION-2026-07-18 L1）。
        流式不可用（provider 不支持 / 非瞬时错误 / 零 chunk）时回退非流式
        调用；create 阶段的瞬时错误（连接/限流/5xx）先按重试策略重试，
        重试耗尽后与非流式路径一样抛异常。
        """
        if on_chunk is not None:
            streamed = self._create_stream_with_retry(
                messages, on_chunk, cancel_event, total_usage, on_status
            )
            if streamed is not None:
                return streamed
            # 流式不可用（尚未流出任何内容），安全回退非流式
        response = self._create_with_retry(messages, cancel_event, on_status)
        self._accumulate_usage(total_usage, response)
        return _LoopMessage.from_response(response)

    def _accumulate_usage(self, total: dict[str, int], response: Any) -> None:
        """把单次 response.usage 累加到 total dict（线程安全）。

        后台提取线程（对话后异步提取）与主线程可能同时累加同一个
        usage dict，累加必须串行化。
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        with self._usage_lock:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                val = getattr(usage, key, None)
                if val is not None:
                    total[key] = total.get(key, 0) + int(val)

    def _create_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        on_chunk: Callable[[str], None],
        cancel_event: threading.Event | None,
        total_usage: dict[str, int],
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> _LoopMessage | None:
        """stream=True（带 tools）调用：文本 delta 回调 + tool_calls 拼接。

        只对 create 阶段的瞬时错误重试（此时尚未流出任何内容）；迭代开始
        后不再重试——已流出的文本无法收回，中途异常用已收集内容收尾。
        零收集（迭代前即失败 / 空流）返回 None，调用方回退非流式。
        重试等待用 ``cancel_event.wait``，Esc 可即时中断（_RetryCancelledError）。

        token 统计：``stream_options={"include_usage": True}`` 让最后一个
        chunk 带 usage，计入 total_usage 并进 TokenTracker。
        """
        from openai import APIConnectionError, InternalServerError, RateLimitError

        retryable = (APIConnectionError, RateLimitError, InternalServerError)

        stream = None
        for attempt in range(self._max_retries + 1):
            try:
                stream = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools.definitions(),
                    stream=True,
                    stream_options={"include_usage": True},
                    **self._completion_options,
                )
                break
            except retryable as exc:
                if attempt >= self._max_retries:
                    _log.error("stream 调用重试 %d 次后仍失败: %s", self._max_retries, exc)
                    raise
                delay = self._retry_delay(exc, attempt)
                _log.warning(
                    "stream 调用失败（第 %d/%d 次）: %s — %.1fs 后重试",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )
                if on_status is not None:
                    with contextlib.suppress(Exception):
                        on_status(
                            "retry",
                            {
                                "attempt": attempt + 1,
                                "max": self._max_retries + 1,
                                "delay": delay,
                                "error": str(exc),
                            },
                        )
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise _RetryCancelledError from None
                else:
                    time.sleep(delay)
            except Exception as exc:
                _log.warning("stream 调用失败，回退非流式: %s", exc)
                return None
        if stream is None:  # pragma: no cover - 上面循环要么 break 要么 raise/return
            return None

        collected: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}  # index → {id, name, arguments 分片}
        usage_chunk: Any | None = None
        try:
            for chunk in stream:
                if cancel_event is not None and cancel_event.is_set():
                    break
                # usage 只挂在最后一个 chunk 上（include_usage），其余为 None
                if getattr(chunk, "usage", None) is not None:
                    usage_chunk = chunk
                    self._accumulate_usage(total_usage, chunk)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    collected.append(text)
                    with contextlib.suppress(Exception):
                        on_chunk(text)
                for tc_delta in getattr(delta, "tool_calls", None) or []:
                    slot = tool_acc.setdefault(
                        tc_delta.index, {"id": "", "name": "", "arguments": []}
                    )
                    if tc_delta.id:
                        slot["id"] += tc_delta.id
                    fn = getattr(tc_delta, "function", None)
                    if fn is not None:
                        if fn.name:
                            slot["name"] += fn.name
                        if fn.arguments:
                            slot["arguments"].append(fn.arguments)
        except Exception as exc:
            _log.warning("stream 迭代中断，用已收集内容收尾: %s", exc)

        if usage_chunk is not None:
            self._track_usage(usage_chunk)

        # 零收集（迭代前即失败 / 空流）视为流式不可用，回退非流式
        if not collected and not tool_acc:
            return None

        tool_calls = [
            _LoopToolCall(
                id=slot["id"] or f"call_{index}",
                name=slot["name"],
                arguments="".join(slot["arguments"]),
            )
            for index, slot in sorted(tool_acc.items())
        ] or None
        return _LoopMessage(content="".join(collected) or None, tool_calls=tool_calls)

    @property
    def tools(self) -> ToolRegistry:
        return self._tools
