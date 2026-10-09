"""行情报价工具：单只/批量实时报价、大盘指数、名称搜索。"""

from __future__ import annotations

import re
from typing import Any

from mommy_chaogu.agent.tools.base import (
    ToolContext,
    ToolDef,
    ToolHandler,
    _clamp_int,
    _json,
    _quote_to_dict,
)
from mommy_chaogu.market_data.rankings import fetch_indexes
from mommy_chaogu.market_data.stock_search import search_stocks_by_name

# 与 get_quote 原参数 pattern 一致：`^` 指数、美股字母、A 股 6 位数字。
# 匹配则直接走行情；不匹配（中文名等）先做名称解析。
_CODE_RE = re.compile(r"^(\^[A-Z]{1,6}|[A-Z]{1,6}|\d{6})$")

DEFS: list[ToolDef] = [
    ToolDef(
        name="search_stock",
        description=(
            "按名称/拼音搜索股票，返回代码+名称+市场。"
            "用户提到股票名称（如'比亚迪'、'苹果'）时，先用此工具解析成代码，"
            "再调用 get_quote/get_bars 等行情工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "股票名称或拼音，如 '比亚迪'、'茅台'、'maotai'、'苹果'",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "最多返回条数（默认 8）",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDef(
        name="get_quote",
        description=(
            "获取单只股票的实时报价。返回最新价、涨跌幅、成交量、换手率、市值等。"
            "code 支持三种形式：A 股 6 位数字如 '600519'、美股字母如 'AAPL'、"
            "`^` 前缀美股指数/利率/VIX 如 '^GSPC'；也可直接传中文名称如 '比亚迪'（自动解析为代码）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码（'600519'/'AAPL'/'^GSPC'）或中文名称（'比亚迪'）",
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
                    "items": {"type": "string", "pattern": "^(\\^[A-Z]{1,6}|[A-Z]{1,6}|\\d{6})$"},
                    "description": "股票代码列表，如 ['600519', 'AAPL', '^GSPC']",
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


def _handle_search_stock(_ctx: ToolContext, args: dict[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return _json({"error": "query 不能为空"})
    limit = _clamp_int(args.get("limit"), 8, 1, 20)
    hits = search_stocks_by_name(query, limit)
    if not hits:
        return _json(
            {
                "error": f"未找到与 '{query}' 匹配的股票",
                "hint": "可尝试更完整的名称或拼音",
            }
        )
    return _json(
        {
            "query": query,
            "count": len(hits),
            "results": [{"code": h.code, "name": h.name, "market": h.market} for h in hits],
        }
    )


def _resolve_code(raw: str) -> str | None:
    """把 LLM 传来的 code 参数规整为适配链可用的代码。

    本身是代码（含 `^` 指数）直接返回；否则视为名称做一次搜索，
    优先取名称完全一致的命中。解析不到返回 None。
    """
    if _CODE_RE.match(raw):
        return raw
    hits = search_stocks_by_name(raw, limit=5)
    for h in hits:
        if h.name == raw:
            return h.code
    return hits[0].code if hits else None


def _handle_get_quote(ctx: ToolContext, args: dict[str, Any]) -> str:
    raw = str(args.get("code") or "").strip()
    if not raw:
        return _json(
            {
                "error": "缺少股票代码或名称参数 code",
                "hint": '传入 6 位代码（"600519"）或中文名称（"比亚迪"），也可先用 search_stock 解析',
            }
        )
    code = _resolve_code(raw)
    if code is None:
        return _json(
            {
                "error": f"未找到股票 {raw} 的行情",
                "hint": "可用 search_stock 按名称搜索代码",
            }
        )
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
    "search_stock": _handle_search_stock,
    "get_quote": _handle_get_quote,
    "get_quotes": _handle_get_quotes,
    "get_market_indexes": _handle_get_market_indexes,
}
