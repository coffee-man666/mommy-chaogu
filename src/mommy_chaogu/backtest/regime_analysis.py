"""市场环境（regime）分组分析模块。

背景：当前所有回测样本都落在 2026 年 6 月（强势上涨期），bearish 命中率
低可能是市场环境 artifact 而非 LLM 分析能力差。本模块把预测按创建时的市场
状态（bull / bear / sideways）分组，分别统计命中率，从而把「分析能力」从
「市场 beta」里剥离出来。

市场状态判定（基于指数日 K 线，如沪深 300）：

- **bull** —— 20 日均线在 60 日均线之上（多头排列）且波动率低
- **bear** —— 20 日均线在 60 日均线之下（空头排列）且波动率高 / 回撤大
- **sideways** —— 其他（均线纠缠、或单一条件不满足）

命中率口径复用 :func:`backtest.scoring.score_direction`（±2% 死区），
与单条评分、组合回测保持一致。
"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.backtest.scoring import score_direction

__all__ = [
    "MA_LONG",
    "MA_SHORT",
    "analyze_by_regime",
    "classify_market_regime",
    "compare_strategies_across_regimes",
    "format_regime_report",
]

# 均线参数
MA_SHORT = 20
MA_LONG = 60

# 波动率阈值：日收益率标准差（小数）
BULL_VOL_THRESHOLD = 0.020  # ≤2% 视为低波动（bull 必要条件）
BEAR_VOL_THRESHOLD = 0.025  # ≥2.5% 视为高波动（bear 触发条件之一）
# 回撤阈值（小数）：空头排列 + 大回撤也算 bear
BEAR_DRAWDOWN_THRESHOLD = 0.10

_REGIMES = ("bull", "bear", "sideways")
_REGIME_LABEL = {"bull": "上涨", "bear": "下跌", "sideways": "震荡"}


# ----------------------------------------------------------------------
# 市场状态判定
# ----------------------------------------------------------------------


def _bar_date(bar: dict[str, Any]) -> str:
    """从 K 线字典提取日期（``YYYY-MM-DD``）。兼容 ``date`` / ``timestamp``。"""
    raw = bar.get("date") or bar.get("timestamp") or ""
    return str(raw)[:10]


def _prediction_date(pred: dict[str, Any]) -> str:
    """从预测字典提取创建日期（``YYYY-MM-DD``）。兼容 ``created_at`` / ``date``。"""
    raw = pred.get("created_at") or pred.get("date") or ""
    return str(raw)[:10]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    """样本标准差（ddof=1），不足 2 个返回 0。"""
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    return var**0.5


def _daily_returns(closes: list[float]) -> list[float]:
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def _max_drawdown(closes: list[float]) -> float:
    """从收盘价序列计算最大回撤（小数，正数）。"""
    peak = closes[0] if closes else 0.0
    max_dd = 0.0
    for px in closes:
        if px > peak:
            peak = px
        if peak > 0:
            dd = (px - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return abs(max_dd)


def classify_market_regime(bars: list[dict[str, Any]]) -> str:
    """根据指数日 K 线判断市场状态。

    Args:
        bars: 指数日 K 线列表，每条至少含 ``close``（兼容 ``date`` / ``timestamp``）。
            按日期升序传入；取尾部窗口计算指标。

    Returns:
        ``"bull"`` / ``"bear"`` / ``"sideways"``。

    判定逻辑：

    - 样本不足 :data:`MA_LONG` 时退化到用 :data:`MA_SHORT` 比较，再不足则判 ``sideways``。
    - **bull**：20 日均线 > 60 日均线 **且** 波动率 ≤ :data:`BULL_VOL_THRESHOLD`
    - **bear**：20 日均线 < 60 日均线 **且**（波动率 ≥ :data:`BEAR_VOL_THRESHOLD`
      或最大回撤 ≥ :data:`BEAR_DRAWDOWN_THRESHOLD`）
    - 其他 → ``sideways``
    """
    closes = [float(b["close"]) for b in bars]
    n = len(closes)
    if n < MA_SHORT:
        return "sideways"

    # 所有指标统一在尾部 MA_LONG 窗口内计算（判定「当前」市场状态）
    window = closes[-MA_LONG:] if n >= MA_LONG else closes
    ma_short = _mean(window[-MA_SHORT:])
    ma_long = _mean(window)

    vol = _std(_daily_returns(window))
    dd = _max_drawdown(window)

    if ma_short > ma_long and vol <= BULL_VOL_THRESHOLD:
        return "bull"
    if ma_short < ma_long and (vol >= BEAR_VOL_THRESHOLD or dd >= BEAR_DRAWDOWN_THRESHOLD):
        return "bear"
    return "sideways"


# ----------------------------------------------------------------------
# 按环境分组分析
# ----------------------------------------------------------------------


def _regime_at(index_bars: list[dict[str, Any]], dates: list[str], pred_date: str) -> str:
    """取 ``pred_date`` 当天及之前最多 :data:`MA_LONG` 根 K 线判定市场状态。

    预测日期早于首根 K 线（无前置行情）时判 ``sideways``。
    """
    # 二分找最后一个 date <= pred_date
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] <= pred_date:
            lo = mid + 1
        else:
            hi = mid
    idx = lo - 1  # dates[idx] <= pred_date 的最大下标
    if idx < 0:
        return "sideways"
    start = max(0, idx - MA_LONG + 1)
    return classify_market_regime(index_bars[start : idx + 1])


def analyze_by_regime(
    predictions: list[dict[str, Any]],
    index_bars: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """将预测按创建时的市场状态分组，分别统计命中率。

    Args:
        predictions: 预测字典列表，每条至少含 ``direction``、到期 ``change_pct``，
            以及 ``created_at`` 或 ``date``（用于定位市场状态）。
        index_bars: 指数日 K 线（升序），用于逐日判定 regime。

    Returns:
        ``{"bull": {"total", "hit", "rate"}, "bear": {...}, "sideways": {...}}``，
        命中率口径同 :func:`backtest.scoring.score_direction`。
    """
    index_bars = sorted(index_bars, key=lambda b: _bar_date(b))
    dates = [_bar_date(b) for b in index_bars]

    result: dict[str, dict[str, Any]] = {r: {"total": 0, "hit": 0, "rate": 0.0} for r in _REGIMES}

    for pred in predictions:
        regime = _regime_at(index_bars, dates, _prediction_date(pred))
        result[regime]["total"] += 1

        direction = str(pred.get("direction", "")).strip().lower()
        change = pred.get("change_pct")
        if change is not None:
            status, _ = score_direction(direction, float(change))
            if status == "hit":
                result[regime]["hit"] += 1

    for bucket in result.values():
        bucket["rate"] = bucket["hit"] / bucket["total"] if bucket["total"] else 0.0
    return result


# ----------------------------------------------------------------------
# 报告 & 对比
# ----------------------------------------------------------------------


def format_regime_report(analysis: dict[str, dict[str, Any]]) -> str:
    """格式化市场环境分组分析为可读文本。

    Args:
        analysis: :func:`analyze_by_regime` 的返回值。

    Returns:
        多行文本，逐 regime 给出命中数 / 总数 / 命中率。
    """
    total_all = sum(d.get("total", 0) for d in analysis.values())
    hit_all = sum(d.get("hit", 0) for d in analysis.values())
    overall = hit_all / total_all if total_all else 0.0

    lines = [
        "市场环境分组命中率分析",
        f"  总体: {hit_all}/{total_all} = {overall:.1%}",
    ]
    for regime in _REGIMES:
        d = analysis.get(regime, {"total": 0, "hit": 0, "rate": 0.0})
        total = d.get("total", 0)
        hit = d.get("hit", 0)
        rate = d.get("rate", 0.0)
        lines.append(f"  {_REGIME_LABEL[regime]:>4}({regime}): {hit}/{total} = {rate:.1%}")
    return "\n".join(lines)


def compare_strategies_across_regimes(
    predictions_a: list[dict[str, Any]],
    predictions_b: list[dict[str, Any]],
    index_bars: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """对比两个策略在不同市场环境下的命中率差异。

    Args:
        predictions_a: 策略 A 的预测列表。
        predictions_b: 策略 B 的预测列表。
        index_bars: 指数日 K 线（共用，用于判定 regime）。

    Returns:
        ``{regime: {"strategy_a": {...}, "strategy_b": {...}, "diff_rate": float}}``，
        ``diff_rate`` 为 A - B 的命中率差（正数表示 A 更优）。
    """
    a = analyze_by_regime(predictions_a, index_bars)
    b = analyze_by_regime(predictions_b, index_bars)
    comparison: dict[str, dict[str, Any]] = {}
    for regime in _REGIMES:
        comparison[regime] = {
            "strategy_a": a[regime],
            "strategy_b": b[regime],
            "diff_rate": a[regime]["rate"] - b[regime]["rate"],
        }
    return comparison
