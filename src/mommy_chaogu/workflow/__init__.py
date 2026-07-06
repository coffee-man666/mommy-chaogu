"""自然语言工作流模块。

把多个工具调用编排成面向用户场景的工作流，
让非技术用户用一句自然语言完成复杂操作。

核心组件：
- Workflow / WorkflowStep — 工作流定义
- WorkflowRegistry — 注册 + 按 pattern 匹配
- WorkflowExecutor — 按 steps 顺序执行
- NLRouter — 意图路由（正则匹配优先，fallback 到 AgentService）
"""

from mommy_chaogu.workflow.engine import (
    Workflow,
    WorkflowExecutor,
    WorkflowRegistry,
    WorkflowResult,
    WorkflowStep,
)
from mommy_chaogu.workflow.router import NLRouter, RouteResult

__all__ = [
    "NLRouter",
    "RouteResult",
    "Workflow",
    "WorkflowExecutor",
    "WorkflowRegistry",
    "WorkflowResult",
    "WorkflowStep",
]
