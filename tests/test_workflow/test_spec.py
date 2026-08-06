from __future__ import annotations

import json

import pytest

from mommy_chaogu.workflow.spec import ArgSource, StepSpec, WorkflowSpec
from mommy_chaogu.workflow.spec_runtime import spec_to_workflow


def _spec() -> WorkflowSpec:
    return WorkflowSpec(
        id="user_flow",
        trigger_patterns=["资金流"],
        description="筛选资金流",
        steps=[
            StepSpec("get_watchlist", "读取自选股"),
            StepSpec(
                "screen_inflow_stocks",
                "筛选",
                inputs={
                    "codes": ArgSource("step_field", step_index=0),
                    "threshold_bp": ArgSource("param", param_name="threshold_bp"),
                },
            ),
        ],
        params={"threshold_bp": 50},
    )


def test_spec_json_round_trip() -> None:
    spec = _spec()
    assert WorkflowSpec.from_json(spec.to_json()) == spec
    assert json.loads(spec.to_json())["spec_version"] == 1


def test_default_summary_template_uses_description() -> None:
    workflow = spec_to_workflow(_spec())
    assert workflow.summary_template is not None
    assert "筛选资金流" in workflow.summary_template
    assert "{context}" in workflow.summary_template


def test_default_summary_template_escapes_format_braces_in_description() -> None:
    spec = WorkflowSpec(
        id="user_braces",
        trigger_patterns=["braces"],
        description="阈值 {threshold}",
        steps=[StepSpec("screen_inflow_stocks", "筛选")],
    )
    workflow = spec_to_workflow(spec)
    assert workflow.summary_template is not None
    assert workflow.summary_template.format(context="{}")


def test_all_arg_source_kinds_resolve() -> None:
    spec = WorkflowSpec(
        id="user_sources",
        trigger_patterns=["source"],
        description="sources",
        steps=[
            StepSpec(
                "screen_inflow_stocks",
                "run",
                inputs={
                    "codes": ArgSource("user_regex", pattern=r"代码(\d{6})"),
                    "threshold_bp": ArgSource("param", param_name="threshold_bp"),
                },
            )
        ],
        params={"threshold_bp": 50},
    )
    extractor = spec_to_workflow(spec, {"threshold_bp": 100}).steps[0].args_extractor
    assert extractor is not None
    assert extractor("代码600519", [])["codes"] == "600519"
    assert extractor("代码600519", [])["threshold_bp"] == 100

    literal_spec = WorkflowSpec(
        id="user_literal",
        trigger_patterns=["literal"],
        description="literal",
        steps=[
            StepSpec("screen_inflow_stocks", "run", {"codes": ArgSource("literal", ["600519"])})
        ],
    )
    literal_extractor = spec_to_workflow(literal_spec).steps[0].args_extractor
    assert literal_extractor is not None
    assert literal_extractor("", [])["codes"] == ["600519"]


def test_known_nested_extractors_and_unknown_shape_error() -> None:
    spec = _spec()
    extractor = spec_to_workflow(spec).steps[1].args_extractor
    assert extractor is not None
    previous = [{"tool": "get_watchlist", "result": {"groups": [{"stocks": [{"code": "600519"}]}]}}]
    assert extractor("", previous)["codes"] == ["600519"]
    with pytest.raises(ValueError, match="无法识别 get_watchlist"):
        extractor("", [{"tool": "get_watchlist", "result": {"unexpected": []}}])


def test_default_results_extractor_requires_contract() -> None:
    spec = WorkflowSpec(
        id="user_contract",
        trigger_patterns=["contract"],
        description="contract",
        steps=[
            StepSpec("screen_inflow_stocks", "first"),
            StepSpec(
                "check_kline_signal",
                "second",
                {"codes": ArgSource("step_field", step_index=0)},
            ),
        ],
    )
    extractor = spec_to_workflow(spec).steps[1].args_extractor
    assert extractor is not None
    with pytest.raises(ValueError, match="results"):
        extractor("", [{"tool": "screen_inflow_stocks", "result": []}])
