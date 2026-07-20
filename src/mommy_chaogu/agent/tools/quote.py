"""行情报价工具：单只/批量实时报价、大盘指数。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json, _quote_to_dict
from mommy_chaogu.market_data.rankings import fetch_indexes

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_quote",
        description="获取单只股票的实时报价。返回最新价、涨跌幅、成交量、换手率、市值等。",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码，如 '600519'（贵州茅台）、'000001'（平安银行）",
                }
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="get_quotes",
        description="批量获取多只股票的实时报价。最多 50 只。",
        parameters={
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，如 ['600519', '000001']",
                }
            },
            "required": ["codes"],
        },
    ),
    ToolDef(
        name="get_market_indexes",
        description="获取大盘核心指数行情（上证指数、深证成指、创业板指、沪深300、科创50、上证50）。",
        parameters={"type": "object", "properties": {}},
    ),
]


def _handle_get_quote(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    q = ctx.adapter.get_quote(code)
    if q is None:
        return _json({"error": f"未找到股票 {code} 的行情"})
    return _json(_quote_to_dict(q))


def _handle_get_quotes(ctx: ToolContext, args: dict[str, Any]) -> str:
    codes = args["codes"][:50]  # 最多 50 只
    quotes = ctx.adapter.get_quotes(codes)
    return _json([_quote_to_dict(q) for q in quotes])


def _handle_get_market_indexes(_ctx: ToolContext, _args: dict[str, Any]) -> str:
    indexes = fetch_indexes()
    return _json(
        [
            {
                "code": i.code,
                "name": i.name,
                "price": float(i.price),
                "change_pct": float(i.change_pct),
                "prev_close": float(i.prev_close),
            }
            for i in indexes
        ]
    )


HANDLERS: dict[str, ToolHandler] = {
    "get_quote": _handle_get_quote,
    "get_quotes": _handle_get_quotes,
    "get_market_indexes": _handle_get_market_indexes,
}
