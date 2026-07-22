"""工作流引擎：定义、注册、执行。

工作流是一组有序步骤，每步调用 ToolRegistry 中的一个工具。
与 AgentService 的 LLM 自主选工具不同，工作流是确定性的——
用户说"今天怎么样"，永远走同一组步骤，不需要 LLM 推理。

工作流的最后一步可以是 LLM 总结，但数据获取是确定性的。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from mommy_chaogu.agent.tools import ToolRegistry

_log = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================


@dataclass(frozen=True)
class WorkflowStep:
    """工作流中的一步。

    Attributes:
        tool_name: ToolRegistry 中注册的工具名（如 "get_market_indexes"）。
        args: 静态参数（如 {"limit": 10}）。
        args_extractor: 从用户输入提取动态参数的函数。
            接收 (user_input, previous_results) → dict。
        display_name: 给用户看的中文步骤名（如"正在获取大盘数据..."）。
        optional: 如果工具调用失败，是否跳过继续（默认 False）。
    """

    tool_name: str
    display_name: str
    args: dict[str, Any] = field(default_factory=dict)
    args_extractor: Callable[[str, list[dict[str, Any]]], dict[str, Any]] | None = None
    optional: bool = False


@dataclass(frozen=True)
class Workflow:
    """一个完整的用户场景工作流。

    Attributes:
        id: 唯一标识（如 "morning_brief"）。
        trigger_patterns: 正则表达式列表，用户输入匹配任一即命中。
        description: 给 LLM router 的简短描述。
        steps: 有序步骤列表。
        summary_template: 可选的 LLM 总结模板。
            如果不为 None，执行完 steps 后用模板调 LLM 做自然语言总结。
            模板中 {context} 会被替换为各步结果的 JSON。
    """

    id: str
    trigger_patterns: list[str]
    description: str
    steps: list[WorkflowStep]
    summary_template: str | None = None
    # 默认是否启用 LLM 总结（summary_template 不为 None 时才生效）
    use_llm_summary: bool = True


@dataclass
class StepResult:
    """单步执行结果。"""

    display_name: str
    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None


@dataclass
class WorkflowResult:
    """工作流执行结果。"""

    workflow_id: str
    steps: list[StepResult] = field(default_factory=list)
    summary: str = ""
    # 未命中工作流时，router 设置此字段让调用方走 AgentService
    fallback_to_agent: bool = False

    @property
    def succeeded(self) -> bool:
        """是否成功执行（至少一步成功且无致命错误）。"""
        return any(s.success for s in self.steps)


# ============================================================
# 注册表
# ============================================================


class WorkflowRegistry:
    """工作流注册 + 匹配。

    用法::

        registry = WorkflowRegistry()
        registry.register(workflow)
        match = registry.match("今天怎么样")  # → Workflow or None
    """

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        """注册一个工作流。"""
        if workflow.id in self._workflows:
            raise ValueError(f"工作流 {workflow.id} 已注册")
        self._workflows[workflow.id] = workflow

    def get(self, workflow_id: str) -> Workflow | None:
        """按 ID 获取工作流。"""
        return self._workflows.get(workflow_id)

    def all_workflows(self) -> list[Workflow]:
        """返回所有已注册的工作流。"""
        return list(self._workflows.values())

    def match(self, user_input: str) -> Workflow | None:
        """尝试用正则匹配用户输入。

        返回第一个命中的 Workflow，如果没有则返回 None。
        """
        text = user_input.strip()
        for wf in self._workflows.values():
            for pattern in wf.trigger_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    _log.debug("工作流 %s 命中 (pattern=%s)", wf.id, pattern)
                    return wf
        return None


# ============================================================
# 执行器
# ============================================================


class LLMSummarizer(Protocol):
    """LLM 总结接口（避免依赖具体 AgentService）。"""

    def summarize(self, template: str, context: str) -> str:
        """用模板和上下文调 LLM 生成自然语言总结。"""
        ...


class WorkflowExecutor:
    """执行工作流。

    用法::

        executor = WorkflowExecutor(tool_registry)
        result = executor.execute(workflow, "今天怎么样")
        print(result.summary)
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_summarizer: LLMSummarizer | None = None,
    ) -> None:
        self._tools = tool_registry
        self._llm = llm_summarizer

    def execute(
        self,
        workflow: Workflow,
        user_input: str,
        on_step_start: Callable[[str], None] | None = None,
        on_step_done: Callable[[str, bool], None] | None = None,
    ) -> WorkflowResult:
        """按顺序执行工作流的所有步骤。

        Args:
            workflow: 要执行的工作流。
            user_input: 用户的原始输入（供 args_extractor 使用）。
            on_step_start: 步骤开始时的回调（显示进度用）。
            on_step_done: 步骤完成时的回调（显示进度用）。
        """
        result = WorkflowResult(workflow_id=workflow.id)
        step_results: list[dict[str, Any]] = []

        for step in workflow.steps:
            # 构建参数
            args = dict(step.args)
            if step.args_extractor:
                extracted = step.args_extractor(user_input, step_results)
                args.update(extracted)

            # 进度回调
            if on_step_start:
                on_step_start(step.display_name)

            # 执行工具调用
            try:
                raw = self._tools.call(step.tool_name, args)
                parsed = _safe_parse_json(raw)
                # registry.call 把工具失败转成 {"error": ...} JSON 字符串返回，
                # 并不抛出——必须检查 payload 的 error 键，否则失败步骤一律
                # 记为 success，optional/break 逻辑成为死代码（T2）。
                # 非 JSON 结果（纯文本）不会是 dict，不误判。
                if isinstance(parsed, dict) and "error" in parsed:
                    sr = StepResult(
                        display_name=step.display_name,
                        tool_name=step.tool_name,
                        success=False,
                        error=str(parsed["error"]),
                    )
                else:
                    sr = StepResult(
                        display_name=step.display_name,
                        tool_name=step.tool_name,
                        success=True,
                        data=parsed,
                    )
                    step_results.append(
                        {"step": step.display_name, "tool": step.tool_name, "result": parsed}
                    )
            except Exception as e:
                _log.warning("工作流步骤 %s 失败: %s", step.display_name, e)
                sr = StepResult(
                    display_name=step.display_name,
                    tool_name=step.tool_name,
                    success=False,
                    error=str(e),
                )

            result.steps.append(sr)

            if not sr.success and not step.optional:
                if on_step_done:
                    on_step_done(step.display_name, False)
                break  # 非可选步骤失败，终止工作流

            if on_step_done:
                on_step_done(step.display_name, sr.success)

        # LLM 总结
        if workflow.summary_template and workflow.use_llm_summary and self._llm:
            import json

            context = json.dumps(step_results, ensure_ascii=False, default=str)
            try:
                result.summary = self._llm.summarize(workflow.summary_template, context)
            except Exception as e:
                _log.warning("LLM 总结失败: %s", e)
                result.summary = _format_fallback(workflow.id, result)

        return result


# ============================================================
# 辅助函数
# ============================================================


def _safe_parse_json(raw: str) -> Any:
    """尝试解析 JSON，失败则返回原始字符串。"""
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _format_fallback(workflow_id: str, result: WorkflowResult) -> str:
    """LLM 总结失败时的简单格式化输出。"""
    lines: list[str] = []
    for sr in result.steps:
        if sr.success and sr.data:
            lines.append(f"**{sr.display_name}**")
            if isinstance(sr.data, dict):
                # 简单提取关键字段
                for k in ("summary", "text", "name", "change_pct"):
                    if k in sr.data:
                        lines.append(f"  {k}: {sr.data[k]}")
            elif isinstance(sr.data, list):
                lines.append(f"  共 {len(sr.data)} 条")
            lines.append("")
    return "\n".join(lines) if lines else "（数据获取完成，但总结失败）"
