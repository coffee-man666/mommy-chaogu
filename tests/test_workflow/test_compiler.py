from __future__ import annotations

import json

from mommy_chaogu.workflow.compiler import WorkflowCompiler


def _payload() -> str:
    return json.dumps(
        {
            "kind": "spec",
            "id": "user_compiled",
            "trigger_patterns": ["编译测试"],
            "description": "compiled",
            "steps": [{"tool_name": "screen_inflow_stocks", "display_name": "筛选"}],
            "params": {},
            "spec_version": 1,
        }
    )


def test_compiler_returns_spec_and_questions() -> None:
    result = WorkflowCompiler(lambda _: _payload()).compile("编译测试")
    assert result.kind == "spec"
    assert result.spec is not None
    assert result.spec.id == "user_compiled"

    questions = WorkflowCompiler(
        lambda _: '{"kind":"questions","questions":["看自选股还是持仓？"]}'
    ).compile("帮我看看")
    assert questions.kind == "questions"
    assert questions.questions


def test_compiler_prompt_contains_tool_directory_and_golden_examples() -> None:
    prompts: list[str] = []

    def chat(messages: list[dict[str, str]]) -> str:
        prompts.append(messages[-1]["content"])
        return _payload()

    WorkflowCompiler(chat).compile("编译测试")
    assert '"name": "screen_inflow_stocks"' in prompts[0]
    assert "自选股资金筛选" in prompts[0]
    assert "指定代码 K 线" in prompts[0]


def test_compiler_retries_invalid_response_once() -> None:
    responses = iter(["not json", _payload()])
    result = WorkflowCompiler(lambda _: next(responses)).compile("重试")
    assert result.kind == "spec"


def test_compiler_returns_guidance_after_second_failure() -> None:
    result = WorkflowCompiler(lambda _: "not json").compile("失败")
    assert result.kind == "error"
    assert result.errors
    assert result.guidance


def test_update_preserves_existing_id_and_injects_old_spec() -> None:
    prompts: list[str] = []
    old = json.loads(_payload())
    old["id"] = "user_existing"

    def chat(messages: list[dict[str, str]]) -> str:
        prompts.append(messages[-1]["content"])
        return _payload()

    from mommy_chaogu.workflow.spec import WorkflowSpec

    current = WorkflowSpec.from_dict(old)
    result = WorkflowCompiler(chat).compile("更新描述", current_spec=current)
    assert result.spec is not None
    assert result.spec.id == "user_existing"
    assert "当前 spec" in prompts[0]
