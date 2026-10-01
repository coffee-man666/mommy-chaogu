"""Deterministic trading-analysis building blocks.

These tools deliberately sit below the LLM workflow compiler.  They expose a
small, bounded result contract so a generated workflow can compose them
without making the model responsible for calculations or response shaping.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from mommy_chaogu.agent.tools.base import (
    ToolContext,
    ToolDef,
    ToolHandler,
    _clamp_int,
    _floatify,
    _json,
)
from mommy_chaogu.market_data.fundamentals_api import get_fundamentals
from mommy_chaogu.market_data.news_api import get_announcements
from mommy_chaogu.market_data.rankings import INDEX_CODES
from mommy_chaogu.market_data.types import BarInterval
from mommy_chaogu.services.regime_series import DEFAULT_DAYS as _REGIME_DEFAULT_DAYS
from mommy_chaogu.services.regime_series import MAX_DAYS as _REGIME_MAX_DAYS
from mommy_chaogu.services.regime_series import MIN_DAYS as _REGIME_MIN_DAYS
from mommy_chaogu.services.regime_series import RegimeSeriesService

MAX_CODES = 50
MAX_RESULTS = 20
FLOW_BATCH_SIZE = 10

# check_kline_signal 支持的日线信号枚举。high_20_breakout / price_above_ma20
# 是「短期右侧确认」信号（docs/plans/trading-method-landing.md 阶段一）。
_KLINE_SIGNALS = frozenset(
    {"volume_breakout", "ma_golden_cross", "high_20_breakout", "price_above_ma20"}
)

# get_bars 日 K 的复权/时点语义未核验（docs/plans/trading-method-landing.md
# §2 阶段一边界），核验前 K 线信号输出统一带该标注——消费方按未复权口径解读。
_UNVERIFIED_ADJUSTMENT_NOTE = "K线复权语义未核验，信号按未复权口径解读"

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
            "检查收盘后日线信号（15:05 前剔除当日未完成 K 线）：volume_breakout 为放量上涨，"
            "ma_golden_cross 为 5 日线上穿 20 日线，high_20_breakout 为收盘突破前 20 根"
            "完成日 K 的最高高点，price_above_ma20 为收盘站上 MA20。"
            "results 只含命中记录；evidence 逐只给出判定依据"
            "（hit/high_20/ma20/close/bars_used，未命中也输出）。"
            "K 线复权语义未核验，按未复权口径解读。"
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
                    "enum": [
                        "volume_breakout",
                        "ma_golden_cross",
                        "high_20_breakout",
                        "price_above_ma20",
                    ],
                    "default": "volume_breakout",
                },
            },
            "required": ["codes"],
        },
    ),
    ToolDef(
        name="market_regime_series",
        description=(
            "市场环境路径式状态：A 股指数近 N 个交易日的逐日三态序列"
            "（bull/bear/sideways）+ 状态持续天数与切换点，回答"
            "「现在市场什么状态？跟上周比有什么变化？」而非单值截面。"
            "输出标注判定标的（如「上证指数 sh000001」）与「探索性状态评估」"
            "（波动率阈值未在真实指数数据校准，不构成择时建议）。"
            "指数代码必须带市场前缀——'000001' 是平安银行不是上证指数。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "index_code": {
                    "type": "string",
                    "enum": list(INDEX_CODES),
                    "description": (
                        "指数代码：sh000001 上证指数 / sz399001 深证成指 / sz399006 创业板指"
                        " / sh000300 沪深300 / sh000688 科创50 / sh000016 上证50"
                    ),
                    "default": "sh000001",
                },
                "days": {
                    "type": "integer",
                    "description": f"回看交易日数，默认 {_REGIME_DEFAULT_DAYS}"
                    f"（{_REGIME_MIN_DAYS}~{_REGIME_MAX_DAYS}）",
                    "default": _REGIME_DEFAULT_DAYS,
                    "minimum": _REGIME_MIN_DAYS,
                    "maximum": _REGIME_MAX_DAYS,
                },
            },
        },
    ),
]


def _codes(args: dict[str, Any]) -> list[str]:
    raw = args.get("codes", [])
    if isinstance(raw, str):
        raw = [raw]
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


def _contract(
    results: list[dict[str, Any]],
    total: int | None = None,
    evidence: list[dict[str, Any]] | None = None,
    note: str | None = None,
) -> str:
    total_value = len(results) if total is None else total
    payload: dict[str, Any] = {
        "results": results[:MAX_RESULTS],
        "count": min(len(results), MAX_RESULTS),
        "total": total_value,
    }
    # 依据明细走独立字段（不进 results）：count 语义保持「命中数」，
    # 不破坏既有 top20 截断契约；evidence 同样按 MAX_RESULTS 截断保持有界。
    if evidence is not None:
        payload["evidence"] = evidence[:MAX_RESULTS]
    if note is not None:
        payload["note"] = note
    return _json(payload)


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
    return _contract(_floatify(results))


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


def _high_20(bars: list[Any], end: int, window: int = 20) -> Decimal | None:
    """bars[end] 之前 window 根完成 K 线的最高高点；不足 window 根返回 None。"""
    if end < window:
        return None
    return max(Decimal(str(bar.high)) for bar in bars[end - window : end])


def _evidence_record(
    code: str,
    name: str,
    signal: str,
    *,
    hit: bool,
    close: Decimal | None,
    high_20: Decimal | None,
    ma20: Decimal | None,
    bars_used: int,
) -> dict[str, Any]:
    """单只代码的判定依据记录——未命中（hit=false）也带数值依据。"""
    return {
        "code": code,
        "name": name,
        "signal": signal,
        "hit": hit,
        "close": str(close) if close is not None else None,
        "high_20": str(high_20) if high_20 is not None else None,
        "ma20": str(ma20) if ma20 is not None else None,
        "bars_used": bars_used,
    }


def _handle_check_kline_signal(ctx: ToolContext, args: dict[str, Any]) -> str:
    signal = str(args.get("signal", "volume_breakout"))
    if signal not in _KLINE_SIGNALS:
        return _json(
            {
                "error": "signal 必须是 volume_breakout / ma_golden_cross / high_20_breakout / price_above_ma20"
            }
        )
    results: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for code in _codes(args):
        bars = _completed_daily_bars(ctx.adapter.get_bars(code, interval=BarInterval.D1, limit=30))
        if not bars:
            # 数据不可得也留一条依据记录：bars_used=0 明示无依据，不产出假信号。
            evidence.append(
                _evidence_record(
                    code, "", signal, hit=False, close=None, high_20=None, ma20=None, bars_used=0
                )
            )
            continue
        index = len(bars) - 1
        latest = bars[index]
        current = bars[index]
        volume_ratio = _volume_ratio(bars, index)
        change_pct = _bar_change_pct(current)
        # 两个右侧确认信号的依据：前 20 根完成 K 的最高高点（不含当前根）、
        # 含当前根的 20 日均线；完成 K 根数不足时为 None，判定不成立。
        high_20 = _high_20(bars, index)
        ma20 = _ma(bars, index, 20) if index >= 19 else None
        hit = False
        if signal == "volume_breakout":
            hit = (
                len(bars) >= 6
                and volume_ratio is not None
                and volume_ratio > Decimal("1.5")
                and change_pct > Decimal("2")
            )
        elif signal == "high_20_breakout":
            hit = high_20 is not None and current.close > high_20
        elif signal == "price_above_ma20":
            hit = ma20 is not None and current.close > ma20
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
        evidence.append(
            _evidence_record(
                latest.code,
                latest.name,
                signal,
                hit=hit,
                close=latest.close,
                high_20=high_20,
                ma20=ma20,
                bars_used=len(bars),
            )
        )
        if hit:
            results.append(
                {
                    "code": current.code,
                    "name": current.name,
                    "signal": signal,
                    "hit": True,
                    "close": str(current.close),
                    "volume_ratio": str(volume_ratio) if volume_ratio is not None else None,
                    "change_pct": str(change_pct),
                }
            )
    return _contract(results, evidence=evidence, note=_UNVERIFIED_ADJUSTMENT_NOTE)


def _handle_market_regime_series(ctx: ToolContext, args: dict[str, Any]) -> str:
    """市场环境路径式状态：指数日 K → 逐日三态序列 + 切换摘要。

    数据入口是 get_index_bars 同源的 INDEX_LIST 白名单（服务层
    resolve_index_symbol 解析），输出带判定标的标注与「探索性状态评估」。
    """
    raw_index = str(args.get("index_code") or "sh000001")
    days = _clamp_int(
        args.get("days", _REGIME_DEFAULT_DAYS),
        _REGIME_DEFAULT_DAYS,
        _REGIME_MIN_DAYS,
        _REGIME_MAX_DAYS,
    )
    service = RegimeSeriesService(ctx.adapter)
    return _json(_floatify(service.compute(raw_index, days=days)))


HANDLERS: dict[str, ToolHandler] = {
    "screen_inflow_stocks": _handle_screen_inflow_stocks,
    "check_earnings_catalyst": _handle_check_earnings_catalyst,
    "check_kline_signal": _handle_check_kline_signal,
    "market_regime_series": _handle_market_regime_series,
}
