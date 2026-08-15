"""build_nl_runtime 统一装配工厂的跨入口一致性测试（F4）。

三入口（CLI / TUI / Web）此前各自内联装配且行为不一致：自定义工作流
只在 CLI merge。工厂收敛后这里断言所有入口共享的语义：

- builtin registry + WorkflowStore 自定义工作流 merge；
- 坏 spec（blocking issue / 转换失败）逐条跳过，不影响内置与其余 spec；
- 注入 agent 时共享 summarizer 接上；无 agent 时 executor 仍可用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.workflow.assembly import AgentSummarizer, build_nl_runtime
from mommy_chaogu.workflow.spec import StepSpec, WorkflowSpec
from mommy_chaogu.workflow.store import WorkflowStore


def _good_spec(
    spec_id: str = "user_assembly",
    trigger: str = "白酒动量打分列一下",
) -> WorkflowSpec:
    return WorkflowSpec(
        id=spec_id,
        trigger_patterns=[trigger],
        description=f"{spec_id} 自定义工作流",
        steps=[StepSpec("get_market_indexes", "取大盘指数")],
        summary_template=None,
    )


def _store_with(tmp_path: Path, *specs: WorkflowSpec) -> WorkflowStore:
    store = WorkflowStore(tmp_path / "agent.db")
    for spec in specs:
        store.save(spec, "test source")
    return store


@pytest.fixture
def isolated_dbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """三库指向 tmp，避免读到仓库 data/ 里的真实数据。"""
    monkeypatch.setattr("mommy_chaogu.db_paths.AGENT_DB", tmp_path / "agent.db")
    monkeypatch.setattr("mommy_chaogu.db_paths.MARKET_DB", tmp_path / "market.db")
    monkeypatch.setattr("mommy_chaogu.db_paths.PORTFOLIO_DB", tmp_path / "portfolio.db")
    return tmp_path


class TestBuildNLRuntime:
    def test_merges_custom_workflows_from_agent_db(self, isolated_dbs: Path) -> None:
        """WorkflowStore（AGENT_DB）里的自定义工作流 merge 进 router registry。"""
        spec = _good_spec(trigger="白酒动量打分列一下")  # 与内置 pattern 无冲突
        store = _store_with(isolated_dbs, spec)
        store.close()

        runtime = build_nl_runtime(agent_db=isolated_dbs / "agent.db", build_agent=False)

        assert runtime.workflow_store is not None
        merged = runtime.router.registry.get("user_assembly")
        assert merged is not None, "自定义工作流应 merge 进 registry"
        assert merged.trigger_patterns == [spec.trigger_patterns[0]]
        # builtin 不受影响
        assert runtime.router.registry.get("morning_brief") is not None
        # 路由能直接命中自定义工作流（未命中会 fallback）
        route = runtime.router.route("白酒动量打分列一下")
        assert route.matched and route.workflow is not None
        assert route.workflow.id == "user_assembly"
        runtime.workflow_store.close()

    def test_bad_spec_skipped_builtins_intact(self, isolated_dbs: Path) -> None:
        """坏 spec（blocking issue：id 与内置冲突）逐条跳过，不影响内置。"""
        conflicting = _good_spec(
            spec_id="user_morning_brief", trigger="今天大盘怎么样"
        )  # trigger 与内置 morning_brief/market_overview 冲突
        unknown_tool = WorkflowSpec(
            id="user_ghost_tool",
            trigger_patterns=["龙头股梯队排一排"],
            description="引用不存在的工具",
            steps=[StepSpec("no_such_tool", "必然失败")],
        )
        good = _good_spec(spec_id="user_still_works", trigger="稀土板块跟踪提醒")
        store = _store_with(isolated_dbs, conflicting, unknown_tool, good)
        store.close()

        runtime = build_nl_runtime(agent_db=isolated_dbs / "agent.db", build_agent=False)

        registry = runtime.router.registry
        assert registry.get("user_ghost_tool") is None, "未知工具 spec 应被跳过"
        assert registry.get("user_morning_brief") is None, "冲突 spec 应被跳过"
        assert registry.get("user_still_works") is not None, "好 spec 不受坏 spec 影响"
        assert registry.get("morning_brief") is not None
        runtime.workflow_store.close()

    def test_injected_store_is_returned_unclosed(self, isolated_dbs: Path) -> None:
        """注入的 workflow_store 原样返回（CLI 用来 increment_hit / close）。"""
        store = _store_with(isolated_dbs, _good_spec())
        try:
            runtime = build_nl_runtime(workflow_store=store, build_agent=False)
            assert runtime.workflow_store is store
            assert runtime.router.registry.get("user_assembly") is not None
        finally:
            store.close()

    def test_no_key_agent_none_executor_usable(self, isolated_dbs: Path) -> None:
        """无 key 时 agent=None（入口据此降级），工作流路由/执行仍可用。"""
        runtime = build_nl_runtime(agent_db=isolated_dbs / "agent.db", build_agent=True)
        assert runtime.agent_service is None
        route = runtime.router.route("今天怎么样")
        assert route.matched, "无 key 时内置工作流仍应可路由"


class TestAgentSummarizerShared:
    def test_wraps_injected_agent_via_chat_raw(self, isolated_dbs: Path) -> None:
        """注入的 agent_service 被共享 AgentSummarizer 包装进 executor。"""

        class _RecordingAgent:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def chat_raw(self, messages: list[dict[str, Any]]) -> Any:
                self.calls.append(messages[0])
                from types import SimpleNamespace

                return SimpleNamespace(text=" summarized! ")

        agent = _RecordingAgent()
        runtime = build_nl_runtime(
            agent_db=isolated_dbs / "agent.db",
            agent_service=agent,  # type: ignore[arg-type]
        )

        from mommy_chaogu.workflow.engine import WorkflowExecutor

        assert isinstance(runtime.executor, WorkflowExecutor)
        assert isinstance(runtime.executor._llm, AgentSummarizer)
        summary = runtime.executor._llm.summarize("总结：{context}", "[1,2]")
        assert summary == " summarized! "
        assert agent.calls == [{"role": "user", "content": "总结：[1,2]"}]
        runtime.workflow_store.close()
