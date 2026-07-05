"""市场环境分组分析模块 ``mommy_chaogu.backtest.regime_analysis`` 的测试。"""

from __future__ import annotations

from mommy_chaogu.backtest.regime_analysis import (
    analyze_by_regime,
    classify_market_regime,
    compare_strategies_across_regimes,
    format_regime_report,
)

# ----------------------------------------------------------------------
# 模拟 K 线构造工具
# ----------------------------------------------------------------------


def _bars_from_closes(closes: list[float], start: str = "2026-01-01") -> list[dict]:
    """把一组收盘价转成升序日 K 线（每天 +1 天）。"""
    from datetime import date, timedelta

    base = date.fromisoformat(start)
    return [
        {"date": (base + timedelta(days=i)).isoformat(), "close": c} for i, c in enumerate(closes)
    ]


def _bull_closes(n: int = 80) -> list[float]:
    """稳步上涨、低波动：每日 +0.4%，回撤极小。"""
    return [100.0 * (1.004**i) for i in range(n)]


def _bear_closes(n: int = 80) -> list[float]:
    """下跌 + 高波动：基线每日 -0.5%，叠加 ±2% 交替震荡。"""
    closes: list[float] = [100.0]
    for i in range(1, n):
        base = closes[-1] * 0.995  # -0.5%
        shock = 1.02 if i % 2 == 0 else 0.98  # 交替 ±2%
        closes.append(base * shock)
    return closes


def _sideways_closes(n: int = 80) -> list[float]:
    """横盘震荡：围绕 100 上下 1% 交替，均线纠缠、波动适中。"""
    return [100.0 * (1.01 if i % 2 == 0 else 0.99) for i in range(n)]


# ----------------------------------------------------------------------
# classify_market_regime
# ----------------------------------------------------------------------


def test_classify_bull() -> None:
    bars = _bars_from_closes(_bull_closes())
    assert classify_market_regime(bars) == "bull"


def test_classify_bear() -> None:
    bars = _bars_from_closes(_bear_closes())
    assert classify_market_regime(bars) == "bear"


def test_classify_sideways() -> None:
    bars = _bars_from_closes(_sideways_closes())
    assert classify_market_regime(bars) == "sideways"


def test_classify_insufficient_data_returns_sideways() -> None:
    # 少于 MA_SHORT(20) 根 → sideways
    assert classify_market_regime(_bars_from_closes([100, 101, 102])) == "sideways"


def test_classify_takes_trailing_window() -> None:
    """前 60 根下跌 + 后 60 根强势上涨 → 尾部窗口判 bull。"""
    closes = _bear_closes(60) + _bull_closes(60)
    bars = _bars_from_closes(closes)
    assert classify_market_regime(bars) == "bull"


# ----------------------------------------------------------------------
# analyze_by_regime
# ----------------------------------------------------------------------


def test_analyze_groups_predictions_by_regime() -> None:
    """构造一段 bull + 一段 bear 的指数，预测落在对应日期，分组应正确。"""
    bull_bars = _bars_from_closes(_bull_closes(60), start="2026-01-01")
    bear_bars = _bars_from_closes(_bear_closes(60), start="2026-03-12")  # 紧接 bull 之后
    index_bars = bull_bars + bear_bars

    # bull 期内：bullish 预测命中（change_pct=+5%）
    pred_bull_hit = {"direction": "bullish", "change_pct": 5.0, "created_at": "2026-02-15"}
    # bull 期内：bearish 预测未命中（change_pct=+5%）
    pred_bull_miss = {"direction": "bearish", "change_pct": 5.0, "created_at": "2026-02-20"}
    # bear 期内：bearish 预测命中（change_pct=-5%）
    pred_bear_hit = {"direction": "bearish", "change_pct": -5.0, "created_at": "2026-05-01"}

    result = analyze_by_regime([pred_bull_hit, pred_bull_miss, pred_bear_hit], index_bars)

    assert set(result.keys()) == {"bull", "bear", "sideways"}
    assert result["bull"]["total"] == 2
    assert result["bull"]["hit"] == 1
    assert result["bull"]["rate"] == 0.5
    assert result["bear"]["total"] == 1
    assert result["bear"]["hit"] == 1
    assert result["bear"]["rate"] == 1.0
    assert result["sideways"]["total"] == 0
    assert result["sideways"]["rate"] == 0.0


def test_analyze_empty_predictions() -> None:
    result = analyze_by_regime([], _bars_from_closes(_bull_closes()))
    for regime in ("bull", "bear", "sideways"):
        assert result[regime] == {"total": 0, "hit": 0, "rate": 0.0}


