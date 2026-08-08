"""
indicators.py — 指标层

库的指标选择有一条主线: **一切阈值用 ATR 归一化**。

为什么用 ATR 而不是固定点数/百分比:
  1. 跨品种可比 —— SOXX 的 1 ATR 和 IWM 的 1 ATR 含义相同 (当前波动尺度);
  2. 跨 regime 自适应 —— 波动率扩张/收缩时阈值自动跟随, 不需要人工调参;
  3. 统计学含义稳定 —— "距离云带 2 ATR" 大致等价于 "2 个日波动单位",
     在不同年份读数一致 (本库回测证实: 2023 与 2026 的底部特征读数可直接比较)。

EMA 用 adjust=False 的递推式, 与 TradingView ta.ema 完全一致
(已用用户的指标导出数据反推验证: 误差 < 0.001)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(close: pd.Series, span: int) -> pd.Series:
    """指数均线, alpha = 2/(span+1), 与 TradingView 一致。"""
    return close.ewm(span=span, adjust=False).mean()


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder 口径的滚动 TR 均值 (简单均值版, 与原型一致)。"""
    h, lo, c = bars["high"], bars["low"], bars["close"]
    tr = pd.concat([h - lo, (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema_cloud(close: pd.Series, fast: int = 55, slow: int = 89) -> pd.DataFrame:
    """
    EMA 云带。55/89 为斐波那契对, 由用户的指标导出数据反推确认
    (Plot 列与 EMA55 误差 0.0002, Plot.1 与 EMA89 误差 0.002)。

    返回: fast, slow, cloud_lo, cloud_hi, bull (fast>slow)
    """
    f, s = ema(close, fast), ema(close, slow)
    out = pd.DataFrame(
        {
            "fast": f,
            "slow": s,
            "cloud_lo": pd.concat([f, s], axis=1).min(axis=1),
            "cloud_hi": pd.concat([f, s], axis=1).max(axis=1),
        }
    )
    out["bull"] = out["fast"] > out["slow"]
    return out


def pivots(series: pd.Series, order: int = 12, kind: str = "high") -> np.ndarray:
    """
    摆动高/低点: 左右各 order 根 bar 内的极值点, 返回整数位置数组。

    order 的选择: 12 根 30min bar ≈ 6 个交易小时, 过滤了 bar 级噪声,
    又保留了日内波段结构 (在 SOXX 数据上与手绘通道的触点吻合)。
    """
    v = series.values
    idx = []
    for i in range(order, len(v) - order):
        window = v[i - order : i + order + 1]
        if (kind == "high" and v[i] == window.max()) or (kind == "low" and v[i] == window.min()):
            idx.append(i)
    return np.array(idx, dtype=int)


def linreg_channel(close: pd.Series, window: int = 60, k: float = 2.0) -> pd.DataFrame:
    """
    滚动回归通道 (稳健版): 中线 = 最小二乘回归, 上下轨 = 中线 ± k×残差σ。

    与 channel.py 的枢轴通道互补: 回归通道每根 bar 都有定义、无拟合失败,
    适合监控面板批量计算; 枢轴通道更贴近交易者手绘, 适合精细分析。
    返回: mid, upper, lower, pos (价格在通道中的位置 0~100)
    """
    n = len(close)
    mid = pd.Series(np.nan, index=close.index)
    sd = pd.Series(np.nan, index=close.index)
    x = np.arange(window)
    mx = x.mean()
    sxx = ((x - mx) ** 2).sum()
    vals = close.values
    for i in range(window - 1, n):
        y = vals[i - window + 1 : i + 1]
        m = ((x - mx) * (y - y.mean())).sum() / sxx
        b0 = y.mean() - m * mx
        resid = y - (m * x + b0)
        mid.iloc[i] = m * (window - 1) + b0
        sd.iloc[i] = resid.std()
    slope = mid.diff()
    out = pd.DataFrame(
        {
            "mid": mid,
            "upper": mid + k * sd,
            "lower": mid - k * sd,
            "slope": slope,
        }
    )
    out["pos"] = ((close - out["lower"]) / (out["upper"] - out["lower"]) * 100).clip(0, 100)
    return out
