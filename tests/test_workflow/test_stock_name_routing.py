"""工作流路由的中文股票名解析（补 PR #72 漏掉的工作流层）。

PR #72 让 ``get_quote`` 支持中文名、并用 system prompt 引导 LLM 先调
``search_stock``——但那是 LLM 驱动的路径。工作流是**确定性路由，不过 LLM**，
早先的 ``_extract_stock_code`` 找不到 6 位代码就返回 ``{}``，handler 拿不到
code 直接 KeyError，traceback 喷到终端。

后果是同一件事按措辞分裂：

    mommy "分析一下比亚迪"   -> 命中 .*分析一下 -> 工作流 -> 崩溃
    mommy "看看比亚迪"       -> 不过工作流     -> LLM 自主 search_stock -> 正常

本文件锁定工作流侧的行为：指令包装要剥掉、后续步骤复用已解析的代码、
真的解析不出来时返回结构化错误而不是抛异常。
"""

from __future__ import annotations

import json
from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext
from mommy_chaogu.agent.tools.registry import ToolRegistry
from mommy_chaogu.workflow.definitions import (
    _extract_stock_code,
    _extract_stock_code_from_prev,
    _extract_stock_name_or_code,
    _strip_command_wrapper,
)


def test_strip_command_wrapper_keeps_only_the_subject() -> None:
    assert _strip_command_wrapper("分析一下比亚迪") == "比亚迪"
    assert _strip_command_wrapper("帮我看看贵州茅台") == "贵州茅台"
    assert _strip_command_wrapper("研究一下宁德时代怎么样") == "宁德时代"
    assert _strip_command_wrapper("比亚迪") == "比亚迪"
    # 剥空时不能返回空串，否则下游又变成"缺参数"
    assert _strip_command_wrapper("分析一下") == ""


def test_strict_extractor_never_invents_a_code() -> None:
    """严格模式必须继续返回 {}。

    它被 manage_watchlist / get_fundamentals / get_announcements 共用，这些
    工具既不解析名称也不校验代码——一旦回退传原话，"加个自选"就会被当成代码
    写进自选池，比原来的步骤失败危险得多。
    """
    assert _extract_stock_code("分析一下比亚迪", []) == {}
    assert _extract_stock_code("加个自选", []) == {}
    assert _extract_stock_code("分析一下 600519", []) == {"code": "600519"}


def test_name_aware_extractor_falls_back_to_stripped_name() -> None:
    """回归：stock_analysis 首步早先走严格提取器，handler 拿不到 code 直接 KeyError。"""
    assert _extract_stock_name_or_code("分析一下比亚迪", []) == {"code": "比亚迪"}
    assert _extract_stock_name_or_code("分析一下 600519", []) == {"code": "600519"}
    assert _extract_stock_name_or_code("分析一下", []) == {}


def test_from_prev_reuses_resolved_code() -> None:
    """get_bars / 资金流只认代码，必须复用 get_quote 解析出的结果。"""
    previous: list[dict[str, Any]] = [
        {"tool": "get_quote", "result": {"code": "002594", "name": "比亚迪", "price": 83.31}}
    ]
    assert _extract_stock_code_from_prev("分析一下比亚迪", previous) == {"code": "002594"}


def test_from_prev_ignores_non_code_payloads() -> None:
    """get_quote 失败时 result 是 error dict，不能把错误信息当代码传下去。"""
    previous: list[dict[str, Any]] = [
        {"tool": "get_quote", "result": {"error": "未找到股票 X 的行情"}}
    ]
    # 退回原始提取逻辑
    assert _extract_stock_code_from_prev("分析一下比亚迪", previous) == {"code": "比亚迪"}


def test_from_prev_without_get_quote_falls_back() -> None:
    assert _extract_stock_code_from_prev("分析一下比亚迪", []) == {"code": "比亚迪"}


class _DeadAdapter:
    """所有方法都返回空/None——模拟全部行情源不可用。"""

    name = "dead"

    def get_quote(self, code: str) -> None:
        return None

    def get_quotes(self, codes: list[str]) -> list[Any]:
        return []

    def get_bars(self, code: str, **kwargs: Any) -> list[Any]:
        return []


def _registry() -> ToolRegistry:
    from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter

    return ToolRegistry(ToolContext(adapter=FallbackAdapter([_DeadAdapter()])))


def test_get_quote_missing_code_returns_structured_error() -> None:
    """回归：早先是 args["code"] → KeyError + traceback 喷终端。"""
    payload = json.loads(_registry().call("get_quote", {}))
    assert "error" in payload
    assert "code" in payload["error"]
    assert "hint" in payload


def test_get_quote_blank_code_returns_structured_error() -> None:
    payload = json.loads(_registry().call("get_quote", {"code": "   "}))
    assert "error" in payload


def test_get_bars_missing_code_returns_structured_error() -> None:
    payload = json.loads(_registry().call("get_bars", {}))
    assert "error" in payload
    assert "hint" in payload


def test_get_bars_all_sources_fail_returns_error_not_empty_list() -> None:
    """回归：FallbackAdapter 全链失败曾返回 None，handler 遍历时 TypeError。"""
    payload = json.loads(_registry().call("get_bars", {"code": "600519", "limit": 5}))
    # 明确告诉调用方"取不到"，而不是让它把 [] 当成零成交
    assert isinstance(payload, dict)
    assert "error" in payload


def test_fallback_adapter_get_bars_returns_empty_list_when_all_fail() -> None:
    """照抄 issue #3 的修法：声明 list[Bar] 就不能返回 None。"""
    from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter
    from mommy_chaogu.market_data.types import BarInterval

    adapter = FallbackAdapter([_DeadAdapter()])
    assert adapter.get_bars("600519", interval=BarInterval.D1, limit=5) == []
    assert adapter.get_bars("600519") == []
