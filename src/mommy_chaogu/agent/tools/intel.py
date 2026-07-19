"""资讯与基本面工具：新闻搜索、公告、龙虎榜、基本面。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json
from mommy_chaogu.market_data.fundamentals_api import get_fundamentals
from mommy_chaogu.market_data.news_api import (
    get_announcements,
    get_longhuban,
    search_news,
)

DEFS: list[ToolDef] = [
    ToolDef(
        name="search_news",
        description="搜索财经新闻。返回标题、来源、日期、摘要。用于了解板块/个股的最新消息和政策。",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键字，如 '创新药 政策'、'半导体 限制'、'茅台'",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 10",
                    "default": 10,
                },
            },
            "required": ["keyword"],
        },
    ),
    ToolDef(
        name="get_announcements",
        description="获取个股最新公告列表（董事会决议、财报、增减持等）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 10",
                    "default": 10,
                },
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="get_longhuban",
        description="获取龙虎榜数据（游资/机构买卖明细）。可看哪些股票被大资金关注。",
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "日期 YYYY-MM-DD，默认今天",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 20",
                    "default": 20,
                },
            },
        },
    ),
    ToolDef(
        name="get_fundamentals",
        description="获取个股基本面指标（PE/PB/PS/ROE/毛利率/净利率/市值/所属行业），用于评估股票质地。",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码，如 '600519'（贵州茅台）",
                }
            },
            "required": ["code"],
        },
    ),
]


def _handle_search_news(_ctx: ToolContext, args: dict[str, Any]) -> str:
    keyword = args["keyword"]
    limit = args.get("limit", 10)
    items = search_news(keyword, limit=limit)
    return _json(items)


def _handle_get_announcements(_ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    limit = args.get("limit", 10)
    items = get_announcements(code, limit=limit)
    return _json(items)


def _handle_get_longhuban(_ctx: ToolContext, args: dict[str, Any]) -> str:
    date = args.get("date")
    limit = args.get("limit", 20)
    items = get_longhuban(date=date, limit=limit)
    return _json(items)


def _handle_get_fundamentals(_ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    result = get_fundamentals(code)
    return _json(result)


HANDLERS: dict[str, ToolHandler] = {
    "search_news": _handle_search_news,
    "get_announcements": _handle_get_announcements,
    "get_longhuban": _handle_get_longhuban,
    "get_fundamentals": _handle_get_fundamentals,
}
