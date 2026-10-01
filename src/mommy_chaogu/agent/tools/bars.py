"""K 线工具：历史 K 线查询、历史数据回填、A 股指数 K 线、日内画像。"""

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
from mommy_chaogu.market_data.rankings import INDEX_CODES, INDEX_LIST, resolve_index_symbol
from mommy_chaogu.market_data.types import BarInterval
from mommy_chaogu.services.intraday_service import IntradayService

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_bars",
        description="获取股票 K 线数据（日/周/月/分钟级别）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^(\\^[A-Z]{1,6}|[A-Z]{1,6}|\\d{6})$",
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
                    "pattern": "^(\\^[A-Z]{1,6}|[A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母；`^` 前缀为美股指数/利率/VIX 如 '^GSPC'）",
                },
                "days": {
                    "type": "integer",
                    "description": "回填天数，默认 30（最大 365）；分钟周期时表示回填根数（受上游分钟存档深度限制）",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 365,
                },
                "interval": {
                    "type": "string",
                    "enum": ["1d", "5m", "15m", "30m", "60m"],
                    "description": (
                        "K 线周期，默认 1d。分钟周期只回填分钟 K（按日打包落缓存，不回填资金流）；"
                        "仅 1d 回填历史资金流"
                    ),
                    "default": "1d",
                },
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="get_index_bars",
        description=(
            "获取 A 股指数 K 线（上证指数/深证成指/创业板指/沪深300/科创50/上证50）。"
            "指数代码必须带市场前缀（如 'sh000001' 上证指数）——裸 6 位数字是 A 股个股"
            "代码（'000001' 是平安银行，不是上证指数），会被拒绝。"
            "输出标注判定标的（index_name + index_code），防止把个股日 K 误当指数。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "enum": list(INDEX_CODES),
                    "description": (
                        "指数代码：sh000001 上证指数 / sz399001 深证成指 / sz399006 创业板指"
                        " / sh000300 沪深300 / sh000688 科创50 / sh000016 上证50"
                    ),
                    "default": "sh000001",
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
        },
    ),
    ToolDef(
        name="get_intraday_profile",
        description=(
            "超短期日内画像：今天资金怎么交易这只股票。三段指标：开盘半小时"
            "（10:00 价相对昨收 + 量占比）、VWAP 相对位置（典型价近似）、尾盘"
            " 14:30-15:00 段行为（涨跌 + 量占比）。5 分钟 K，东财主源 + 腾讯"
            " mkline 备源，经本地缓存。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^\\d{6}$",
                    "description": "A 股 6 位数字代码（如 600519）",
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


def _handle_get_bars(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    interval_str = args.get("interval", "1d")
    limit = _clamp_int(args.get("limit", 30), 30, 1, MAX_BARS_LIMIT)
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
    days = _clamp_int(args.get("days", 30), 30, 1, MAX_BACKFILL_DAYS)
    interval = BarInterval(args.get("interval", "1d"))
    store = CacheStore(db_path)
    result = store.backfill_history(ctx.adapter, code, days=days, interval=interval)
    return _json(result)


def _handle_get_intraday_profile(ctx: ToolContext, args: dict[str, Any]) -> str:
    """超短期日内画像（阶段六）：5 分钟 K → 开盘半小时 / VWAP（典型价近似）/ 尾盘段。"""
    code = args["code"]
    service = IntradayService(ctx.adapter)
    return _json(_floatify(service.profile(code)))


def _index_help() -> str:
    return " / ".join(f"{code} {name}" for _secid, name, code in INDEX_LIST)


def _handle_get_index_bars(ctx: ToolContext, args: dict[str, Any]) -> str:
    """A 股指数 K 线通路：INDEX_LIST 白名单解析 + 输出标注判定标的。

    防错源（docs/plans/trading-method-landing.md 阶段四任务 1 / 风险 R10）：
    裸 '000001' 会静默拉到平安银行日 K——这里按 INDEX_LIST（secid/名称/代码）
    白名单解析，解析不到直接报错并列出可选指数，绝不透传给 adapter。
    """
    raw = str(args.get("code") or "sh000001")
    entry = resolve_index_symbol(raw)
    if entry is None:
        return _json(
            {
                "error": f"未知指数代码 '{raw}'：A 股指数代码必须带市场前缀",
                "hint": f"可选指数：{_index_help()}；裸 6 位数字（如 '000001'）是 A 股个股代码（平安银行），不能当指数用",
            }
        )
    secid, name, code = entry
    interval = BarInterval(args.get("interval", "1d"))
    limit = _clamp_int(args.get("limit", 30), 30, 1, MAX_BARS_LIMIT)
    bars = ctx.adapter.get_bars(code, interval=interval, limit=limit)
    subject = f"{name} {code}"
    if not bars:
        return _json(
            {
                "error": f"{subject} 指数 K 线不可得（上游无数据或网络不可达）",
                "subject": subject,
                "index_code": code,
                "count": 0,
            }
        )
    return _json(
        {
            "subject": subject,  # 判定标的标注：防把个股日 K 误当指数
            "index_name": name,
            "index_code": code,
            "secid": secid,
            "interval": interval.value,
            "count": len(bars),
            "bars": [
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
            ],
            "note": f"判定标的：{name} {code}（东财 secid {secid}）",
        }
    )


HANDLERS: dict[str, ToolHandler] = {
    "get_bars": _handle_get_bars,
    "backfill_history": _handle_backfill_history,
    "get_index_bars": _handle_get_index_bars,
    "get_intraday_profile": _handle_get_intraday_profile,
}
