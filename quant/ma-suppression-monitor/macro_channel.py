"""
macro_channel.py — 大尺度通道识别（4h/日线级别）

设计思路：
  1. 用较大尺度（4小时线）减少噪音
  2. 找到回撤前的 high（趋势顶点）
  3. 沿高点画线 → 上轨
  4. 平行投影到最深低点 → 下轨
  5. 不依赖 order 参数，直接找"显而易见"的极值点

与 channel.py 的区别：
  - channel.py: 枚举枢轴对 + 包含性约束，参数敏感，换周期结果变
  - macro_channel: 先找最大回撤段，再连接段内的高点高点，更接近人眼

不修改原 channel.py，完全独立。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MacroChannel:
    slope: float  # $/bar
    upper_int: float  # 上轨截距
    lower_int: float  # 下轨截距
    anchor_idx: int  # 锚点 bar 序号
    anchor_price: float  # 锚点价格
    peak_idx: int  # 最高点 bar 序号
    peak_price: float
    trough_idx: int  # 最低点 bar 序号
    trough_price: float
    upper_touches: list  # 上轨触碰点的 bar 序号列表
    lower_touches: list  # 下轨触碰点的 bar 序号列表
    n_bars: int  # 通道覆盖的 bar 数
    ok: bool


def find_drawdown_segment(bars: pd.DataFrame, min_decline_pct: float = 0.08) -> tuple[int, int]:
    """
    找最大回撤段：从某个高点到之后的最低点，跌幅 ≥ min_decline_pct。
    返回 (peak_idx, trough_idx)。
    """
    high = bars["high"].values
    low = bars["low"].values
    n = len(bars)

    best_peak = 0
    best_trough = 0
    best_dd = 0.0

    running_peak = 0
    for i in range(1, n):
        if high[i] >= high[running_peak]:
            running_peak = i
        else:
            dd = (low[i] - high[running_peak]) / high[running_peak]
            if dd < best_dd:
                best_dd = dd
                best_peak = running_peak
                best_trough = i

    if best_peak == best_trough:
        # fallback: just use global max → global min after it
        best_peak = int(np.argmax(high))
        best_trough = best_peak + int(np.argmin(low[best_peak:]))

    return best_peak, best_trough


def fit_macro_channel(
    bars: pd.DataFrame,
    touch_tol_atr: float = 0.3,
    touch_tol_pct: float = 0.004,
) -> MacroChannel:
    """
    大尺度通道拟合：
      1. 找回撤段 [peak → trough]
      2. 上轨 = 连接 peak 和 trough 之后所有反弹高点中"最好的那条线"
         "最好" = 包含所有高点（容差 touch_tol_pct）、触点最多
      3. 下轨 = 平行，过 trough
      4. 通道延伸到最新 bar

    与 channel.py 的 fit_channel 完全独立。
    """
    high = bars["high"].values
    low = bars["low"].values
    n = len(bars)

    if n < 10:
        return MacroChannel(0, 0, 0, 0, 0, 0, 0, 0, 0, [], [], n, False)

    # 1. 找回撤段
    peak_idx, trough_idx = find_drawdown_segment(bars)
    peak_price = high[peak_idx]
    trough_price = low[trough_idx]

    # 2. 找 peak 之后的所有反弹高点（候选用来连上轨）
    # 一个"反弹高点" = 局部最大值（左右各 2 根 bar 内最高）
    candidate_highs = []
    window = 2  # 简单局部极值
    for i in range(peak_idx + 1, n):
        left = max(0, i - window)
        right = min(n, i + window + 1)
        if high[i] == high[left:right].max() and high[i] < peak_price:
            candidate_highs.append(i)

    # 候选：peak 本身 + 每个反弹高点 → 枚举所有两点组合
    all_anchor_points = [(peak_idx, peak_price)] + [(i, high[i]) for i in candidate_highs]

    best = None  # (touches, slope, intercept)
    for a in range(len(all_anchor_points)):
        for c in range(a + 1, len(all_anchor_points)):
            x1, y1 = all_anchor_points[a]
            x2, y2 = all_anchor_points[c]
            if x2 == x1:
                continue
            m = (y2 - y1) / (x2 - x1)
            if m >= 0:  # 下降通道要求负斜率
                continue

            b0 = y1 - m * x1
            line = m * np.arange(n) + b0

            # 包含性检查：peak 之后所有 high 不能超过 line*(1+tol)
            violated = False
            for i in range(peak_idx, n):
                if high[i] > line[i] * (1 + touch_tol_pct):
                    violated = True
                    break
            if violated:
                continue

            # 数触点：peak 之后 high 接近 line 的 bar
            touches = []
            for i in range(peak_idx, n):
                if abs(high[i] - line[i]) / max(abs(line[i]), 1e-9) < touch_tol_pct:
                    touches.append(i)

            if best is None or len(touches) > len(best[0]):
                best = (touches, m, b0)

    if best is None:
        # fallback: peak → trough 之后的最高反弹点
        if candidate_highs:
            second = candidate_highs[0]
            m = (high[second] - peak_price) / (second - peak_idx)
            if m >= 0:
                m = -0.5  # 强制负斜率
            b0 = peak_price - m * peak_idx
            line = m * np.arange(n) + b0
            touches = [
                i
                for i in range(peak_idx, n)
                if abs(high[i] - line[i]) / max(abs(line[i]), 1e-9) < touch_tol_pct
            ]
            best = (touches, m, b0)
        else:
            return MacroChannel(
                0,
                0,
                0,
                peak_idx,
                peak_price,
                peak_idx,
                peak_price,
                trough_idx,
                trough_price,
                [],
                [],
                n,
                False,
            )

    upper_touches, slope, upper_int = best

    # 3. 下轨 = 平行过 trough
    lower_int = trough_price - slope * trough_idx

    # 4. 下轨触点
    lower_line = slope * np.arange(n) + lower_int
    lower_touches = []
    for i in range(trough_idx, n):
        if abs(low[i] - lower_line[i]) / max(abs(lower_line[i]), 1e-9) < touch_tol_pct:
            lower_touches.append(i)

    return MacroChannel(
        slope=slope,
        upper_int=upper_int,
        lower_int=lower_int,
        anchor_idx=peak_idx,
        anchor_price=peak_price,
        peak_idx=peak_idx,
        peak_price=peak_price,
        trough_idx=trough_idx,
        trough_price=trough_price,
        upper_touches=upper_touches,
        lower_touches=lower_touches,
        n_bars=n,
        ok=True,
    )


def channel_report(ch: MacroChannel, bars: pd.DataFrame, label: str = "") -> str:
    """生成通道文字报告"""
    if not ch.ok:
        return f"[{label}] NO CHANNEL FITTED"

    n = len(bars)
    upper_now = ch.slope * (n - 1) + ch.upper_int
    lower_now = ch.slope * (n - 1) + ch.lower_int
    last_close = bars["close"].iloc[-1]
    pos = (last_close - lower_now) / (upper_now - lower_now) * 100

    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"Macro Channel — {label}")
    lines.append(f"{'=' * 60}")
    lines.append(f"Peak:   {bars.index[ch.peak_idx]}  ${ch.peak_price:.1f}")
    lines.append(f"Trough: {bars.index[ch.trough_idx]}  ${ch.trough_price:.1f}")
    lines.append(f"Drawdown: {(ch.trough_price / ch.peak_price - 1) * 100:+.1f}%")
    lines.append(f"Slope: {ch.slope:.5f}/bar")
    lines.append("")
    lines.append(f"Upper rail NOW: ${upper_now:.1f}")
    lines.append(f"Lower rail NOW: ${lower_now:.1f}")
    lines.append(f"Close:          ${last_close:.1f}")
    lines.append(f"Position:       {pos:.0f}%")
    lines.append(
        f"Dist to upper:  ${upper_now - last_close:.1f} ({(upper_now - last_close) / last_close * 100:+.2f}%)"
    )
    lines.append(
        f"Dist to lower:  ${last_close - lower_now:.1f} ({(lower_now - last_close) / last_close * 100:+.2f}%)"
    )
    lines.append("")
    lines.append(f"Upper touches: {len(ch.upper_touches)} bars")
    for t in ch.upper_touches:
        broke = bars["close"].iloc[t] > ch.slope * t + ch.upper_int
        lines.append(
            f"  {bars.index[t]}  H=${bars['high'].iloc[t]:.1f}  C=${bars['close'].iloc[t]:.1f}  {'✅' if broke else '—'}"
        )
    lines.append(f"Lower touches: {len(ch.lower_touches)} bars")

    return "\n".join(lines)
