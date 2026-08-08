"""
suppression.py — 均线压制三阶段状态机 (模块三)

核心思想: 把 "一个信号" 拆成 "一台状态机"。
预判 (ARMED) / 监控 (ENGAGED) / 确认 (CONFIRMED) 各用各的阈值 ——
信号不稳定的最常见原因, 是进场和出场用了同一个判据,
价格在边界附近反复穿越时信号疯狂闪烁。

状态转移 (做空向, 多头向完全对称):

    IDLE    --空头排列 且 价格逼近云带(≤arm_dist ATR)--> ARMED
    ARMED   --探入触发区间 且 深度≥min_depth ATR-------> ENGAGED
    ARMED   --收盘站上云带上沿+失效缓冲----------------> IDLE   (预判失效)
    ENGAGED --收盘跌回云带下沿之下---------------------> CONFIRMED (发信号)
    ENGAGED --收盘站上云带上沿-------------------------> IDLE   (压制失败)
    CONFIRMED--价格离开云带>cooldown_dist ATR----------> ARMED  (重新武装, 计数+1)

防闪烁三件套:
  1. 滞后缓冲 (hysteresis): 进入区间 ≠ 退出区间, 缓冲带 0.3 ATR;
  2. 一次反弹只出一枪: 确认后进入冷却, 重置条件是看价离开云带而非再次触碰;
  3. 压制计数: 同一趋势段内第 N 次压制单独打标, 供回测分组 (事不过三)。

执行惯例 (与全库一致): 信号在 bar 收盘确认, 成交价为 **下一根 bar 的开盘价**。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class SuppressionConfig:
    arm_dist: float = 1.5  # 预判: 距云带下沿 ≤ 1.5 ATR 时武装
    buffer: float = 0.3  # 滞后缓冲 (ATR)
    min_depth: float = 0.2  # 有效探入的最小深度 (ATR)
    cooldown_dist: float = 1.0  # 冷却重置距离 (ATR)
    channel_pos_min: float = 50  # 预判要求通道位置 ≥ 50% (反弹性质)


@dataclass
class SuppressionEvent:
    t_armed: pd.Timestamp
    t_engaged: pd.Timestamp
    t_confirmed: pd.Timestamp
    confirm_close: float
    depth_atr: float  # 探入云带的最深幅度
    dwell_bars: int  # 在触发区间内停留的 bar 数
    count: int  # 本趋势段内第几次压制


@dataclass
class SuppressionResult:
    events: list[SuppressionEvent] = field(default_factory=list)
    states: pd.Series | None = None  # 每根 bar 的状态, 供可视化
    failures: int = 0  # 压制失败 (突破云带) 次数


def run_suppression_engine(
    bars: pd.DataFrame,
    regime: pd.DataFrame,
    atr_: pd.Series,
    cfg: SuppressionConfig | None = None,
    channel_pos: pd.Series | None = None,
) -> SuppressionResult:
    """
    做空向压制状态机。需要 regime (含 bull/cross_age) 与 ATR。
    channel_pos 可选: 若提供, 预判阶段要求价格在通道上半部。
    """
    cfg = cfg or SuppressionConfig()
    close, high = bars["close"], bars["high"]
    c_lo, c_hi = regime["cloud_lo"], regime["cloud_hi"]
    bull = regime["bull"].values

    state = "IDLE"
    count = 0
    res = SuppressionResult()
    states = []
    t_armed = t_engaged = None
    max_depth = 0.0
    dwell = 0
    prev_regime_bull = bull[0]

    for i in range(len(bars)):
        a = atr_.iloc[i]
        if not np_isfinite(a) or a <= 0:
            states.append(state)
            continue
        # 趋势段切换 → 重置计数与状态
        if bull[i] != prev_regime_bull:
            count = 0
            state = "IDLE"
            prev_regime_bull = bull[i]
        if bull[i]:  # 做空引擎只在空头排列工作
            states.append(state)
            continue

        zone_lo = c_lo.iloc[i] - cfg.buffer * a  # 触发区间下沿 (含滞后缓冲)
        zone_hi = c_hi.iloc[i]
        near = close.iloc[i] >= c_lo.iloc[i] - cfg.arm_dist * a

        if state == "IDLE":
            pos_ok = True if channel_pos is None else channel_pos.iloc[i] >= cfg.channel_pos_min
            if near and close.iloc[i] < c_lo.iloc[i] and pos_ok:
                state = "ARMED"
                t_armed = bars.index[i]
                max_depth, dwell = 0.0, 0
        elif state == "ARMED":
            if close.iloc[i] > zone_hi + cfg.buffer * a:  # 失效: 站上云带
                state = "IDLE"
            elif high.iloc[i] >= zone_lo:
                depth = (min(high.iloc[i], zone_hi) - zone_lo) / a
                if depth >= cfg.min_depth:
                    state = "ENGAGED"
                    t_engaged = bars.index[i]
                    max_depth, dwell = max(max_depth, depth), 1
        elif state == "ENGAGED":
            if high.iloc[i] >= zone_lo:
                dwell += 1
                max_depth = max(max_depth, (min(high.iloc[i], zone_hi) - zone_lo) / a)
            if close.iloc[i] > zone_hi:  # 压制失败
                res.failures += 1
                state = "IDLE"
            elif close.iloc[i] < c_lo.iloc[i]:  # 确认: 跌回云下
                count += 1
                res.events.append(
                    SuppressionEvent(
                        t_armed=t_armed,
                        t_engaged=t_engaged,
                        t_confirmed=bars.index[i],
                        confirm_close=float(close.iloc[i]),
                        depth_atr=float(max_depth),
                        dwell_bars=dwell,
                        count=count,
                    )
                )
                state = "COOLDOWN"
        elif state == "COOLDOWN":
            if abs(close.iloc[i] - c_lo.iloc[i]) > cfg.cooldown_dist * a:
                state = "ARMED" if close.iloc[i] < c_lo.iloc[i] else "IDLE"
                t_armed = bars.index[i]
                max_depth, dwell = 0.0, 0
        states.append(state)

    res.states = pd.Series(states, index=bars.index, name="suppression_state")
    return res


def np_isfinite(x: float) -> bool:
    return x == x and abs(x) != float("inf")
