"""资金流工具：当日主力净流入、历史资金流。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_money_flow_today",
        description=(
            "获取股票当日资金流明细（主力/超大单/大单/中单/小单净流入）。"
            "单只用 code；多只（如批量查自选股）用 codes 列表，最多处理前 10 只。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码（单只，与 codes 二选一）"},
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表（多只批量查询，最多前 10 只，与 code 二选一）",
                },
            },
        },
    ),
    ToolDef(
        name="get_money_flow_history",
        description="获取单只股票历史 N 天资金流（每日主力净流入等）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "days": {
                    "type": "integer",
                    "description": "历史天数",
                    "default": 7,
                },
            },
            "required": ["code"],
        },
    ),
]


def _flow_to_dict(latest: Any) -> dict[str, Any]:
    return {
        "code": latest.code,
        "name": latest.name,
        "timestamp": latest.timestamp.isoformat(),
        "main_net": float(latest.main_net.amount),
        "super_large_net": float(latest.super_large_net.amount),
        "large_net": float(latest.large_net.amount),
        "medium_net": float(latest.medium_net.amount),
        "small_net": float(latest.small_net.amount),
        "main_net_ratio": float(latest.main_net_ratio) if latest.main_net_ratio else None,
    }


def _handle_get_money_flow_today(ctx: ToolContext, args: dict[str, Any]) -> str:
    codes_arg = args.get("codes")
    if codes_arg is not None:
        if not isinstance(codes_arg, list) or not codes_arg:
            return _json({"error": "codes 必须是非空股票代码列表"})
        return _handle_multi_money_flow_today(ctx, [str(c) for c in codes_arg[:10]])

    code = args.get("code")
    if not code:
        return _json({"error": "需要 code（单只）或 codes（多只）参数"})
    flows = ctx.adapter.get_today_money_flow(code)
    if not flows:
        return _json({"error": f"未找到 {code} 的当日资金流"})
    return _json(_flow_to_dict(flows[-1]))


def _handle_multi_money_flow_today(ctx: ToolContext, codes: list[str]) -> str:
    """批量查询当日资金流（最多 10 只，调用方负责截断）。

    单只失败不影响其他；全部失败时返回顶层 error（让 workflow 识别为失败步骤）。
    """
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for code in codes:
        try:
            flows = ctx.adapter.get_today_money_flow(code)
        except Exception as e:
            errors[code] = str(e)
            continue
        if not flows:
            errors[code] = "未找到当日资金流"
            continue
        results[code] = _flow_to_dict(flows[-1])

    if not results:
        return _json({"error": "所有股票的当日资金流均不可用", "errors": errors})
    payload: dict[str, Any] = {"results": results, "count": len(results)}
    if errors:
        payload["errors"] = errors
    return _json(payload)


def _handle_get_money_flow_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    days = args.get("days", 7)
    flows = ctx.adapter.get_history_money_flow(code, days=days)
    return _json(
        [
            {
                "code": f.code,
                "name": f.name,
                "timestamp": f.timestamp.isoformat(),
                "main_net": float(f.main_net.amount),
                "super_large_net": float(f.super_large_net.amount),
                "large_net": float(f.large_net.amount),
                "medium_net": float(f.medium_net.amount),
                "small_net": float(f.small_net.amount),
                "main_net_ratio": float(f.main_net_ratio) if f.main_net_ratio else None,
            }
            for f in flows
        ]
    )


HANDLERS: dict[str, ToolHandler] = {
    "get_money_flow_today": _handle_get_money_flow_today,
    "get_money_flow_history": _handle_get_money_flow_history,
}
