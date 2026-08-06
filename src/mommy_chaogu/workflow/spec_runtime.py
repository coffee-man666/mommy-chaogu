"""Runtime adapter from :mod:`workflow.spec` to the existing engine."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from mommy_chaogu.workflow.engine import Workflow, WorkflowStep
from mommy_chaogu.workflow.spec import ArgSource, StepSpec, WorkflowSpec

CodeExtractor = Callable[[Any], list[str]]


def _codes_from_items(items: Any) -> list[str]:
    if not isinstance(items, list):
        raise ValueError("结果字段不是数组，无法提取 codes")
    codes: list[str] = []
    for item in items:
        if not isinstance(item, dict) or "code" not in item:
            raise ValueError("结果数组中的每一项都必须包含 code")
        codes.append(str(item["code"]))
    return codes[:50]


def _extract_watchlist_codes(result: Any) -> list[str]:
    if isinstance(result, list):
        return _codes_from_items(result)
    if isinstance(result, dict) and "groups" in result:
        groups = result["groups"]
        if not isinstance(groups, list):
            raise ValueError("get_watchlist.groups 必须是数组")
        items: list[Any] = []
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("get_watchlist.groups 中存在非法项")
            stocks = group.get("stocks", [])
            if not isinstance(stocks, list):
                raise ValueError("get_watchlist.groups[].stocks 必须是数组")
            items.extend(stocks)
        return _codes_from_items(items)
    raise ValueError("无法识别 get_watchlist 输出形状")


def _extract_portfolio_codes(result: Any) -> list[str]:
    if not isinstance(result, dict) or "positions" not in result:
        raise ValueError("无法识别 get_portfolio 输出形状")
    return _codes_from_items(result["positions"])


def _extract_from_results(result: Any) -> list[str]:
    if not isinstance(result, dict) or "results" not in result:
        raise ValueError("积木输出必须包含 results 数组，无法提取 codes")
    return _codes_from_items(result["results"])


KNOWN_CODE_EXTRACTORS: dict[str, CodeExtractor] = {
    "get_watchlist": _extract_watchlist_codes,
    "get_portfolio": _extract_portfolio_codes,
}


def _extract_field(step_data: dict[str, Any], field: str) -> Any:
    result = step_data.get("result")
    if field == "codes":
        tool_name = str(step_data.get("tool", ""))
        extractor = KNOWN_CODE_EXTRACTORS.get(tool_name, _extract_from_results)
        return extractor(result)
    if isinstance(result, dict) and field in result:
        return result[field]
    raise ValueError(f"前置步骤结果没有字段: {field}")


def _resolve_source(
    source: ArgSource,
    user_input: str,
    previous: list[dict[str, Any]],
    params: dict[str, Any],
) -> Any:
    if source.kind == "literal":
        return source.value
    if source.kind == "param":
        if not source.param_name:
            raise ValueError("param source 缺少 param_name")
        if source.param_name not in params:
            raise ValueError(f"未提供工作流参数: {source.param_name}")
        return params[source.param_name]
    if source.kind == "user_regex":
        if not source.pattern:
            raise ValueError("user_regex source 缺少 pattern")
        match = re.search(source.pattern, user_input, re.IGNORECASE)
        if match is None:
            raise ValueError(f"用户输入未匹配正则: {source.pattern}")
        return match.group(1) if match.lastindex else match.group(0)
    if source.kind == "step_field":
        if source.step_index >= len(previous):
            raise ValueError(f"前置步骤索引不存在: {source.step_index}")
        return _extract_field(previous[source.step_index], source.field)
    raise ValueError(f"未知 ArgSource.kind: {source.kind}")


def _step_extractor(
    step: StepSpec,
    params: dict[str, Any],
) -> Callable[[str, list[dict[str, Any]]], dict[str, Any]]:
    def extract(user_input: str, previous: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            name: _resolve_source(source, user_input, previous, params)
            for name, source in step.inputs.items()
        }

    return extract


def spec_to_workflow(
    spec: WorkflowSpec,
    param_overrides: dict[str, Any] | None = None,
) -> Workflow:
    params = {**spec.params, **(param_overrides or {})}
    steps = [
        WorkflowStep(
            tool_name=step.tool_name,
            display_name=step.display_name,
            args_extractor=_step_extractor(step, params),
            optional=step.optional,
        )
        for step in spec.steps
    ]
    safe_description = spec.description.replace("{", "{{").replace("}", "}}")
    summary_template = spec.summary_template or (
        f"请基于以下工作流数据，用通俗、简洁的中文总结‘{safe_description}’的结果。"
        "只引用数据中明确出现的事实，不做额外计算。\n\n数据：{context}"
    )
    return Workflow(
        id=spec.id,
        trigger_patterns=list(spec.trigger_patterns),
        description=spec.description,
        steps=steps,
        summary_template=summary_template,
        use_llm_summary=spec.use_llm_summary,
    )
