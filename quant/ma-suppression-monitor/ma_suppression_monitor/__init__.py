"""
ma_suppression_monitor — 均线压制与趋势通道监控系统

模块地图 (对应分析文档的四个模块 + 双引擎):
  bars.py        数据加载与规范化
  indicators.py  EMA 云带 / ATR / 枢轴点 / 回归通道
  regime.py      模块一: 趋势状态机 + 云带几何量 (ATR 归一化)
  channel.py     模块二: 枢轴通道 (包含性 + 最大触碰拟合)
  suppression.py 模块三: 压制三阶段状态机 (预判/监控/确认)
  bottom.py      模块四: 底部形态评分 (含崩盘过滤器)
  engine.py      双引擎编排: 做空引擎 × 底部评分调制
  backtest.py    无未来函数回测工具 (下一根 bar 开盘执行)
"""

from .backtest import baseline, forward_returns, portfolio_sim, score_events, signal_pairs
from .bars import load_csv, resample_bars, validate
from .bottom import BottomConfig, bottom_score
from .channel import Channel, fit_channel
from .engine import DualEngine, EngineConfig
from .indicators import atr, ema, ema_cloud, linreg_channel, pivots
from .regime import cloud_metrics, trend_regime
from .suppression import SuppressionConfig, SuppressionEvent, run_suppression_engine

__all__ = [
    "BottomConfig",
    "Channel",
    "DualEngine",
    "EngineConfig",
    "SuppressionConfig",
    "SuppressionEvent",
    "atr",
    "baseline",
    "bottom_score",
    "cloud_metrics",
    "ema",
    "ema_cloud",
    "fit_channel",
    "forward_returns",
    "linreg_channel",
    "load_csv",
    "pivots",
    "portfolio_sim",
    "resample_bars",
    "run_suppression_engine",
    "score_events",
    "signal_pairs",
    "trend_regime",
    "validate",
]

__version__ = "0.1.0"
