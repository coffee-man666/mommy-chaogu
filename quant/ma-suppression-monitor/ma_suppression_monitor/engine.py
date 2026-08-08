"""
engine.py — 双引擎架构 (编排层)

做空引擎 (suppression.py) 与底部评分 (bottom.py) 不是两个并列信号,
而是调制关系: 底部评分回答 "下跌趋势是不是快完了",
它降权/挂起做空引擎, 并在指标沉默期 (死叉后~金叉前) 预武装做多侧。

    底部评分 < 25  : 做空引擎正常工作
    25 ~ 50        : S 信号降仓 (半仓), 确认判据收紧
    > 50           : 做空引擎挂起 (不开新空), BOTTOM_WATCH 点亮
    BOTTOM_WATCH 中, 价格收复云带 + 金叉 → LONG_ARMED (做多预武装)
    BOTTOM_WATCH 中, 跌破最近 pivot 低点 → 底部证伪, 评分作废

Alert 优先级 (单一口径输出, 面板直接可读):
    CROSS (金叉/死叉, 3 bar 内) > RALLY_FADE (压制确认区) >
    BOTTOM_WATCH (评分≥65) > TREND_LONG / FREE_FALL > —
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .bottom import BottomConfig, bottom_score
from .channel import Channel, fit_channel
from .indicators import atr, ema_cloud, linreg_channel
from .regime import cloud_metrics, trend_regime
from .suppression import SuppressionConfig, run_suppression_engine


@dataclass
class EngineConfig:
    ema_fast: int = 55
    ema_slow: int = 89
    atr_n: int = 14
    chan_window: int = 60
    bottom_watch: float = 65.0
    bottom_caution: float = 50.0
    rally_fade_pos: float = 75.0
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    bottom: BottomConfig = field(default_factory=BottomConfig)


class DualEngine:
    """一次性计算全部模块, 输出逐 bar 的监控帧 + 当前读数。"""

    def __init__(self, cfg: EngineConfig | None = None):
        self.cfg = cfg or EngineConfig()

    def run(self, bars: pd.DataFrame) -> pd.DataFrame:
        c = self.cfg
        cloud = ema_cloud(bars["close"], c.ema_fast, c.ema_slow)
        regime = trend_regime(cloud)
        atr_ = atr(bars, c.atr_n)
        metrics = cloud_metrics(bars, regime, atr_)
        chan = linreg_channel(bars["close"], c.chan_window)
        bscore = bottom_score(bars, metrics, c.bottom)
        sup = run_suppression_engine(bars, regime, atr_, c.suppression, chan["pos"])

        frame = pd.concat(
            [
                regime[["regime", "cross_age"]],
                metrics,
                chan[["pos", "slope"]].rename(columns={"pos": "chan_pos", "slope": "chan_slope"}),
                bscore,
                sup.states,
            ],
            axis=1,
        )
        frame["tests_26"] = (frame["suppression_state"] == "ENGAGED").rolling(26).sum().fillna(0)
        # 引擎门控
        frame["engine"] = "SHORT_ACTIVE"
        frame.loc[frame["score"] >= c.bottom_caution, "engine"] = "SHORT_REDUCED"
        frame.loc[frame["score"] >= c.bottom_watch, "engine"] = "BOTTOM_WATCH"
        frame.loc[frame["regime"] == "BULL", "engine"] = "LONG_SIDE"

        # 单一口径警报
        alert = pd.Series("—", index=bars.index)
        fade = (
            (frame["regime"] == "BEAR")
            & (frame["chan_pos"] >= c.rally_fade_pos)
            & (frame["tests_26"] > 0)
        )
        alert[fade] = "RALLY_FADE"
        watch = (frame["regime"] == "BEAR") & (frame["score"] >= c.bottom_watch)
        alert[(alert == "—") & watch] = "BOTTOM_WATCH"
        alert[(alert == "—") & (frame["regime"] == "BULL") & (frame["cloud_dist"] > 0)] = (
            "TREND_LONG"
        )
        alert[(alert == "—") & (frame["cloud_dist"] < -1.5)] = "FREE_FALL"
        new_cross = frame["cross_age"] <= 3
        alert[new_cross] = frame["regime"][new_cross].map({"BULL": "GOLDEN_X", "BEAR": "DEATH_X"})
        frame["alert"] = alert

        self.frame_ = frame
        self.suppression_events_ = sup.events
        return frame

    def readout(self, bars: pd.DataFrame, use_pivot_channel: bool = True) -> dict:
        """当前时刻的监控面板读数 (dict)。"""
        frame = self.frame_
        i = len(frame) - 1
        row = frame.iloc[-1]
        out = {
            "time": str(frame.index[-1]),
            "close": float(bars["close"].iloc[-1]),
            "regime": row["regime"],
            "cross_age": int(row["cross_age"]),
            "slope_slow_atr": round(float(row["slope_slow"]), 2),
            "cloud_dist_atr": round(float(row["cloud_dist"]), 2),
            "cloud_width_atr": round(float(row["cloud_width"]), 2),
            "chan_pos": round(float(row["chan_pos"]), 1),
            "bottom_score": float(row["score"]),
            "engine": row["engine"],
            "alert": row["alert"],
            "suppression_events_total": len(self.suppression_events_),
        }
        if use_pivot_channel:
            ch: Channel = fit_channel(bars, direction="down" if row["regime"] == "BEAR" else "up")
            if ch.ok:
                out["pivot_channel"] = {
                    "slope_per_bar": round(ch.slope, 3),
                    "touches": ch.touches,
                    "position": round(ch.position(float(bars["close"].iloc[-1]), i), 1),
                }
        return out
