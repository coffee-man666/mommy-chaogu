"""Serializable specification for user-authored workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

SPEC_VERSION = 1
ArgSourceKind = Literal["literal", "user_regex", "step_field", "param"]


@dataclass(frozen=True)
class ArgSource:
    kind: ArgSourceKind
    value: Any = None
    pattern: str = ""
    step_index: int = 0
    field: str = "codes"
    param_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "pattern": self.pattern,
            "step_index": self.step_index,
            "field": self.field,
            "param_name": self.param_name,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ArgSource:
        if not isinstance(raw, dict) or raw.get("kind") not in {
            "literal",
            "user_regex",
            "step_field",
            "param",
        }:
            raise ValueError("ArgSource.kind 必须是 literal/user_regex/step_field/param")
        return cls(
            kind=raw["kind"],
            value=raw.get("value"),
            pattern=str(raw.get("pattern", "")),
            step_index=int(raw.get("step_index", 0)),
            field=str(raw.get("field", "codes")),
            param_name=str(raw.get("param_name", "")),
        )


@dataclass(frozen=True)
class StepSpec:
    tool_name: str
    display_name: str
    inputs: dict[str, ArgSource] = field(default_factory=dict)
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "display_name": self.display_name,
            "inputs": {name: source.to_dict() for name, source in self.inputs.items()},
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> StepSpec:
        if not isinstance(raw, dict) or not raw.get("tool_name"):
            raise ValueError("StepSpec.tool_name 不能为空")
        inputs = raw.get("inputs", {})
        if not isinstance(inputs, dict):
            raise ValueError("StepSpec.inputs 必须是对象")
        return cls(
            tool_name=str(raw["tool_name"]),
            display_name=str(raw.get("display_name", raw["tool_name"])),
            inputs={name: ArgSource.from_dict(source) for name, source in inputs.items()},
            optional=bool(raw.get("optional", False)),
        )


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    trigger_patterns: list[str]
    description: str
    steps: list[StepSpec]
    summary_template: str | None = None
    use_llm_summary: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    spec_version: int = SPEC_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trigger_patterns": list(self.trigger_patterns),
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "summary_template": self.summary_template,
            "use_llm_summary": self.use_llm_summary,
            "params": self.params,
            "spec_version": self.spec_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)

    @classmethod
    def from_dict(cls, raw: Any) -> WorkflowSpec:
        if not isinstance(raw, dict):
            raise ValueError("WorkflowSpec 必须是 JSON 对象")
        required = ("id", "trigger_patterns", "description", "steps")
        missing = [name for name in required if name not in raw]
        if missing:
            raise ValueError(f"WorkflowSpec 缺少字段: {', '.join(missing)}")
        patterns = raw["trigger_patterns"]
        steps = raw["steps"]
        params = raw.get("params", {})
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ValueError("trigger_patterns 必须是字符串数组")
        if not isinstance(steps, list):
            raise ValueError("steps 必须是数组")
        if not isinstance(params, dict):
            raise ValueError("params 必须是对象")
        return cls(
            id=str(raw["id"]),
            trigger_patterns=list(patterns),
            description=str(raw["description"]),
            steps=[StepSpec.from_dict(step) for step in steps],
            summary_template=(
                None if raw.get("summary_template") is None else str(raw["summary_template"])
            ),
            use_llm_summary=bool(raw.get("use_llm_summary", True)),
            params=dict(params),
            spec_version=int(raw.get("spec_version", SPEC_VERSION)),
        )

    @classmethod
    def from_json(cls, raw: str) -> WorkflowSpec:
        try:
            return cls.from_dict(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"WorkflowSpec JSON 无法解析: {exc}") from exc
