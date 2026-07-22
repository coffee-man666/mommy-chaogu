"""K 线工具：历史 K 线查询、历史数据回填。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.types import BarInterval

DEFS: list[ToolDef] = [
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


def _handle_get_bars(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    interval_str = args.get("interval", "1d")
    limit = args.get("limit", 30)
    interval = BarInterval(interval_str)
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


def _handle_backfill_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    # 回填写入行情缓存，与缓存层读取共用 market.db
    db_path = ctx.resolved_market_db
    if db_path is None:
        return _json({"error": "market_db 未配置，无法回填"})
    code = args["code"]
    days = args.get("days", 30)
    store = CacheStore(db_path)
    result = store.backfill_history(ctx.adapter, code, days=days)
    return _json(result)


HANDLERS: dict[str, ToolHandler] = {
    "get_bars": _handle_get_bars,
    "backfill_history": _handle_backfill_history,
}
