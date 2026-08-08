"""
backtest.py — 无未来函数的回测工具

执行惯例 (全库统一, 与用户约定一致):
  信号在 bar t 收盘确认 → 成交价为 bar t+1 的 **开盘价**,
  前向收益从该开盘价起算。跨 bar 跳空用旧仓位计价 (见 portfolio_sim)。

提供三类评估:
  1. forward_returns : 事件集的前向收益分布 (vs 无条件基准)
  2. signal_pairs    : B→S 成对交易 (用户 B/S 信号的评估方法)
  3. score_events    : 阈值穿越事件生成 (带上穿/下穿双阈值, 一次偏移只出一枪)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def forward_returns(bars: pd.DataFrame, event_idx: list[int], horizons: list[int]) -> pd.DataFrame:
    """事件前向收益: 从 t+1 开盘到 t+1+h 收盘 (百分比)。"""
    o = np.log(bars["open"].values)
    c = np.log(bars["close"].values)
    rows = []
    for t in event_idx:
        if t + 1 >= len(bars):
            continue
        entry = o[t + 1]
        row = {"time": bars.index[t]}
        for h in horizons:
            row[f"r{h}"] = (c[t + 1 + h] - entry) * 100 if t + 1 + h < len(bars) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def baseline(bars: pd.DataFrame, horizons: list[int], step: int = 7) -> dict:
    """无条件基准: 每隔 step 根取样一次的前向收益均值。"""
    idx = list(range(0, len(bars) - max(horizons) - 2, step))
    fr = forward_returns(bars, idx, horizons)
    return {h: fr[f"r{h}"].mean() for h in horizons}


def score_events(score: pd.Series, on: float = 65, off: float = 35) -> list[int]:
    """评分上穿 on 触发, 下穿 off 重置 (一次偏移只出一枪)。"""
    events, state = [], 0
    v = score.values
    for i, s in enumerate(v):
        if state == 0 and s > on:
            events.append(i)
            state = 1
        elif state == 1 and s < off:
            state = 0
    return events


def signal_pairs(bars: pd.DataFrame, buy_flags: pd.Series, sell_flags: pd.Series) -> pd.DataFrame:
    """
    B→S 成对交易: B 出现 → 下一根开盘买入; 之后第一个 S → 下一根开盘卖出。
    连续 B 不重复加仓。
    """
    b_idx = np.where(buy_flags.values)[0]
    s_idx = np.where(sell_flags.values)[0]
    events = sorted([(i, "B") for i in b_idx] + [(i, "S") for i in s_idx])
    trades, pos = [], None
    for t, kind in events:
        if kind == "B" and pos is None and t + 1 < len(bars):
            pos = t
        elif kind == "S" and pos is not None and t + 1 < len(bars):
            ret = bars["open"].iloc[t + 1] / bars["open"].iloc[pos + 1] - 1
            trades.append(
                {
                    "entry_t": bars.index[pos + 1],
                    "exit_t": bars.index[t + 1],
                    "ret": ret,
                    "bars_held": t - pos,
                }
            )
            pos = None
    return pd.DataFrame(trades)


def portfolio_sim(bars: pd.DataFrame, target_pos: pd.Series) -> pd.Series:
    """
    逐 bar 组合模拟 (log 收益序列):
      仓位变化在信号 bar 的下一根 bar 开盘生效;
      跨 bar 跳空用旧仓位, bar 内用新仓位 —— 严格模拟实盘执行顺序。
    target_pos: 每根 bar 收盘时的目标仓位 (-1/0/1)。
    """
    lo = np.log(bars["open"].values)
    lc = np.log(bars["close"].values)
    gap = lo - np.roll(lc, 1)
    gap[0] = 0.0
    intra = lc - lo
    s = target_pos.values.astype(float)
    s_prev1 = np.roll(s, 1)
    s_prev2 = np.roll(s, 2)
    s_prev1[0] = s_prev2[0] = s_prev2[1] = 0.0
    port = s_prev2 * gap + s_prev1 * intra
    return pd.Series(port, index=bars.index, name="strategy_logret")
