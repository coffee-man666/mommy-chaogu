"""K 线工具：历史 K 线查询、历史数据回填。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _clamp_int, _json
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.codes import INDEX_OR_STOCK_CODE_PATTERN
from mommy_chaogu.market_data.types import BarInterval

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_bars",
        description="获取股票 K 线数据（日/周/月/分钟级别）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": INDEX_OR_STOCK_CODE_PATTERN,
                    "description": "股票代码（A 股 6 位数字或美股字母；`^` 前缀为美股指数/利率/VIX 如 '^GSPC'）",
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
                "include_ma": {
                    "type": "boolean",
                    "description": "在每根 K 线上附加简单均线值（服务端计算，字段名 ma_<窗口>）",
                    "default": False,
                },
                "ma_windows": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 2, "maximum": 250},
                    "description": "均线窗口列表（最多 4 个，默认 [5, 20]；仅 include_ma 时生效）",
                    "default": [5, 20],
                    "maxItems": 4,
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
                "code": {
                    "type": "string",
                    "pattern": INDEX_OR_STOCK_CODE_PATTERN,
                    "description": "股票代码（A 股 6 位数字或美股字母；`^` 前缀为美股指数/利率/VIX 如 '^GSPC'）",
                },
                "days": {
                    "type": "integer",
                    "description": "回填天数，默认 30（最大 365）",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 365,
                },
            },
            "required": ["code"],
        },
    ),
]

# get_bars 单次返回上限（根）：120 根日 K ≈ 半年，再大只会灌爆
# agent 的 context window（EVALUATION-2026-07-18 L2/T5）。
MAX_BARS_LIMIT = 120

# backfill_history 单次回填上限（天）。
MAX_BACKFILL_DAYS = 365


def _ma_windows(args: dict[str, Any]) -> list[int]:
    """解析 ma_windows：去重、排序、最多 4 个，各钳到 [2, 250]；默认 [5, 20]。"""
    raw = args.get("ma_windows")
    if not isinstance(raw, list) or not raw:
        return [5, 20]
    windows: list[int] = []
    for item in raw:
        try:
            window = int(item)
        except (TypeError, ValueError):
            continue
        window = max(2, min(250, window))
        if window not in windows:
            windows.append(window)
        if len(windows) == 4:
            break
    return windows or [5, 20]


def _handle_get_bars(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    interval_str = args.get("interval", "1d")
    limit = _clamp_int(args.get("limit", 30), 30, 1, MAX_BARS_LIMIT)
    interval = BarInterval(interval_str)
    bars = ctx.adapter.get_bars(code, interval=interval, limit=limit)
    include_ma = args.get("include_ma") is True
    # MA 序列服务端计算（含当根收盘的简单均线），浏览器/TS 侧只渲染不算指标
    windows = _ma_windows(args) if include_ma else []
    closes = [float(b.close) for b in bars]
    payload: list[dict[str, Any]] = []
    for i, b in enumerate(bars):
        row: dict[str, Any] = {
            "code": b.code,
            "name": b.name,
            "timestamp": b.timestamp.isoformat(),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": closes[i],
            "volume": b.volume,
            "turnover": float(b.turnover.amount),
            "change_pct": float(b.change_pct) if b.change_pct else None,
        }
        for window in windows:
            row[f"ma_{window}"] = (
                round(sum(closes[i - window + 1 : i + 1]) / window, 4) if i + 1 >= window else None
            )
        payload.append(row)
    return _json(payload)


def _handle_backfill_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    # 回填写入行情缓存，与缓存层读取共用 market.db
    db_path = ctx.resolved_market_db
    if db_path is None:
        return _json({"error": "market_db 未配置，无法回填"})
    code = args["code"]
    days = _clamp_int(args.get("days", 30), 30, 1, MAX_BACKFILL_DAYS)
    store = CacheStore(db_path)
    result = store.backfill_history(ctx.adapter, code, days=days)
    return _json(result)


HANDLERS: dict[str, ToolHandler] = {
    "get_bars": _handle_get_bars,
    "backfill_history": _handle_backfill_history,
}
