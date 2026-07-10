"""MemoryService：独立记忆服务，任何 agent 入口都可调用。

把记忆注入（对话前）和记忆提取（对话后）从 AgentService.chat() 内部
提取为独立服务。这样 MCP Server、回测脚本等非 AgentService 入口
也能获得同样的记忆能力。

设计原则（与 MemoryPipeline 一致）：
- 所有组件可选，None 时静默降级
- 任何异常不向上抛，只 log warning
- get_context() 返回基础 SYSTEM_PROMPT 时表示记忆不可用

用法::

    svc = MemoryService(pipeline=pipe, memory=mem)

    # 对话前：注入记忆到 system prompt
    system_prompt = svc.get_context(query="茅台")

    # 对话后：记录 + 提取 observations/predictions
    svc.record_conversation(user_msg, assistant_resp, adapter=adapter)

    # 不带记忆的入口（MCP 工具等）
    context = svc.get_context(query="半导体")  # 如果 pipeline 存在则返回记忆
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
from mommy_chaogu.agent.prompt import SYSTEM_PROMPT

if TYPE_CHECKING:
    from mommy_chaogu.agent.memory import ConversationMemory
    from mommy_chaogu.market_data.adapter import MarketDataAdapter

_log = logging.getLogger(__name__)


class MemoryService:
    """独立记忆服务。

    封装 MemoryPipeline + ConversationMemory，提供统一的记忆接口。
    任何 agent 入口（AgentService / MCP Server / 回测）都可以使用。

    所有方法在 pipeline 或 memory 为 None 时安全降级。
    """

    def __init__(
        self,
        pipeline: MemoryPipeline | None = None,
        memory: ConversationMemory | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._memory = memory

    @property
    def has_pipeline(self) -> bool:
        """是否有完整记忆管道（build_prompt + record_analysis）。"""
        return self._pipeline is not None

    @property
    def has_memory(self) -> bool:
        """是否有对话记忆（跨轮次上下文）。"""
        return self._memory is not None

    def get_context(self, query: str | None = None) -> str:
        """获取记忆上下文，用于注入到 system prompt。

        如果 pipeline 存在，返回注入了历史事件/预测/知识的增强 prompt。
        否则返回基础 SYSTEM_PROMPT。

        Args:
            query: 用户当前查询（用于语义搜索相关历史事件）
        """
        if self._pipeline is not None:
            try:
                return self._pipeline.build_prompt(query=query)
            except Exception as e:
                _log.warning("MemoryService.get_context: pipeline.build_prompt failed: %s", e)
        return SYSTEM_PROMPT

    def get_recent_messages(self, limit: int = 10) -> list[dict[str, str]]:
        """获取最近的对话历史（用于多轮对话上下文）。

        返回 [{"role": "user"|"assistant", "content": "..."}] 列表。
        如果 memory 不存在返回空列表。
        """
        if self._memory is not None:
            try:
                return list(self._memory.recent(limit=limit))
            except Exception as e:
                _log.warning("MemoryService.get_recent_messages failed: %s", e)
        return []

    def record_conversation(
        self,
        user_msg: str,
        assistant_response: str,
        adapter: MarketDataAdapter | None = None,
    ) -> None:
        """对话结束后记录 + 提取。

        1. 把 user/assistant 消息写入对话记忆（ConversationMemory）
        2. 从对话中提取 observations + predictions（MemoryPipeline.record_analysis）

        两步独立，任一失败不影响另一步。
        """
        # 1. 写入对话记忆
        if self._memory is not None:
            try:
                self._memory.add("user", user_msg)
                self._memory.add("assistant", assistant_response)
            except Exception as e:
                _log.warning("MemoryService.record_conversation: memory.add failed: %s", e)

        # 2. 事实提取（observations + predictions）
        if self._pipeline is not None:
            try:
                self._pipeline.record_analysis(
                    user_msg,
                    assistant_response,
                    adapter=adapter,
                )
            except Exception as e:
                _log.warning(
                    "MemoryService.record_conversation: pipeline.record_analysis failed: %s",
                    e,
                )

    def stats(self) -> dict[str, Any]:
        """记忆系统状态快照（可观测性）。

        返回 episodic/prediction/semantic/insight 的统计。
        pipeline 不存在时返回空结构。
        """
        if self._pipeline is not None:
            try:
                return self._pipeline.stats()
            except Exception as e:
                _log.warning("MemoryService.stats: pipeline.stats failed: %s", e)
        return {
            "episodic_count": 0,
            "prediction_stats": {},
            "semantic_count": 0,
            "insight_count": 0,
        }
