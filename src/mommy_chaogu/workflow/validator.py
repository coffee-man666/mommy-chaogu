"""Validation for persisted and compiler-generated workflow specs."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from mommy_chaogu.agent.tools.registry import _TOOL_MAP, ToolRegistry
from mommy_chaogu.workflow.engine import Workflow
from mommy_chaogu.workflow.spec import WorkflowSpec


def _patterns_conflict(left: str, right: str) -> bool:
    if left == right:
        return True
    # Most hand-authored triggers are literal Chinese phrases.  Treat clear
    # containment as a conflict while avoiding an expensive regex SAT solver.
    left_literal = re.sub(r"\\[.*?]|[().*+?{}|^$]", "", left)
    right_literal = re.sub(r"\\[.*?]|[().*+?{}|^$]", "", right)
    return bool(left_literal and right_literal and (left_literal in right_literal or right_literal in left_literal))


def _workflow_patterns(item: Any) -> tuple[str, list[str]]:
    return str(item.id), list(item.trigger_patterns)


def validate_spec(
    spec: WorkflowSpec,
    tool_registry: ToolRegistry | None = None,
    *,
    existing_workflows: Iterable[Workflow | WorkflowSpec] | None = None,
) -> list[str]:
    """Return errors and ``warning:`` diagnostics for a workflow spec."""
    del tool_registry  # ToolRegistry is accepted for the public API; definitions are static.
    issues: list[str] = []
    if spec.spec_version != 1:
        issues.append(f"spec_version 不受支持: {spec.spec_version}")
    if not spec.id.startswith("user_"):
        issues.append("id 必须以 user_ 开头")
    if not spec.trigger_patterns:
        issues.append("trigger_patterns 不能为空")
    for index, pattern in enumerate(spec.trigger_patterns):
        try:
            re.compile(pattern)
        except re.error as exc:
            issues.append(f"第 {index} 个 trigger pattern 非法: {exc}")

    known_ids: set[str] = set()
    known_patterns: list[tuple[str, str]] = []
    for item in existing_workflows or ():
        workflow_id, patterns = _workflow_patterns(item)
        known_ids.add(workflow_id)
        known_patterns.extend((workflow_id, pattern) for pattern in patterns)
    if spec.id in known_ids:
        issues.append(f"工作流 id 已存在: {spec.id}")
    for pattern in spec.trigger_patterns:
        for workflow_id, existing_pattern in known_patterns:
            if _patterns_conflict(pattern, existing_pattern):
                issues.append(f"trigger 与工作流 {workflow_id} 冲突: {pattern}")

    for index, step in enumerate(spec.steps):
        tool_def = _TOOL_MAP.get(step.tool_name)
        if tool_def is None:
            issues.append(f"第 {index} 步工具不存在: {step.tool_name}")
            continue
        properties = tool_def.parameters.get("properties", {})
        for name, source in step.inputs.items():
            if name not in properties:
                issues.append(f"warning: 第 {index} 步参数 {name} 不在 {step.tool_name} 定义中")
            if source.kind == "step_field" and source.step_index >= index:
                issues.append(f"第 {index} 步引用了非前置步骤: {source.step_index}")
            if source.kind == "user_regex":
                try:
                    re.compile(source.pattern)
                except re.error as exc:
                    issues.append(f"第 {index} 步 user_regex 非法: {exc}")
            if source.kind == "param" and not source.param_name:
                issues.append(f"第 {index} 步 param source 缺少 param_name")
    return issues


def blocking_issues(issues: Iterable[str]) -> list[str]:
    return [issue for issue in issues if not issue.startswith("warning:")]
