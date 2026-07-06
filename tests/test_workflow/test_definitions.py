"""预定义工作流测试。"""

from __future__ import annotations

import pytest

from mommy_chaogu.workflow.definitions import (
    WORKFLOWS,
    _extract_sector_keyword,
    _extract_stock_code,
    get_default_registry,
)


class TestWorkflowDefinitions:
    def test_all_workflows_have_unique_ids(self) -> None:
        ids = [wf.id for wf in WORKFLOWS]
        assert len(ids) == len(set(ids)), f"重复的 workflow id: {ids}"

    def test_all_workflows_have_patterns(self) -> None:
        for wf in WORKFLOWS:
            assert len(wf.trigger_patterns) > 0, f"{wf.id} 没有 trigger pattern"

    def test_all_workflows_have_steps(self) -> None:
        for wf in WORKFLOWS:
            assert len(wf.steps) > 0, f"{wf.id} 没有 steps"

    def test_all_workflows_have_description(self) -> None:
        for wf in WORKFLOWS:
            assert wf.description, f"{wf.id} 没有 description"

    def test_workflow_count(self) -> None:
        assert len(WORKFLOWS) == 9

    @pytest.mark.parametrize(
        "workflow_id",
        [
            "morning_brief",
            "market_check",
            "add_watchlist",
            "stock_analysis",
            "sector_scan",
            "flow_check",
            "portfolio_review",
            "earnings_check",
            "close_report",
        ],
    )
    def test_workflow_exists(self, workflow_id: str) -> None:
        ids = [wf.id for wf in WORKFLOWS]
        assert workflow_id in ids


class TestDefaultRegistry:
    def test_registry_has_all_workflows(self) -> None:
        registry = get_default_registry()
        assert len(registry.all_workflows()) == 9

    def test_registry_match_morning_brief(self) -> None:
        registry = get_default_registry()
        wf = registry.match("今天怎么样")
        assert wf is not None
        assert wf.id == "morning_brief"

    def test_registry_match_stock_analysis(self) -> None:
        registry = get_default_registry()
        wf = registry.match("分析一下 600519")
        assert wf is not None
        assert wf.id == "stock_analysis"

    def test_registry_match_sector_scan(self) -> None:
        registry = get_default_registry()
        wf = registry.match("半导体板块怎么样")
        assert wf is not None
        assert wf.id == "sector_scan"

    def test_registry_match_portfolio_review(self) -> None:
        registry = get_default_registry()
        wf = registry.match("我的持仓怎么样")
        assert wf is not None
        assert wf.id == "portfolio_review"

    def test_registry_match_flow_check(self) -> None:
        registry = get_default_registry()
        wf = registry.match("主力在买什么")
        assert wf is not None
        assert wf.id == "flow_check"

    def test_registry_match_close_report(self) -> None:
        registry = get_default_registry()
        wf = registry.match("今日总结")
        assert wf is not None
        assert wf.id == "close_report"

    def test_registry_match_earnings(self) -> None:
        registry = get_default_registry()
        wf = registry.match("中报怎么样")
        assert wf is not None
        assert wf.id == "earnings_check"

    def test_registry_match_add_watchlist(self) -> None:
        registry = get_default_registry()
        wf = registry.match("加个自选股")
        assert wf is not None
        assert wf.id == "add_watchlist"

    def test_registry_match_market_check(self) -> None:
        registry = get_default_registry()
        wf = registry.match("大盘怎么样")
        assert wf is not None
        assert wf.id == "market_check"

    def test_registry_no_match_for_unrelated(self) -> None:
        registry = get_default_registry()
        assert registry.match("量子计算是什么") is None
        assert registry.match("帮我写首诗") is None


class TestExtractors:
    def test_extract_stock_code_hit(self) -> None:
        result = _extract_stock_code("分析 600519", [])
        assert result == {"code": "600519"}

    def test_extract_stock_code_miss(self) -> None:
        result = _extract_stock_code("分析贵州茅台", [])
        assert result == {}

    def test_extract_sector_keyword(self) -> None:
        result = _extract_sector_keyword("半导体板块怎么样", [])
        assert result == {"keyword": "半导体"}

    def test_extract_sector_keyword_multiple_words(self) -> None:
        result = _extract_sector_keyword("创新药板块分析", [])
        assert result["keyword"] == "创新药"
