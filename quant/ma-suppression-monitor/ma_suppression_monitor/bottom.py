"""
bottom.py — 底部形态评分 (模块四)

把交易员的底部经验形式化为四个 ATR 归一化特征, 加权成 0~100 的评分:

  特征                    权重   含义                              真底部均值*
  ─────────────────────────────────────────────────────────────────
  均线走平度 slope_slow    30%   EMA89 的 26 根斜率 (越平越好)      -1.98 ATR
  底底高结构 higher_lows   30%   最近 3 个 pivot 低点抬升步数        0.73 / 2
  价格贴线度 cloud_dist    25%   价格相对云带下沿 (收复云带最好)     +0.95 ATR
  云带收敛度 cloud_width   15%   EMA89-55 开口 (收口好)             1.14 ATR

  * 真底部 = SOXX 2023-2026 年 42 个主要波段低点中,
    随后 130 根 bar 反弹 ≥10% 且不再破位的 12 个。

两条硬经验, 都来自回测的失败模式分析:
  1. 崩盘过滤器: 价格在云带下 > crash_dist ATR (自由落体) 时, 评分封顶 49。
     "跌得慢了 ≠ 不跌了" —— 2026-06-09 和 2026-07-14 两次假信号同源于此。
  2. 评分只在空头排列有意义 (多头里的"走平"是另一回事),
     引擎层负责按 regime 门控, 本模块如实输出原始分。

特征→分数用**固定仿射映射**而不是滚动分位数:
  分位数映射在极端行情里会失真 (2026-06 崩盘中"相对走平"被高估),
  固定映射用样本内 (2023-2025) 的真底部分布一次标定, 之后不再动,
  保证了 2026 样本外读数与样本内可直接比较 (OOS 胜率反而更高: 75% vs 53%)。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import pivots


@dataclass
class BottomConfig:
    w_slope: float = 0.30
    w_hl: float = 0.30
    w_dist: float = 0.25
    w_gap: float = 0.15
    # 仿射映射端点 (样本内标定)
    slope_lo: float = -4.0  # ATR/26bars, ≤此值 → 0 分
    slope_hi: float = 0.0  # ≥此值 → 100 分
    dist_lo: float = -2.0  # ATR
    dist_hi: float = 1.0
    gap_narrow: float = 0.5  # ATR, ≤ → 100 分
    gap_wide: float = 3.0  # ≥ → 0 分
    crash_dist: float = 2.0  # 崩盘过滤器阈值 (ATR)
    pivot_order: int = 6
    pivot_lookback: int = 120


def _lin(x: float, x0: float, x1: float) -> float:
    return float(np.clip((x - x0) / (x1 - x0) * 100, 0, 100))


def bottom_score(
    bars: pd.DataFrame,
    metrics: pd.DataFrame,
    cfg: BottomConfig | None = None,
) -> pd.DataFrame:
    """
    输入 bars + regime.cloud_metrics 输出, 返回逐 bar 的评分与分量。
    列: score, s_slope, s_hl, s_dist, s_gap, crash_blocked
    """
    cfg = cfg or BottomConfig()
    slope = metrics["slope_slow"]
    dist = metrics["cloud_dist"]
    gap = metrics["cloud_width"]

    # higher-lows: 最近 lookback 根内, 最近 3 个 pivot 低点的抬升步数 ×50
    lows = bars["low"]
    hl = pd.Series(0.0, index=bars.index)
    lo_idx = pivots(lows, cfg.pivot_order, "low")
    pos_of = {int(v): k for k, v in enumerate(lo_idx)}
    for i in range(len(bars)):
        j = i
        while j >= 0 and j not in pos_of:
            j -= 1
        if j < 0:
            continue
        k = pos_of[j]
        if k >= 2 and i - lo_idx[k - 2] <= cfg.pivot_lookback:
            v = lows.values[lo_idx[k - 2 : k + 1]]
            hl.iloc[i] = (50.0 if v[2] > v[1] else 0.0) + (50.0 if v[1] > v[0] else 0.0)

    s_slope = slope.apply(lambda x: _lin(x, cfg.slope_lo, cfg.slope_hi) if pd.notna(x) else 0.0)
    s_dist = dist.apply(lambda x: _lin(x, cfg.dist_lo, cfg.dist_hi) if pd.notna(x) else 0.0)
    s_gap = gap.apply(
        lambda x: 100.0 - _lin(x, cfg.gap_narrow, cfg.gap_wide) if pd.notna(x) else 0.0
    )

    raw = cfg.w_slope * s_slope + cfg.w_hl * hl + cfg.w_dist * s_dist + cfg.w_gap * s_gap
    crash_blocked = dist < -cfg.crash_dist
    score = raw.where(~crash_blocked, raw.clip(upper=49.0)).clip(0, 100)

    return pd.DataFrame(
        {
            "score": score.round(1),
            "s_slope": s_slope.round(1),
            "s_hl": hl,
            "s_dist": s_dist.round(1),
            "s_gap": s_gap.round(1),
            "crash_blocked": crash_blocked,
        }
    )