def test_analyze_prediction_before_index_returns_sideways() -> None:
    """预测日期早于首根 K 线 → 归入 sideways。"""
    index_bars = _bars_from_closes(_bull_closes(), start="2026-03-01")
    pred = {"direction": "bullish", "change_pct": 5.0, "created_at": "2026-01-01"}
    result = analyze_by_regime([pred], index_bars)
    assert result["sideways"]["total"] == 1
    assert result["bull"]["total"] == 0


def test_analyze_accepts_date_field_for_prediction() -> None:
    """预测用 ``date`` 而非 ``created_at`` 也能定位。"""
    index_bars = _bars_from_closes(_bull_closes(), start="2026-01-01")
    pred = {"direction": "bullish", "change_pct": 5.0, "date": "2026-02-15"}
    result = analyze_by_regime([pred], index_bars)
    assert result["bull"]["total"] == 1


# ----------------------------------------------------------------------
# format_regime_report
# ----------------------------------------------------------------------


def test_format_regime_report_contains_all_regimes() -> None:
    analysis = {
        "bull": {"total": 10, "hit": 7, "rate": 0.7},
        "bear": {"total": 8, "hit": 2, "rate": 0.25},
        "sideways": {"total": 5, "hit": 3, "rate": 0.6},
    }
    report = format_regime_report(analysis)
    assert "市场环境分组命中率分析" in report
    assert "bull" in report
    assert "bear" in report
    assert "sideways" in report
    # 总体命中 12/23
    assert "12/23" in report


def test_format_regime_report_empty() -> None:
    analysis = {
        "bull": {"total": 0, "hit": 0, "rate": 0.0},
        "bear": {"total": 0, "hit": 0, "rate": 0.0},
        "sideways": {"total": 0, "hit": 0, "rate": 0.0},
    }
    report = format_regime_report(analysis)
    assert "0/0" in report


# ----------------------------------------------------------------------
# compare_strategies_across_regimes
# ----------------------------------------------------------------------


def test_compare_strategies_diff_rate() -> None:
    index_bars = _bars_from_closes(_bull_closes(), start="2026-01-01")

    # 策略 A：bull 期 bullish 全命中
    preds_a = [
        {"direction": "bullish", "change_pct": 5.0, "created_at": "2026-02-01"},
        {"direction": "bullish", "change_pct": 4.0, "created_at": "2026-02-10"},
    ]
    # 策略 B：bull 期 bearish 全未命中
    preds_b = [
        {"direction": "bearish", "change_pct": 5.0, "created_at": "2026-02-01"},
        {"direction": "bearish", "change_pct": 4.0, "created_at": "2026-02-10"},
    ]

    cmp = compare_strategies_across_regimes(preds_a, preds_b, index_bars)
    assert set(cmp.keys()) == {"bull", "bear", "sideways"}
    assert cmp["bull"]["strategy_a"]["rate"] == 1.0
    assert cmp["bull"]["strategy_b"]["rate"] == 0.0
    assert cmp["bull"]["diff_rate"] == 1.0
    # bear/sideways 双方都无样本 → diff_rate == 0
    assert cmp["bear"]["diff_rate"] == 0.0
    assert cmp["sideways"]["diff_rate"] == 0.0


# ----------------------------------------------------------------------
# 端到端：模拟 bull + bear 两段行情完整走一遍
# ----------------------------------------------------------------------


def test_end_to_end_pipeline() -> None:
    bull_bars = _bars_from_closes(_bull_closes(60), start="2026-01-01")
    bear_bars = _bars_from_closes(_bear_closes(60), start="2026-03-12")
    index_bars = bull_bars + bear_bars

    predictions = [
        # bull 期：bullish 命中、bearish 未命中
        {"direction": "bullish", "change_pct": 6.0, "created_at": "2026-02-01"},
        {"direction": "bullish", "change_pct": 3.0, "created_at": "2026-02-10"},
        {"direction": "bearish", "change_pct": 4.0, "created_at": "2026-02-15"},
        # bear 期：bearish 命中、bullish 未命中
        {"direction": "bearish", "change_pct": -6.0, "created_at": "2026-05-01"},
        {"direction": "bullish", "change_pct": -4.0, "created_at": "2026-05-10"},
    ]

    analysis = analyze_by_regime(predictions, index_bars)
    report = format_regime_report(analysis)

    # bull 期 3 条，2 命中
    assert analysis["bull"]["total"] == 3
    assert analysis["bull"]["hit"] == 2
    # bear 期 2 条，1 命中
    assert analysis["bear"]["total"] == 2
    assert analysis["bear"]["hit"] == 1
    # sideways 无样本
    assert analysis["sideways"]["total"] == 0

    # 报告可渲染、含关键数字
    assert "上涨" in report
    assert "下跌" in report
    assert "2/3" in report
    assert "1/2" in report
