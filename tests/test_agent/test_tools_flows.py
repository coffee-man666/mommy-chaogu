"""get_money_flow_today 的 codes 批量参数测试（EVALUATION-2026-07-18 T2/T3）。

修复前 handler 只认单数 code，flow_check 工作流传入 {"codes": [...]} 每次
必败。现在支持 codes 列表（cap 10），返回按 code 分组的结果；单数 code
行为不变。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools.base import ToolContext
from mommy_chaogu.agent.tools.flows import HANDLERS
from mommy_chaogu.market_data.types import Money, MoneyFlow


def _make_flow(code: str) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=f"股{code}",
        timestamp=datetime(2026, 7, 18, 15, 0, 0),
        main_net=Money.from_yuan("1000000"),
        small_net=Money.from_yuan("-100000"),
        medium_net=Money.from_yuan("-200000"),
        large_net=Money.from_yuan("300000"),
        super_large_net=Money.from_yuan("500000"),
        main_net_ratio=Decimal("1.5"),
    )


def _ctx_with_flows(codes_with_data: list[str]) -> ToolContext:
    """adapter：list 内的 code 有资金流数据，其余返回空。"""
    adapter = MagicMock()

    def get_today_money_flow(code: str) -> list[MoneyFlow]:
        return [_make_flow(code)] if code in codes_with_data else []

    adapter.get_today_money_flow.side_effect = get_today_money_flow
    return ToolContext(adapter=adapter)


class TestSingleCodeUnchanged:
    def test_single_code(self) -> None:
        ctx = _ctx_with_flows(["600519"])
        result = HANDLERS["get_money_flow_today"](ctx, {"code": "600519"})
        data = json.loads(result)
        assert data["code"] == "600519"
        assert "main_net" in data

    def test_single_code_not_found(self) -> None:
        ctx = _ctx_with_flows([])
        result = HANDLERS["get_money_flow_today"](ctx, {"code": "600519"})
        assert "error" in json.loads(result)


class TestCodesBatch:
    def test_codes_grouped_by_code(self) -> None:
        ctx = _ctx_with_flows(["600519", "000858"])
        result = HANDLERS["get_money_flow_today"](ctx, {"codes": ["600519", "000858"]})
        data = json.loads(result)
        assert data["count"] == 2
        assert set(data["results"].keys()) == {"600519", "000858"}
        assert data["results"]["600519"]["main_net"] == 1000000.0

    def test_codes_capped_at_10(self) -> None:
        codes = [f"6000{i:02d}" for i in range(12)]
        ctx = _ctx_with_flows(codes)
        result = HANDLERS["get_money_flow_today"](ctx, {"codes": codes})
        data = json.loads(result)
        assert data["count"] == 10
        assert len(data["results"]) == 10
        # adapter 只被调 10 次（截断在请求前生效）
        assert ctx.adapter.get_today_money_flow.call_count == 10

    def test_codes_partial_failure(self) -> None:
        """部分股票无数据：成功的进 results，失败的进 errors，步骤整体成功。"""
        ctx = _ctx_with_flows(["600519"])
        result = HANDLERS["get_money_flow_today"](ctx, {"codes": ["600519", "000858"]})
        data = json.loads(result)
        assert "error" not in data
        assert data["count"] == 1
        assert "600519" in data["results"]
        assert "000858" in data["errors"]

    def test_codes_all_failed_returns_error(self) -> None:
        """全部失败时返回顶层 error（让 workflow 识别为失败步骤）。"""
        ctx = _ctx_with_flows([])
        result = HANDLERS["get_money_flow_today"](ctx, {"codes": ["600519", "000858"]})
        assert "error" in json.loads(result)

    def test_codes_adapter_exception_per_code(self) -> None:
        """单只 adapter 异常不拖垮整批。"""
        adapter = MagicMock()

        def get_today_money_flow(code: str) -> list[MoneyFlow]:
            if code == "000858":
                raise RuntimeError("network error")
            return [_make_flow(code)]

        adapter.get_today_money_flow.side_effect = get_today_money_flow
        ctx = ToolContext(adapter=adapter)
        result = HANDLERS["get_money_flow_today"](ctx, {"codes": ["600519", "000858"]})
        data = json.loads(result)
        assert data["count"] == 1
        assert "network error" in data["errors"]["000858"]

    def test_codes_empty_list_error(self) -> None:
        ctx = _ctx_with_flows(["600519"])
        result = HANDLERS["get_money_flow_today"](ctx, {"codes": []})
        assert "error" in json.loads(result)

    def test_neither_code_nor_codes_error(self) -> None:
        ctx = _ctx_with_flows(["600519"])
        result = HANDLERS["get_money_flow_today"](ctx, {})
        assert "error" in json.loads(result)
