"""
regime.py — 趋势状态机 (模块一)

最简形式的双状态机: BULL (EMA55>EMA89) / BEAR (EMA55<EMA89)。
cross_age 记录距上一次金叉/死叉的 bar 数 —— 新交叉是独立的警报事件,
老交叉则进入"趋势延续"的监控逻辑。

设计说明: 状态只有两种是刻意的。纠缠区 (两线贴近) 不加第三态,
因为云带宽度 (cloud width, ATR) 已经作为一个连续变量输出了同样的信息,
离散状态保持二元可以让下游规则 (压制/底部) 的条件写得干净。
"""

from __future__ import annotations

import pandas as pd


def trend_regime(cloud: pd.DataFrame) -> pd.DataFrame:
    """输入 ema_cloud 输出, 追加 regime 与 cross_age 两列。"""
    bull = cloud["bull"]
    cross = bull.ne(bull.shift(1))
    out = cloud.copy()
    out["regime"] = bull.map({True: "BULL", False: "BEAR"})
    # bars since last cross
    age = pd.Series(0, index=cloud.index, dtype=int)
    last_cross = -(10**9)
    cross_idx = [i for i, c in enumerate(cross.values) if c]
    ci = 0
    for i in range(len(age)):
        if ci < len(cross_idx) and i == cross_idx[ci]:
            last_cross = i
            ci += 1
        age.iloc[i] = i - last_cross if last_cross >= 0 else i + 1
    out["cross_age"] = age
    return out


def cloud_metrics(bars: pd.DataFrame, cloud: pd.DataFrame, atr_: pd.Series) -> pd.DataFrame:
    """
    云带几何量 (全部 ATR 归一化):
      cloud_dist : 价格到云带的有符号距离 (云内=0, 云上正, 云下负)
      cloud_width: 云带开口宽度
      slope_slow : 慢线 26 根斜率 (底部模块的"均线走平度"原料)
    """
    px = bars["close"]
    dist = pd.Series(0.0, index=bars.index)
    above = px > cloud["cloud_hi"]
    below = px < cloud["cloud_lo"]
    dist[above] = (px[above] - cloud["cloud_hi"][above]) / atr_[above]
    dist[below] = (px[below] - cloud["cloud_lo"][below]) / atr_[below]
    out = pd.DataFrame(
        {
            "cloud_dist": dist,
            "cloud_width": (cloud["cloud_hi"] - cloud["cloud_lo"]) / atr_,
            "slope_slow": (cloud["slow"] - cloud["slow"].shift(26)) / atr_,
        }
    )
    return out
