"""NL Router：意图路由层。

正则匹配优先（零成本零延迟），未命中则 fallback 到 AgentService。

这是面向用户的统一入口：用户说自然语言，
Router 决定走预定义工作流还是通用 LLM 对话。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mommy_chaogu.workflow.engine import (
    Workflow,
    WorkflowExecutor,
    WorkflowRegistry,
    WorkflowResult,
)

_log = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """路由结果。

    Attributes:
        matched: 是否命中预定义工作流。
        workflow: 命中的工作流（matched=True 时）。
        fallback_reason: 未命中时的原因（调试用）。
    """

    matched: bool
    workflow: Workflow | None = None
    fallback_reason: str = ""


class NLRouter:
    """自然语言意图路由器。

    用法::

        router = NLRouter(registry, executor)
        route = router.route("今天怎么样")
        if route.matched:
            result = router.execute_route(route, "今天怎么样")
        else:
            # fallback to AgentService
    """

    def __init__(
        self,
        registry: WorkflowRegistry,
        executor: WorkflowExecutor | None = None,
    ) -> None:
        self._registry = registry
        self._executor = executor

    @property
    def registry(self) -> WorkflowRegistry:
        return self._registry

    def route(self, user_input: str) -> RouteResult:
        """尝试路由用户输入。

        先正则匹配预定义工作流，命中返回 Workflow；否则返回 fallback。
        """
        wf = self._registry.match(user_input)
        if wf is not None:
            return RouteResult(matched=True, workflow=wf)
        return RouteResult(
            matched=False,
            fallback_reason="未命中任何预定义工作流模式",
        )

    def execute_route(
        self,
        route: RouteResult,
        user_input: str,
        on_step_start: Any = None,
        on_step_done: Any = None,
    ) -> WorkflowResult:
        """执行路由结果。

        如果 route.matched，执行工作流；否则返回 fallback 标记。
        """
        if not route.matched or route.workflow is None:
            return WorkflowResult(
                workflow_id="fallback",
                fallback_to_agent=True,
                summary="",
            )

        if self._executor is None:
            raise RuntimeError("没有设置 WorkflowExecutor，无法执行工作流")

        return self._executor.execute(
            route.workflow,
            user_input,
            on_step_start=on_step_start,
            on_step_done=on_step_done,
        )

    def suggest_prompts(self) -> list[str]:
        """返回给用户的功能提示（不是命令，而是自然语言场景示例）。

        从每个工作流的 description + 第一个 trigger pattern 生成。
        """
        prompts: list[str] = []
        for wf in self._registry.all_workflows():
            # 取第一个 trigger pattern 作为示例
            if wf.trigger_patterns:
                prompts.append(wf.description)
        return prompts
