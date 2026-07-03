"""工具层：把现有数据接口包装成 function-calling tools。

设计：
- ToolDef: 工具定义（name + description + JSON Schema parameters）
- ToolContext: 共享的依赖注入容器（adapter + stores）
- ToolRegistry: 注册 + 查找 + 调用

所有 handler 是同步函数，内部直接调 adapter（已被 CachedMarketDataAdapter 包装）。
AgentService 负责用 asyncio.to_thread 包装。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.fundamentals_api import get_fundamentals
from mommy_chaogu.market_data.news_api import get_announcements, get_longhuban, search_news
from mommy_chaogu.market_data.rankings import fetch_indexes, fetch_sector_ranking
from mommy_chaogu.market_data.sector_api import fetch_sector_stocks, search_sector
from mommy_chaogu.market_data.types import BarInterval, Quote
from mommy_chaogu.portfolio.store import PortfolioStore
from mommy_chaogu.watchlist.store import WatchlistStore

_log = logging.getLogger(__name__)


# ---------- 数据结构 ----------


@dataclass(frozen=True)
class ToolDef:
    """单个工具的定义。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def to_openai_dict(self) -> dict[str, Any]:
        """转 OpenAI function-calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolContext:
    """工具层的共享依赖。"""

    adapter: MarketDataAdapter
    watchlist_store: WatchlistStore | None = None
    portfolio_store: PortfolioStore | None = None
    db_path: Path | None = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], str]


# ---------- JSON 序列化辅助 ----------


def _quote_to_dict(q: Quote) -> dict[str, Any]:
    return {
        "code": q.code,
        "name": q.name,
        "price": float(q.price),
        "change_pct": float(q.change_pct),
        "change": float(q.change),
        "open": float(q.open),
        "high": float(q.high),
        "low": float(q.low),
        "prev_close": float(q.prev_close),
        "volume": q.volume,
        "turnover": float(q.turnover.amount),
        "turnover_rate": float(q.turnover_rate) if q.turnover_rate else None,
        "volume_ratio": float(q.volume_ratio) if q.volume_ratio else None,
        "pe": float(q.pe_dynamic) if q.pe_dynamic else None,
        "total_market_cap": float(q.total_market_cap.amount) if q.total_market_cap else None,
        "circulating_market_cap": (
            float(q.circulating_market_cap.amount) if q.circulating_market_cap else None
        ),
        "timestamp": q.timestamp.isoformat(),
    }


def _json(obj: Any) -> str:
    """安全 JSON 序列化（处理 Decimal / datetime）。"""
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))


# ---------- 工具定义 ----------


_TOOL_DEFINITIONS: list[ToolDef] = [
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
    ToolDef(
        name="get_bars",
        description="获取股票 K 线数据（日/周/月/分钟级别）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "interval": {
                    "type": "string",
                    "enum": ["1d", "1w", "1M", "5m", "15m", "30m", "60m"],
                    "description": "K 线周期",
                    "default": "1d",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回 K 线根数",
                    "default": 30,
                },
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="get_watchlist",
        description="获取用户的自选股列表。",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="get_portfolio",
        description="获取用户持仓明细（含成本、盈亏）。需要先有行情数据来计算盈亏。",
        parameters={"type": "object", "properties": {}},
    ),
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
    ToolDef(
        name="backfill_history",
        description="批量回填指定股票的历史 K 线和资金流数据到本地缓存，便于离线分析。",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "days": {
                    "type": "integer",
                    "description": "回填天数，默认 30",
                    "default": 30,
                },
            },
            "required": ["code"],
        },
    ),
]


# ---------- 工具实现 ----------


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
    return _json([
        {
            "code": i.code,
            "name": i.name,
            "price": float(i.price),
            "change_pct": float(i.change_pct),
            "prev_close": float(i.prev_close),
        }
        for i in indexes
    ])


def _handle_get_sector_ranking(_ctx: ToolContext, args: dict[str, Any]) -> str:
    limit = args.get("limit", 30)
    items = fetch_sector_ranking(limit=limit)
    return _json([
        {
            "code": i["code"],
            "name": i["name"],
            "change_pct": float(i["change_pct"]),
        }
        for i in items
    ])


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


def _handle_get_money_flow_today(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    flows = ctx.adapter.get_today_money_flow(code)
    if not flows:
        return _json({"error": f"未找到 {code} 的当日资金流"})
    latest = flows[-1]
    return _json({
        "code": latest.code,
        "name": latest.name,
        "timestamp": latest.timestamp.isoformat(),
        "main_net": float(latest.main_net.amount),
        "super_large_net": float(latest.super_large_net.amount),
        "large_net": float(latest.large_net.amount),
        "medium_net": float(latest.medium_net.amount),
        "small_net": float(latest.small_net.amount),
        "main_net_ratio": float(latest.main_net_ratio) if latest.main_net_ratio else None,
    })


def _handle_get_money_flow_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    days = args.get("days", 7)
    flows = ctx.adapter.get_history_money_flow(code, days=days)
    return _json([
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
    ])


def _handle_get_bars(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    interval_str = args.get("interval", "1d")
    limit = args.get("limit", 30)
    interval = BarInterval(interval_str)
    bars = ctx.adapter.get_bars(code, interval=interval, limit=limit)
    return _json([
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
    ])


def _handle_get_watchlist(ctx: ToolContext, _args: dict[str, Any]) -> str:
    if ctx.watchlist_store is None:
        return _json({"error": "自选股未配置"})
    entries = ctx.watchlist_store.list_entries()
    return _json([
        {
            "code": e.code,
            "name": e.name or "—",
            "group": e.group.name,
            "note": e.note or "",
        }
        for e in entries
    ])


def _handle_get_portfolio(ctx: ToolContext, _args: dict[str, Any]) -> str:
    if ctx.portfolio_store is None:
        return _json({"error": "持仓未配置"})
    positions = ctx.portfolio_store.list_positions()
    if not positions:
        return _json({"positions": [], "message": "暂无持仓"})

    # 拉当前报价来算盈亏
    codes = list({p.code for p in positions if p.shares > 0})
    current_prices: dict[str, Decimal] = {}
    if codes:
        quotes = ctx.adapter.get_quotes(codes)
        for q in quotes:
            current_prices[q.code] = q.price

    summary = ctx.portfolio_store.summary(current_prices)

    result_positions = []
    for item in summary["positions"]:
        pos = item["position"]  # type: ignore[attr-defined]
        result_positions.append({
            "code": pos.code,
            "name": pos.name or "—",
            "shares": int(item["shares"]),  # type: ignore[arg-type]
            "avg_cost": float(item["avg_cost"]),  # type: ignore[arg-type]
            "current_price": float(item["current_price"]) if item["current_price"] else None,  # type: ignore[arg-type]
            "market_value": float(item["market_value"]) if item["market_value"] else None,  # type: ignore[arg-type]
            "total_cost": float(item["total_cost"]),  # type: ignore[arg-type]
            "unrealized_pnl": float(item["unrealized_pnl"]) if item["unrealized_pnl"] else None,  # type: ignore[arg-type]
            "unrealized_pnl_pct": (
                float(item["unrealized_pnl_pct"]) if item["unrealized_pnl_pct"] else None  # type: ignore[arg-type]
            ),
        })

    return _json({
        "positions": result_positions,
        "total_cost": float(summary["total_cost"]),  # type: ignore[arg-type]
        "total_market_value": (
            float(summary["total_market_value"]) if summary["total_market_value"] else None  # type: ignore[arg-type]
        ),
        "total_unrealized_pnl": (
            float(summary["total_unrealized_pnl"]) if summary["total_unrealized_pnl"] else None  # type: ignore[arg-type]
        ),
        "total_unrealized_pnl_pct": (
            float(summary["total_unrealized_pnl_pct"])  # type: ignore[arg-type]
            if summary["total_unrealized_pnl_pct"]
            else None
        ),
        "n_positions": int(summary["n_positions"]),  # type: ignore[arg-type]
    })


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


def _handle_backfill_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.db_path is None:
        return _json({"error": "db_path 未配置，无法回填"})
    code = args["code"]
    days = args.get("days", 30)
    store = CacheStore(ctx.db_path)
    result = store.backfill_history(ctx.adapter, code, days=days)
    return _json(result)


# ---------- 注册表 ----------


_HANDLERS: dict[str, ToolHandler] = {
    "get_quote": _handle_get_quote,
    "get_quotes": _handle_get_quotes,
    "get_market_indexes": _handle_get_market_indexes,
    "get_sector_ranking": _handle_get_sector_ranking,
    "search_sector": _handle_search_sector,
    "get_sector_stocks": _handle_get_sector_stocks,
    "get_money_flow_today": _handle_get_money_flow_today,
    "get_money_flow_history": _handle_get_money_flow_history,
    "get_bars": _handle_get_bars,
    "get_watchlist": _handle_get_watchlist,
    "get_portfolio": _handle_get_portfolio,
    "search_news": _handle_search_news,
    "get_announcements": _handle_get_announcements,
    "get_longhuban": _handle_get_longhuban,
    "get_fundamentals": _handle_get_fundamentals,
    "backfill_history": _handle_backfill_history,
}

_TOOL_MAP: dict[str, ToolDef] = {td.name: td for td in _TOOL_DEFINITIONS}


class ToolRegistry:
    """工具注册表：查找工具定义 + 执行工具调用。"""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    def definitions(self) -> list[dict[str, Any]]:
        """返回 OpenAI function-calling 格式的 tool definitions。"""
        return [td.to_openai_dict() for td in _TOOL_DEFINITIONS]

    def call(self, name: str, args: dict[str, Any]) -> str:
        """执行工具调用，返回 JSON 字符串结果。

        Raises:
            KeyError: 工具名不存在
        """
        handler = _HANDLERS.get(name)
        if handler is None:
            return _json({"error": f"未知工具: {name}"})
        try:
            return handler(self._ctx, args)
        except Exception as e:
            _log.exception("tool %s failed", name)
            return _json({"error": f"工具执行失败: {e}"})

    @staticmethod
    def tool_names() -> list[str]:
        return list(_HANDLERS.keys())
