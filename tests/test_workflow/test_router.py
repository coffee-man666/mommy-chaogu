"""NLRouter 测试。"""

from __future__ import annotations

import pytest

from mommy_chaogu.workflow.definitions import get_default_registry
from mommy_chaogu.workflow.engine import (
    WorkflowExecutor,
    WorkflowRegistry,
)
from mommy_chaogu.workflow.router import NLRouter


class FakeToolRegistry:
    def call(self, name: str, args: dict) -> str:
        return '{"status": "ok"}'

    def definitions(self) -> list[dict]:
        return []

    @staticmethod
    def tool_names() -> list[str]:
        return []


class TestNLRouter:
    def test_route_hit(self) -> None:
        router = NLRouter(get_default_registry())
        result = router.route("今天怎么样")
        assert result.matched is True
        assert result.workflow is not None
        assert result.workflow.id == "morning_brief"

    def test_route_miss_fallback(self) -> None:
        router = NLRouter(get_default_registry())
        result = router.route("1+1等于几")
        assert result.matched is False
        assert result.workflow is None
        assert result.fallback_reason

    def test_route_various_inputs(self) -> None:
        router = NLRouter(get_default_registry())

        test_cases = [
            ("今天怎么样", True),
            ("大盘怎么样", True),
            ("分析一下600519", True),
            ("半导体板块怎么样", True),
            ("主力在买什么", True),
            ("我的持仓怎么样", True),
            ("今日总结", True),
            ("中报怎么样", True),
            ("加个自选股", True),
            ("量子计算原理", False),
            ("", False),
        ]
        for user_input, expected_match in test_cases:
            result = router.route(user_input)
            assert result.matched == expected_match, (
                f"输入 '{user_input}' 期望 matched={expected_match}，实际 matched={result.matched}"
            )

    def test_execute_matched_route(self) -> None:
        tools = FakeToolRegistry()
        executor = WorkflowExecutor(tools)
        router = NLRouter(get_default_registry(), executor)

        route = router.route("大盘怎么样")
        assert route.matched

        result = router.execute_route(route, "大盘怎么样")
        assert result.fallback_to_agent is False
        assert len(result.steps) > 0

    def test_execute_unmatched_returns_fallback(self) -> None:
        executor = WorkflowExecutor(FakeToolRegistry())
        router = NLRouter(get_default_registry(), executor)

        route = router.route("1+1=?")
        assert not route.matched

        result = router.execute_route(route, "1+1=?")
        assert result.fallback_to_agent is True

    def test_execute_without_executor_raises(self) -> None:
        router = NLRouter(get_default_registry(), executor=None)
        route = router.route("今天怎么样")
        with pytest.raises(RuntimeError, match="没有设置 WorkflowExecutor"):
            router.execute_route(route, "今天怎么样")

    def test_suggest_prompts(self) -> None:
        router = NLRouter(get_default_registry())
        prompts = router.suggest_prompts()
        assert len(prompts) == 9
        # 每个提示应该是一句中文描述
        for p in prompts:
            assert isinstance(p, str)
            assert len(p) > 0

    def test_route_empty_registry(self) -> None:
        empty_registry = WorkflowRegistry()
        router = NLRouter(empty_registry)
        result = router.route("今天怎么样")
        assert result.matched is False
