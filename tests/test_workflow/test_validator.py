from __future__ import annotations

from mommy_chaogu.workflow.definitions import get_default_registry
from mommy_chaogu.workflow.spec import ArgSource, StepSpec, WorkflowSpec
from mommy_chaogu.workflow.validator import blocking_issues, validate_spec


def _valid(**kwargs: object) -> WorkflowSpec:
    values = {
        "id": "user_test",
        "trigger_patterns": ["独特测试触发词"],
        "description": "test",
        "steps": [StepSpec("screen_inflow_stocks", "筛选")],
    }
    values.update(kwargs)
    return WorkflowSpec(**values)  # type: ignore[arg-type]


def test_validator_requires_user_prefix_and_known_tool() -> None:
    spec = _valid(id="custom", steps=[StepSpec("missing_tool", "bad")])
    issues = validate_spec(spec)
    assert any("user_" in issue for issue in issues)
    assert any("工具不存在" in issue for issue in issues)


def test_validator_checks_prior_step_and_regex() -> None:
    spec = _valid(
        steps=[
            StepSpec(
                "screen_inflow_stocks", "bad", {"codes": ArgSource("step_field", step_index=0)}
            ),
            StepSpec(
                "check_kline_signal", "bad regex", {"codes": ArgSource("user_regex", pattern="[")}
            ),
        ]
    )
    issues = validate_spec(spec)
    assert any("非前置步骤" in issue for issue in issues)
    assert any("user_regex 非法" in issue for issue in issues)

    missing_pattern = _valid(
        steps=[StepSpec("check_kline_signal", "missing", {"codes": ArgSource("user_regex")})]
    )
    assert any("user_regex 缺少 pattern" in issue for issue in validate_spec(missing_pattern))

    wrong_field = _valid(
        steps=[
            StepSpec(
                "check_kline_signal",
                "wrong field",
                {"codes": ArgSource("step_field", step_index=0, field="results")},
            )
        ]
    )
    assert any("codes 只能引用" in issue for issue in validate_spec(wrong_field))


def test_validator_detects_builtin_trigger_conflict_and_warns_unknown_arg() -> None:
    builtins = get_default_registry().all_workflows()
    existing_pattern = builtins[0].trigger_patterns[0]
    spec = _valid(
        trigger_patterns=[existing_pattern],
        steps=[StepSpec("screen_inflow_stocks", "bad", {"not_a_param": ArgSource("literal", 1)})],
    )
    issues = validate_spec(spec, existing_workflows=builtins)
    assert blocking_issues(issues)
    assert any("冲突" in issue for issue in issues)
    assert any(issue.startswith("warning:") for issue in issues)


def test_validator_blocks_write_tools_in_custom_specs() -> None:
    """自定义工作流按 trigger 自动执行、无逐次确认通道——写工具必须 blocking。

    判定集与 agent/service.py 的确认白名单同源（strategy_* 三件套 +
    manage_watchlist / manage_alert）；backfill_history 写的是行情缓存而非
    用户数据，不属于此集。
    """
    for write_tool in ("manage_watchlist", "manage_alert", "strategy_save"):
        spec = _valid(steps=[StepSpec(write_tool, "写")])
        issues = validate_spec(spec)
        assert any("写工具" in issue and write_tool in issue for issue in issues), write_tool
        assert blocking_issues(issues)

    cache_write = _valid(steps=[StepSpec("backfill_history", "回填")])
    assert not any("写工具" in issue for issue in validate_spec(cache_write))
