"""LLM boundary that turns a trading viewpoint into a validated spec."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from mommy_chaogu.agent.tools.registry import _TOOL_DEFINITIONS
from mommy_chaogu.workflow.engine import Workflow
from mommy_chaogu.workflow.spec import WorkflowSpec
from mommy_chaogu.workflow.validator import blocking_issues, validate_spec

ChatRaw = Callable[[list[dict[str, str]]], Any]


@dataclass
class CompileResult:
    kind: Literal["spec", "questions", "error"]
    spec: WorkflowSpec | None = None
    questions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    guidance: str = ""


def _response_text(response: Any) -> str:
    return str(getattr(response, "text", response))


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM 没有返回 JSON") from None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM JSON 无法解析: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM 返回的 JSON 顶层必须是对象")
    return parsed


class WorkflowCompiler:
    def __init__(
        self,
        chat_raw: ChatRaw,
        *,
        existing_workflows: Iterable[Workflow] | None = None,
    ) -> None:
        self._chat_raw = chat_raw
        self._existing_workflows = list(existing_workflows or ())

    def _prompt(self, viewpoint: str, current_spec: WorkflowSpec | None, retry: str = "") -> str:
        tool_directory = json.dumps(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in _TOOL_DEFINITIONS
            ],
            ensure_ascii=False,
            indent=2,
        )
        old = f"\n当前 spec（update 时必须在此基础上修改）：\n{current_spec.to_json()}\n" if current_spec else ""
        retry_text = f"\n上一次错误，请修正：\n{retry}\n" if retry else ""
        return f"""你是交易工作流编译器。只负责把用户观点转成 JSON spec，不做行情计算。
观点：{viewpoint}
{old}{retry_text}
可用工具目录（只能使用这些工具）：
{tool_directory}

参考样例：
1. 自选股资金筛选：get_watchlist → screen_inflow_stocks(codes=step_field, threshold_bp=param)
2. 持仓业绩检查：get_portfolio → check_earnings_catalyst(codes=step_field)
3. 指定代码 K 线：check_kline_signal(codes=user_regex, signal=literal)

只允许输出以下两种 JSON 之一，不要 Markdown：
{{"kind":"questions","questions":["需要澄清的问题"]}}
或 {{"kind":"spec","id":"user_example","trigger_patterns":["..."],"description":"...",
"steps":[{{"tool_name":"screen_inflow_stocks","display_name":"筛选资金流","inputs":{{
"codes":{{"kind":"step_field","step_index":0,"field":"codes"}},
"threshold_bp":{{"kind":"param","param_name":"threshold_bp"}}}}}}],
"params":{{"threshold_bp":50}},"summary_template":null,"use_llm_summary":true,"spec_version":1}}
规则：id 必须 user_ 开头；step_field 只能引用前置步骤；参数值必须来自 literal、user_regex、step_field 或 param；
积木结果遵守 results/count/total 契约，codes 只能从 get_watchlist/get_portfolio 或 results 提取。
"""

    def _call(self, prompt: str) -> dict[str, Any]:
        response = self._chat_raw(
            [
                {"role": "system", "content": "你严格输出工作流 JSON。"},
                {"role": "user", "content": prompt},
            ]
        )
        return _parse_json(_response_text(response))

    def _interpret(
        self,
        payload: dict[str, Any],
        current_spec: WorkflowSpec | None,
    ) -> CompileResult:
        kind = payload.get("kind")
        if kind == "questions":
            questions = payload.get("questions", [])
            if not isinstance(questions, list):
                return CompileResult("error", errors=["questions 必须是数组"])
            return CompileResult("questions", questions=[str(question) for question in questions])
        if kind != "spec":
            return CompileResult("error", errors=["kind 必须是 spec 或 questions"])
        try:
            spec = WorkflowSpec.from_dict(payload)
        except (TypeError, ValueError) as exc:
            return CompileResult("error", errors=[str(exc)])
        if current_spec is not None:
            spec = WorkflowSpec(
                id=current_spec.id,
                trigger_patterns=spec.trigger_patterns,
                description=spec.description,
                steps=spec.steps,
                summary_template=spec.summary_template,
                use_llm_summary=spec.use_llm_summary,
                params=spec.params,
                spec_version=spec.spec_version,
            )
        issues = validate_spec(spec, existing_workflows=self._existing_workflows)
        errors = blocking_issues(issues)
        if errors:
            return CompileResult("error", spec=spec, errors=errors, guidance="请修正 spec 后重试。")
        return CompileResult("spec", spec=spec, errors=issues)

    def compile(
        self,
        viewpoint: str,
        *,
        current_spec: WorkflowSpec | None = None,
    ) -> CompileResult:
        last_error = ""
        for attempt in range(2):
            try:
                payload = self._call(self._prompt(viewpoint, current_spec, last_error))
                result = self._interpret(payload, current_spec)
            except ValueError as exc:
                result = CompileResult("error", errors=[str(exc)], guidance="请让模型只返回合法 JSON。")
            if result.kind != "error":
                return result
            last_error = "; ".join(result.errors)
            if attempt == 1:
                result.guidance = result.guidance or "已重试一次；请缩小观点范围或手动编辑 spec。"
                return result
        return CompileResult("error", errors=["编译失败"], guidance="请稍后重试。")
