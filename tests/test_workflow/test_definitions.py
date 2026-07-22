"""预定义工作流测试。"""

from __future__ import annotations

import pytest

from mommy_chaogu.workflow.definitions import (
    WORKFLOWS,
    _extract_codes_from_portfolio,
    _extract_codes_from_watchlist,
    _extract_sector_code_from_prev,
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


class TestExtractSectorCodeFromPrev:
    def test_extracts_from_list_result(self) -> None:
        previous = [{"tool": "search_sector", "result": [{"board_code": "BK1106"}]}]
        result = _extract_sector_code_from_prev("", previous)
        assert result == {"board_code": "BK1106"}

    def test_extracts_from_dict_result(self) -> None:
        previous = [{"tool": "search_sector", "result": {"board_code": "BK0475"}}]
        result = _extract_sector_code_from_prev("", previous)
        assert result == {"board_code": "BK0475"}

    def test_returns_empty_when_no_search_sector(self) -> None:
        previous = [{"tool": "get_quote", "result": {"code": "600519"}}]
        assert _extract_sector_code_from_prev("", previous) == {}

    def test_returns_empty_when_empty_list_result(self) -> None:
        previous = [{"tool": "search_sector", "result": []}]
        assert _extract_sector_code_from_prev("", previous) == {}

    def test_returns_empty_when_no_previous(self) -> None:
        assert _extract_sector_code_from_prev("", []) == {}


class TestExtractCodesFromWatchlist:
    def test_extracts_flat_list(self) -> None:
        previous = [
            {
                "tool": "get_watchlist",
                "result": [
                    {"code": "600519"},
                    {"code": "000858"},
                ],
            }
        ]
        result = _extract_codes_from_watchlist("", previous)
        assert result == {"codes": ["600519", "000858"]}

    def test_extracts_grouped_format(self) -> None:
        previous = [
            {
                "tool": "get_watchlist",
                "result": {
                    "groups": [
                        {"stocks": [{"code": "600519"}, {"code": "000001"}]},
                        {"stocks": [{"code": "000858"}]},
                    ]
                },
            }
        ]
        result = _extract_codes_from_watchlist("", previous)
        assert result == {"codes": ["600519", "000001", "000858"]}

    def test_caps_at_50(self) -> None:
        stocks = [{"code": f"60000{i}"} for i in range(60)]
        previous = [{"tool": "get_watchlist", "result": stocks}]
        result = _extract_codes_from_watchlist("", previous)
        assert len(result["codes"]) == 50

    def test_returns_empty_when_no_watchlist(self) -> None:
        assert _extract_codes_from_watchlist("", []) == {}

    def test_returns_empty_when_no_codes(self) -> None:
        previous = [{"tool": "get_watchlist", "result": []}]
        assert _extract_codes_from_watchlist("", previous) == {}


class TestExtractCodesFromPortfolio:
    def test_extracts_from_positions(self) -> None:
        previous = [
            {
                "tool": "get_portfolio",
                "result": {
                    "positions": [
                        {"code": "600519"},
                        {"code": "000858"},
                    ]
                },
            }
        ]
        result = _extract_codes_from_portfolio("", previous)
        assert result == {"codes": ["600519", "000858"]}

    def test_caps_at_50(self) -> None:
        positions = [{"code": f"60000{i}"} for i in range(60)]
        previous = [{"tool": "get_portfolio", "result": {"positions": positions}}]
        result = _extract_codes_from_portfolio("", previous)
        assert len(result["codes"]) == 50

    def test_returns_empty_when_no_portfolio(self) -> None:
        assert _extract_codes_from_portfolio("", []) == {}

    def test_returns_empty_when_no_positions_key(self) -> None:
        previous = [{"tool": "get_portfolio", "result": {}}]
        assert _extract_codes_from_portfolio("", previous) == {}


class _FakeTools:
    """最小 ToolRegistry 替身：返回预设 JSON，记录调用参数。"""

    def __init__(self, results: dict[str, str]) -> None:
        self._results = results
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return self._results.get(name, "{}")

    def definitions(self) -> list[dict]:
        return []

    @staticmethod
    def tool_names() -> list[str]:
        return []


class TestStockAnalysisDefinition:
    def test_get_bars_uses_limit_not_count(self) -> None:
        """stock_analysis 传给 get_bars 的参数是 limit（工具不认 count）。"""
        wf = get_default_registry().get("stock_analysis")
        assert wf is not None
        bars_step = next(s for s in wf.steps if s.tool_name == "get_bars")
        assert bars_step.args.get("limit") == 20
        assert "count" not in bars_step.args


class TestFlowCheckDefinition:
    def test_flow_step_succeeds_with_watchlist_codes(self) -> None:
        """flow_check 的资金流步骤用自选股 codes 批量查询并成功。

        修复前 get_money_flow_today 只认单数 code，_extract_codes_from_watchlist
        返回的 {"codes": [...]} 让该步每次必败（且被记为成功）。
        """
        from mommy_chaogu.workflow.engine import WorkflowExecutor

        tools = _FakeTools(
            {
                "get_watchlist": '[{"code": "600519"}, {"code": "000858"}]',
                "get_money_flow_today": '{"results": {"600519": {}}, "count": 1}',
                "get_sector_ranking": "[]",
            }
        )
        executor = WorkflowExecutor(tools)  # type: ignore[arg-type]
        wf = get_default_registry().get("flow_check")
        assert wf is not None

        result = executor.execute(wf, "主力资金怎么样")

        flow_calls = [args for name, args in tools.calls if name == "get_money_flow_today"]
        assert flow_calls == [{"codes": ["600519", "000858"]}]
        flow_step = next(s for s in result.steps if s.tool_name == "get_money_flow_today")
        assert flow_step.success is True


class TestAddWatchlistDefinition:
    def test_uses_manage_watchlist_tool(self) -> None:
        """add_watchlist 工作流调 manage_watchlist（修复前误用告警工具 manage_alert）。"""
        wf = get_default_registry().get("add_watchlist")
        assert wf is not None
        assert wf.steps[0].tool_name == "manage_watchlist"
        assert wf.steps[0].args == {"action": "add"}

    def test_end_to_end_adds_entry(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """端到端：'加自选 600519' 真正把股票写进 portfolio.db 自选股。"""
        from unittest.mock import MagicMock

        from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
        from mommy_chaogu.watchlist.store import WatchlistStore
        from mommy_chaogu.workflow.engine import WorkflowExecutor

        store = WatchlistStore(tmp_path / "portfolio.db")
        ctx = ToolContext(adapter=MagicMock(), watchlist_store=store)
        executor = WorkflowExecutor(ToolRegistry(ctx))

        wf = get_default_registry().get("add_watchlist")
        assert wf is not None
        result = executor.execute(wf, "加自选 600519")

        assert result.steps[0].success is True
        entries = store.list_entries()
        assert [e.code for e in entries] == ["600519"]

    def test_without_code_step_fails_but_workflow_continues(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """抠不到 6 位代码时步骤失败但 optional 不中断（由 LLM 总结引导用户）。"""
        from unittest.mock import MagicMock

        from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
        from mommy_chaogu.watchlist.store import WatchlistStore
        from mommy_chaogu.workflow.engine import WorkflowExecutor

        store = WatchlistStore(tmp_path / "portfolio.db")
        ctx = ToolContext(adapter=MagicMock(), watchlist_store=store)
        executor = WorkflowExecutor(ToolRegistry(ctx))

        wf = get_default_registry().get("add_watchlist")
        assert wf is not None
        result = executor.execute(wf, "加个自选")

        assert result.steps[0].success is False
        assert result.steps[0].error is not None
        assert store.list_entries() == []
