"""资金流工具：当日主力净流入、历史资金流。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_money_flow_today",
        description="获取单只股票当日资金流明细（主力/超大单/大单/中单/小单净流入）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
            },
            "required": ["code"],
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


def _handle_get_money_flow_today(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    flows = ctx.adapter.get_today_money_flow(code)
    if not flows:
        return _json({"error": f"未找到 {code} 的当日资金流"})
    latest = flows[-1]
    return _json(
        {
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
    )


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
