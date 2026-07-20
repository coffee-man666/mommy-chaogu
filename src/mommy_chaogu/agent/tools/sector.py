"""板块工具：板块涨跌排行、板块搜索、成分股行情。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json
from mommy_chaogu.market_data.rankings import fetch_sector_ranking
from mommy_chaogu.market_data.sector_api import fetch_sector_stocks, search_sector

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_sector_ranking",
        description="获取板块涨跌幅排行（行业板块 + 概念板块合并去重，按涨跌幅排序）。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回前 N 个板块，默认 30",
                    "default": 30,
                }
            },
        },
    ),
    ToolDef(
        name="search_sector",
        description="按关键字搜索板块代码。如搜索'创新药'返回 BK1106。在调用 get_sector_stocks 前先用这个找板块代码。",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键字，如 '创新药'、'半导体'、'人工智能'",
                }
            },
            "required": ["keyword"],
        },
    ),
    ToolDef(
        name="get_sector_stocks",
        description="获取某个板块的成分股行情（按涨幅排序）。需要先用 search_sector 找到板块代码。",
        parameters={
            "type": "object",
            "properties": {
                "board_code": {
                    "type": "string",
                    "description": "东财板块代码，如 'BK1106'（创新药）、'BK0475'（半导体）",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["change_pct", "main_net", "turnover", "amount"],
                    "description": "排序方式：涨跌幅/主力净流入/换手率/成交额",
                    "default": "change_pct",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回前 N 只股票",
                    "default": 30,
                },
            },
            "required": ["board_code"],
        },
    ),
]


def _handle_get_sector_ranking(_ctx: ToolContext, args: dict[str, Any]) -> str:
    limit = args.get("limit", 30)
    items = fetch_sector_ranking(limit=limit)
    return _json(
        [
            {
                "code": i["code"],
                "name": i["name"],
                "change_pct": float(i["change_pct"]),
            }
            for i in items
        ]
    )


def _handle_search_sector(_ctx: ToolContext, args: dict[str, Any]) -> str:
    keyword = args["keyword"]
    results = search_sector(keyword)
    return _json(results)


def _handle_get_sector_stocks(_ctx: ToolContext, args: dict[str, Any]) -> str:
    board_code = args["board_code"]
    sort_by = args.get("sort_by", "change_pct")
    limit = args.get("limit", 30)
    stocks = fetch_sector_stocks(board_code, sort_by=sort_by, limit=limit)
    return _json(stocks)


HANDLERS: dict[str, ToolHandler] = {
    "get_sector_ranking": _handle_get_sector_ranking,
    "search_sector": _handle_search_sector,
    "get_sector_stocks": _handle_get_sector_stocks,
}
