"""Deterministic trading-analysis building blocks.

These tools deliberately sit below the LLM workflow compiler.  They expose a
small, bounded result contract so a generated workflow can compose them
without making the model responsible for calculations or response shaping.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json
from mommy_chaogu.market_data.fundamentals_api import get_fundamentals
from mommy_chaogu.market_data.news_api import get_announcements
from mommy_chaogu.market_data.types import BarInterval

MAX_CODES = 50
MAX_RESULTS = 20
FLOW_BATCH_SIZE = 10

DEFS: list[ToolDef] = [
    ToolDef(
        name="screen_inflow_stocks",
        description=(
            "从给定股票代码中筛选主力资金净流入占比达到阈值的股票。"
            "返回统一 results/count/total 契约，最多返回 20 条。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^\\d{6}$"},
                    "description": "股票代码列表，最多 50 只",
                },
                "threshold_bp": {
                    "type": "integer",
                    "description": "主力净流入占比阈值，单位 bp；50bp = 0.5%",
                    "default": 50,
                    "minimum": -10000,
                    "maximum": 10000,
                },
            },
            "required": ["codes"],
        },
    ),
    ToolDef(
        name="check_earnings_catalyst",
        description="逐只检查股票的基本面与最近 3 条公告，识别潜在业绩催化。",
        parameters={
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^\\d{6}$"},
                    "description": "股票代码列表，最多 50 只",
                }
            },
            "required": ["codes"],
        },
    ),
    ToolDef(
        name="check_kline_signal",
        description=(
            "检查收盘后日线信号：volume_breakout 为放量上涨，"
            "ma_golden_cross 为 5 日线上穿 20 日线。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^\\d{6}$"},
                    "description": "股票代码列表，最多 50 只",
                },
                "signal": {
                    "type": "string",
                    "enum": ["volume_breakout", "ma_golden_cross"],
                    "default": "volume_breakout",
                },
            },
            "required": ["codes"],
        },
    ),
]


def _codes(args: dict[str, Any]) -> list[str]:
    raw = args.get("codes", [])
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(code) for code in raw if str(code).isdigit()))[:MAX_CODES]


def _number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _contract(results: list[dict[str, Any]], total: int | None = None) -> str:
    total_value = len(results) if total is None else total
    return _json(
        {
            "results": results[:MAX_RESULTS],
            "count": min(len(results), MAX_RESULTS),
            "total": total_value,
        }
    )


def _handle_screen_inflow_stocks(ctx: ToolContext, args: dict[str, Any]) -> str:
    codes = _codes(args)
    if not codes:
        return _contract([])
    threshold = _number(args.get("threshold_bp", 50))
    if threshold is None:
        threshold = Decimal("50")
    # The adapter is single-code by contract.  Keep the loop in explicit
    # batches so a future batch-capable adapter can replace this body without
    # changing the tool's bounded behavior.
    matched: list[dict[str, Any]] = []
    for start in range(0, len(codes), FLOW_BATCH_SIZE):
        for code in codes[start : start + FLOW_BATCH_SIZE]:
            flows = ctx.adapter.get_today_money_flow(code)
            if not flows:
                continue
            latest = flows[-1]
            ratio_pct = _number(latest.main_net_ratio)
            if ratio_pct is None:
                quote = ctx.adapter.get_quote(code)
                circulating_cap = quote.circulating_market_cap if quote is not None else None
                if circulating_cap is not None and circulating_cap.amount != 0:
                    ratio_pct = latest.main_net.amount / circulating_cap.amount * Decimal("100")
            if ratio_pct is None:
                continue
            ratio_bp = ratio_pct * Decimal("100")
            if ratio_bp < threshold:
                continue
            matched.append(
                {
                    "code": latest.code,
                    "name": latest.name,
                    "main_net": str(latest.main_net.amount),
                    "ratio_bp": str(ratio_bp),
                    "main_net_ratio": str(ratio_pct),
                }
            )
    matched.sort(key=lambda item: Decimal(str(item["ratio_bp"])), reverse=True)
    return _contract(matched, total=len(matched))


def _handle_check_earnings_catalyst(ctx: ToolContext, args: dict[str, Any]) -> str:
    del ctx  # Fundamentals/news use their own resilient data adapters.
    results: list[dict[str, Any]] = []
    for code in _codes(args):
        fundamentals = get_fundamentals(code)
        announcements = get_announcements(code, limit=3)
        results.append(
            {
                "code": code,
                "name": fundamentals.get("name", ""),
                "pe": fundamentals.get("pe"),
                "roe": fundamentals.get("roe"),
                "has_earnings_ann": any(
                    any(
                        word in str(item.get("title", ""))
                        for word in ("业绩", "财报", "年报", "半年报")
                    )
                    for item in announcements
                ),
                "ann_titles": [str(item.get("title", "")) for item in announcements],
            }
        )
    return _contract(results)


def _completed_daily_bars(bars: list[Any], now: datetime | None = None) -> list[Any]:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    if not ordered:
        return []
    current = now or datetime.now()
    last = ordered[-1]
    # A daily bar dated today is incomplete until the regular A-share close.
    if last.timestamp.date() == current.date() and current.time() < time(15, 5):
        return ordered[:-1]
    return ordered


def _bar_change_pct(bar: Any) -> Decimal:
    if bar.change_pct is not None:
        return _number(bar.change_pct) or Decimal("0")
    open_value = _number(bar.open)
    close_value = _number(bar.close)
    if open_value is None or open_value == Decimal("0") or close_value is None:
        return Decimal("0")
    return (close_value / open_value - Decimal("1")) * Decimal("100")


def _volume_ratio(bars: list[Any], index: int) -> Decimal | None:
    if index < 5:
        return None
    average = sum(Decimal(str(bar.volume)) for bar in bars[index - 5 : index]) / Decimal("5")
    if average == 0:
        return None
    return Decimal(str(bars[index].volume)) / average


def _ma(bars: list[Any], end: int, window: int) -> Decimal:
    values = [Decimal(str(bar.close)) for bar in bars[end - window + 1 : end + 1]]
    return sum(values) / Decimal(str(window))


def _handle_check_kline_signal(ctx: ToolContext, args: dict[str, Any]) -> str:
    signal = str(args.get("signal", "volume_breakout"))
    if signal not in {"volume_breakout", "ma_golden_cross"}:
        return _json({"error": "signal 必须是 volume_breakout 或 ma_golden_cross"})
    results: list[dict[str, Any]] = []
    for code in _codes(args):
        bars = _completed_daily_bars(ctx.adapter.get_bars(code, interval=BarInterval.D1, limit=30))
        if not bars:
            continue
        index = len(bars) - 1
        current = bars[index]
        volume_ratio = _volume_ratio(bars, index)
        change_pct = _bar_change_pct(current)
        hit = False
        if signal == "volume_breakout":
            hit = (
                len(bars) >= 6
                and volume_ratio is not None
                and volume_ratio > Decimal("1.5")
                and change_pct > Decimal("2")
            )
        elif len(bars) >= 22:
            # Check the most recent completed bar and its predecessor for a
            # cross; this avoids reporting an old crossover as current.
            for end in (index - 1, index):
                if end < 20:
                    continue
                previous_short = _ma(bars, end - 1, 5)
                previous_long = _ma(bars, end - 1, 20)
                current_short = _ma(bars, end, 5)
                current_long = _ma(bars, end, 20)
                if previous_short <= previous_long and current_short > current_long:
                    hit = True
                    current = bars[end]
                    volume_ratio = _volume_ratio(bars, end)
                    change_pct = _bar_change_pct(current)
                    break
        if hit:
            results.append(
                {
                    "code": current.code,
                    "name": current.name,
                    "signal": signal,
                    "close": str(current.close),
                    "volume_ratio": str(volume_ratio) if volume_ratio is not None else None,
                    "change_pct": str(change_pct),
                }
            )
    return _contract(results)


HANDLERS: dict[str, ToolHandler] = {
    "screen_inflow_stocks": _handle_screen_inflow_stocks,
    "check_earnings_catalyst": _handle_check_earnings_catalyst,
    "check_kline_signal": _handle_check_kline_signal,
}
