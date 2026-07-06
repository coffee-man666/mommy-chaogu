"""WorkflowEngine 核心测试。"""

from __future__ import annotations

import pytest

from mommy_chaogu.workflow.engine import (
    StepResult,
    Workflow,
    WorkflowExecutor,
    WorkflowRegistry,
    WorkflowResult,
    WorkflowStep,
)

# ============================================================
# Fake ToolRegistry — 不依赖真实 adapter
# ============================================================


class FakeToolRegistry:
    """模拟 ToolRegistry，返回预设结果。"""

    def __init__(self, results: dict[str, str] | None = None) -> None:
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        if name in self._results:
            return self._results[name]
        return '{"status": "ok"}'

    def definitions(self) -> list[dict]:
        return []

    @staticmethod
    def tool_names() -> list[str]:
        return []


class FailingToolRegistry(FakeToolRegistry):
    """工具调用总是失败。"""

    def call(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        raise RuntimeError(f"工具 {name} 模拟失败")


# ============================================================
# WorkflowStep / Workflow 数据结构
# ============================================================


class TestWorkflowStep:
    def test_defaults(self) -> None:
        step = WorkflowStep(tool_name="get_quote", display_name="获取报价")
        assert step.tool_name == "get_quote"
        assert step.args == {}
        assert step.args_extractor is None
        assert step.optional is False

    def test_with_args(self) -> None:
        step = WorkflowStep(
            tool_name="get_bars",
            display_name="K线",
            args={"interval": "1d", "count": 20},
        )
        assert step.args["interval"] == "1d"
        assert step.args["count"] == 20


# ============================================================
# WorkflowRegistry
# ============================================================


class TestWorkflowRegistry:
    def test_register_and_get(self) -> None:
        reg = WorkflowRegistry()
        wf = Workflow(
            id="test_wf",
            trigger_patterns=[r"测试"],
            description="测试工作流",
            steps=[],
        )
        reg.register(wf)
        assert reg.get("test_wf") is wf

    def test_duplicate_register_raises(self) -> None:
        reg = WorkflowRegistry()
        wf = Workflow(id="dup", trigger_patterns=["x"], description="", steps=[])
        reg.register(wf)
        with pytest.raises(ValueError, match="已注册"):
            reg.register(wf)

    def test_match_hit(self) -> None:
        reg = WorkflowRegistry()
        wf = Workflow(
            id="market",
            trigger_patterns=[r"大盘.*怎么样"],
            description="",
            steps=[],
        )
        reg.register(wf)
        assert reg.match("大盘怎么样") is wf
        assert reg.match("今天大盘怎么样啊") is wf

    def test_match_miss(self) -> None:
        reg = WorkflowRegistry()
        wf = Workflow(
            id="market",
            trigger_patterns=[r"大盘.*怎么样"],
            description="",
            steps=[],
        )
        reg.register(wf)
        assert reg.match("量子计算是什么") is None

    def test_match_multiple_workflows_first_hit_wins(self) -> None:
        reg = WorkflowRegistry()
        wf1 = Workflow(id="a", trigger_patterns=[r"今天"], description="", steps=[])
        wf2 = Workflow(id="b", trigger_patterns=[r"今天.*大盘"], description="", steps=[])
        reg.register(wf1)
        reg.register(wf2)
        # 两个都匹配，第一个注册的优先
        result = reg.match("今天大盘怎么样")
        assert result.id == "a"

    def test_match_case_insensitive(self) -> None:
        reg = WorkflowRegistry()
        wf = Workflow(
            id="en",
            trigger_patterns=[r"how.*market"],
            description="",
            steps=[],
        )
        reg.register(wf)
        assert reg.match("How is the MARKET today") is wf

    def test_all_workflows(self) -> None:
        reg = WorkflowRegistry()
        wf1 = Workflow(id="a", trigger_patterns=["x"], description="", steps=[])
        wf2 = Workflow(id="b", trigger_patterns=["y"], description="", steps=[])
        reg.register(wf1)
        reg.register(wf2)
        assert len(reg.all_workflows()) == 2


# ============================================================
# WorkflowExecutor
# ============================================================


class TestWorkflowExecutor:
    def test_simple_execution(self) -> None:
        tools = FakeToolRegistry({"get_market_indexes": '{"上证": 3200}'})
        executor = WorkflowExecutor(tools)

        wf = Workflow(
            id="test",
            trigger_patterns=["test"],
            description="",
            steps=[
                WorkflowStep(tool_name="get_market_indexes", display_name="取指数"),
            ],
        )
        result = executor.execute(wf, "test")
        assert result.workflow_id == "test"
        assert len(result.steps) == 1
        assert result.steps[0].success is True
        assert result.steps[0].data == {"上证": 3200}
        assert result.succeeded is True

    def test_multi_step_execution(self) -> None:
        tools = FakeToolRegistry(
            {
                "get_market_indexes": '{"上证": 3200}',
                "get_sector_ranking": "[{'板块': '半导体'}]",
            }
        )
        executor = WorkflowExecutor(tools)

        wf = Workflow(
            id="multi",
            trigger_patterns=["test"],
            description="",
            steps=[
                WorkflowStep(tool_name="get_market_indexes", display_name="取指数"),
                WorkflowStep(tool_name="get_sector_ranking", display_name="取板块"),
            ],
        )
        result = executor.execute(wf, "test")
        assert len(result.steps) == 2
        assert result.steps[0].tool_name == "get_market_indexes"
        assert result.steps[1].tool_name == "get_sector_ranking"

    def test_non_optional_failure_stops(self) -> None:
        tools = FailingToolRegistry()
        executor = WorkflowExecutor(tools)

        wf = Workflow(
            id="fail",
            trigger_patterns=["test"],
            description="",
            steps=[
                WorkflowStep(tool_name="tool_a", display_name="步骤A"),
                WorkflowStep(tool_name="tool_b", display_name="步骤B"),
            ],
        )
        result = executor.execute(wf, "test")
        assert len(result.steps) == 1  # 第一步失败就停了
        assert result.steps[0].success is False
        assert result.steps[0].error is not None

    def test_optional_failure_continues(self) -> None:
        tools = FailingToolRegistry()
        executor = WorkflowExecutor(tools)

        wf = Workflow(
            id="opt",
            trigger_patterns=["test"],
            description="",
            steps=[
                WorkflowStep(tool_name="tool_a", display_name="步骤A", optional=True),
                WorkflowStep(tool_name="tool_b", display_name="步骤B"),
            ],
        )
        result = executor.execute(wf, "test")
        # 两个都失败了（FailingToolRegistry 总是失败），但 optional 步骤 A 被记录
        # 非可选步骤 B 也失败 → 停止
        assert len(result.steps) == 2
        assert result.steps[0].success is False  # optional 失败但继续了
        assert result.steps[1].success is False  # non-optional 失败 → 停止

    def test_args_extractor(self) -> None:
        tools = FakeToolRegistry()
        executor = WorkflowExecutor(tools)

        def extract_code(text: str, _: list) -> dict:
            import re

            m = re.search(r"\d{6}", text)
            return {"code": m.group(0)} if m else {}

        wf = Workflow(
            id="extract",
            trigger_patterns=["test"],
            description="",
            steps=[
                WorkflowStep(
                    tool_name="get_quote",
                    display_name="取报价",
                    args_extractor=extract_code,
                ),
            ],
        )
        executor.execute(wf, "分析 600519")
        assert tools.calls[0][1]["code"] == "600519"

    def test_progress_callbacks(self) -> None:
        tools = FakeToolRegistry({"get_market_indexes": "{}"})
        executor = WorkflowExecutor(tools)

        starts: list[str] = []
        dones: list[tuple[str, bool]] = []

        wf = Workflow(
            id="cb",
            trigger_patterns=["test"],
            description="",
            steps=[
                WorkflowStep(tool_name="get_market_indexes", display_name="步骤1"),
            ],
        )
        executor.execute(
            wf,
            "test",
            on_step_start=lambda name: starts.append(name),
            on_step_done=lambda name, ok: dones.append((name, ok)),
        )
        assert starts == ["步骤1"]
        assert dones == [("步骤1", True)]

    def test_llm_summary(self) -> None:
        tools = FakeToolRegistry({"get_market_indexes": '{"上证": 3200}'})

        class FakeLLM:
            def summarize(self, template: str, context: str) -> str:
                return "LLM 总结结果"

        executor = WorkflowExecutor(tools, llm_summarizer=FakeLLM())  # type: ignore[arg-type]
        wf = Workflow(
            id="summary",
            trigger_patterns=["test"],
            description="",
            steps=[WorkflowStep(tool_name="get_market_indexes", display_name="取指数")],
            summary_template="模板 {context}",
        )
        result = executor.execute(wf, "test")
        assert result.summary == "LLM 总结结果"

    def test_llm_summary_failure_fallback(self) -> None:
        tools = FakeToolRegistry({"get_market_indexes": '{"上证": 3200}'})

        class FailingLLM:
            def summarize(self, template: str, context: str) -> str:
                raise RuntimeError("LLM 不可用")

        executor = WorkflowExecutor(tools, llm_summarizer=FailingLLM())  # type: ignore[arg-type]
        wf = Workflow(
            id="fallback",
            trigger_patterns=["test"],
            description="",
            steps=[WorkflowStep(tool_name="get_market_indexes", display_name="取指数")],
            summary_template="模板 {context}",
        )
        result = executor.execute(wf, "test")
        # LLM 失败应该 fallback 到简单格式化
        assert "取指数" in result.summary

    def test_no_llm_summary_when_none(self) -> None:
        tools = FakeToolRegistry({"get_market_indexes": '{"上证": 3200}'})
        executor = WorkflowExecutor(tools, llm_summarizer=None)
        wf = Workflow(
            id="no_llm",
            trigger_patterns=["test"],
            description="",
            steps=[WorkflowStep(tool_name="get_market_indexes", display_name="取指数")],
            summary_template="模板 {context}",
        )
        result = executor.execute(wf, "test")
        assert result.summary == ""  # 没有 LLM，不做总结


# ============================================================
# WorkflowResult
# ============================================================


class TestWorkflowResult:
    def test_succeeded_with_results(self) -> None:
        result = WorkflowResult(
            workflow_id="test",
            steps=[StepResult("a", "tool_a", True, {"data": 1})],
        )
        assert result.succeeded is True

    def test_failed(self) -> None:
        result = WorkflowResult(
            workflow_id="test",
            steps=[StepResult("a", "tool_a", False, error="失败")],
        )
        assert result.succeeded is False

    def test_empty(self) -> None:
        result = WorkflowResult(workflow_id="empty")
        assert result.succeeded is False
        assert result.steps == []
