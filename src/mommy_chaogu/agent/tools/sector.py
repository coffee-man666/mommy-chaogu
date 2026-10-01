"""板块工具：板块涨跌排行、板块搜索、成分股行情、板块 K 线与多日相对强弱。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import (
    ToolContext,
    ToolDef,
    ToolHandler,
    _clamp_int,
    _floatify,
    _json,
)
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.rankings import fetch_sector_ranking
from mommy_chaogu.market_data.sector_api import fetch_sector_stocks, search_sector
from mommy_chaogu.market_data.types import BarInterval
from mommy_chaogu.services.sector_momentum import SectorMomentumService

# get_sector_bars 单次返回上限与 agent/tools/bars.py 的个股 get_bars 对齐。
MAX_SECTOR_BARS_LIMIT = 120

# get_sector_momentum 返回行数上限：全量约 90 行业 + 400 概念的排名表
# 远超工具结果 8KB 截断（registry.MAX_RESULT_BYTES），只出 top N + 汇总。
MAX_MOMENTUM_TOP = 50

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_sector_ranking",
        description="获取板块涨跌幅排行（行业板块 + 概念板块合并去重，按涨跌幅排序）。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回前 N 个板块，默认 30（最大 100）",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 100,
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
                    "description": "东财板块代码，如 'BK1106'（创新药）、'BK1036'（半导体）",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["change_pct", "main_net", "turnover", "amount"],
                    "description": "排序方式：涨跌幅/主力净流入/换手率/成交额",
                    "default": "change_pct",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回前 N 只股票（最大 100）",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["board_code"],
        },
    ),
    ToolDef(
        name="get_sector_bars",
        description=(
            "获取板块 K 线（东财板块代码直通，如 BK1036 半导体）。"
            "板块代码先用 search_sector 动态查询，不要凭记忆猜测（板块代码会漂移）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^BK\\d{4}$",
                    "description": "东财板块代码，如 'BK1036'（半导体）——先用 search_sector 查询",
                },
                "interval": {
                    "type": "string",
                    "enum": ["1d", "1w", "1M", "5m", "15m", "30m", "60m"],
                    "description": "K 线周期",
                    "default": "1d",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回 K 线根数（最大 120）",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 120,
                },
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="get_sector_momentum",
        description=(
            "板块多日相对强弱排名：N 日涨幅 + 排名 vs 上一窗口（路径式，回答"
            "「过去 N 日哪些板块最强？钱在往哪走？」，不是当日截面）。"
            "首次全量拉取较慢（逐板块拉日 K 且有限速），二次执行走本地缓存明显变快。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "回看窗口（交易日），默认 20（2~60）",
                    "default": 20,
                    "minimum": 2,
                    "maximum": 60,
                },
                "include_concept": {
                    "type": "boolean",
                    "description": "是否纳入概念板块（约 400 个，首次拉取明显变慢），默认只算行业板块（约 90 个）",
                    "default": False,
                },
                "top": {
                    "type": "integer",
                    "description": "返回前 N 名板块（最大 50）",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
        },
    ),
]


def _handle_get_sector_ranking(_ctx: ToolContext, args: dict[str, Any]) -> str:
    limit = _clamp_int(args.get("limit", 30), 30, 1, 100)
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
    limit = _clamp_int(args.get("limit", 30), 30, 1, 100)
    stocks = fetch_sector_stocks(board_code, sort_by=sort_by, limit=limit)
    return _json(_floatify(stocks))


def _handle_get_sector_bars(ctx: ToolContext, args: dict[str, Any]) -> str:
    # BK 代码直通 adapter（EfinanceAdapter.get_bars 无前缀校验）；
    # 个股工具 get_bars 的 code pattern 不动，避免个股工具误收板块代码。
    code = args["code"]
    interval = BarInterval(args.get("interval", "1d"))
    limit = _clamp_int(args.get("limit", 30), 30, 1, MAX_SECTOR_BARS_LIMIT)
    bars = ctx.adapter.get_bars(code, interval=interval, limit=limit)
    return _json(
        [
            {
                "code": b.code,
                "name": b.name,
                "timestamp": b.timestamp.isoformat(),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": b.volume,
                "turnover": float(b.turnover.amount),
                "change_pct": float(b.change_pct) if b.change_pct else None,
            }
            for b in bars
        ]
    )


def _handle_get_sector_momentum(ctx: ToolContext, args: dict[str, Any]) -> str:
    days = _clamp_int(args.get("days", 20), 20, 2, 60)
    include_concept = bool(args.get("include_concept", False))
    top = _clamp_int(args.get("top", 20), 20, 1, MAX_MOMENTUM_TOP)

    # 缓存库用于「板块列表拉取失败时回退 bar_cache 已缓存板块」；
    # 与 backfill_history 同款按需开库，market_db 未配置则无回退池。
    store: CacheStore | None = None
    if ctx.resolved_market_db is not None:
        store = CacheStore(ctx.resolved_market_db)
    try:
        service = SectorMomentumService(ctx.adapter, store=store)
        result = service.compute(days, include_concept=include_concept)
    finally:
        if store is not None:
            store.close()

    ranking = result.get("ranking")
    if isinstance(ranking, list):
        result["ranking"] = ranking[:top]
        result["showing_top"] = f"{min(top, len(ranking))}/{len(ranking)}"
    return _json(_floatify(result))


HANDLERS: dict[str, ToolHandler] = {
    "get_sector_ranking": _handle_get_sector_ranking,
    "search_sector": _handle_search_sector,
    "get_sector_stocks": _handle_get_sector_stocks,
    "get_sector_bars": _handle_get_sector_bars,
    "get_sector_momentum": _handle_get_sector_momentum,
}
