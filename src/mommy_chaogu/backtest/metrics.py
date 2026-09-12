"""统一的风险/收益统计口径（单一真相源）。

此前夏普与最大回撤在 backtest.engine、backtest.portfolio、
backtest.regime_analysis、portfolio.analysis 四处各有一份私有实现，
无风险利率折算（算术 vs 几何）与自由度（ddof=0 vs 1）已经漂移。
本模块收敛为一份，口径写死如下，修改必须同步校准受影响的既有数值断言
（tests/test_backtest*.py、tests/test_portfolio.py）：

- 无风险年化利率 2%；日折算用算术 ``rf / 252``
- 样本标准差 ddof=1
- 逐笔收益的年化系数 ``sqrt(252 / 每笔覆盖交易日)``
- 日频收益的年化波动 = 日波动 × ``sqrt(252)``
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "RISK_FREE_ANNUAL",
    "TRADING_DAYS",
    "annualized_vol_pct",
    "daily_sharpe_ratio",
    "drawdown_fraction",
    "max_drawdown_pct",
    "sharpe_ratio",
]

# 无风险年化利率 2%
RISK_FREE_ANNUAL = 0.02
# 年交易日
TRADING_DAYS = 252


def drawdown_fraction(values: Sequence[float]) -> float:
    """从净值/价格序列计算最大回撤比例（0~1，正数）。

    适用于收盘价（regime 判定）、组合净值曲线（backtest.portfolio）、
    复利净值（见 :func:`max_drawdown_pct`）。
    """
    if not values:
        return 0.0
    peak = float(values[0])
    max_dd = 0.0
    for raw in values:
        v = float(raw)
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return abs(max_dd)


def max_drawdown_pct(returns_pct: Sequence[float]) -> float:
    """从逐笔收益率序列（%）复利计算最大回撤（%，正数）。"""
    if not returns_pct:
        return 0.0
    equity = 1.0
    curve: list[float] = []
    for r in returns_pct:
        equity *= 1 + r / 100
        curve.append(equity)
    return drawdown_fraction(curve) * 100


def sharpe_ratio(returns_pct: Sequence[float], period_days: int) -> float:
    """逐笔收益率（%）序列的年化夏普。

    - 每笔覆盖 ``period_days`` 个交易日（持有期）
    - rf 按 ``年化 2% × period_days / 252`` 算术折算到每笔
    - 年化系数 ``sqrt(252 / period_days)``
    """
    n = len(returns_pct)
    if n < 2:
        return 0.0

    daily_returns = [r / 100 for r in returns_pct]
    mean_r = sum(daily_returns) / n
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (n - 1)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0

    rf_per_trade = RISK_FREE_ANNUAL * period_days / TRADING_DAYS
    excess = mean_r - rf_per_trade
    annualization = math.sqrt(TRADING_DAYS / period_days)
    return (excess / std_r) * annualization


def annualized_vol_pct(daily_returns: Sequence[float]) -> float:
    """日频收益（小数）的年化波动率（%），样本标准差 ddof=1。"""
    n = len(daily_returns)
    if n < 2:
        return 0.0
    mean_r = sum(daily_returns) / n
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (n - 1)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS) * 100


def daily_sharpe_ratio(daily_returns: Sequence[float]) -> float:
    """日频收益（小数）的年化夏普。

    rf 用算术 ``2% / 252``（与逐笔口径一致；此前 portfolio.analysis 用
    几何折算 ``(1+2%)^(1/252)-1``，此处统一为算术）；分子 ×252 年化。
    """
    vol_pct = annualized_vol_pct(daily_returns)
    if vol_pct <= 0:
        return 0.0
    n = len(daily_returns)
    mean_r = sum(daily_returns) / n
    rf_daily = RISK_FREE_ANNUAL / TRADING_DAYS
    mean_excess = mean_r - rf_daily
    return (mean_excess * TRADING_DAYS) / (vol_pct / 100)
