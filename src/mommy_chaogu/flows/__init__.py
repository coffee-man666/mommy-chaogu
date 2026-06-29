"""资金流监控 + 缓存。

设计：
- 复用现有 CachedMarketDataAdapter（节流 + 缓存已经写好）
- 加 PoolSource 抽象：把「拉哪几只」从「怎么拉」里解耦
  - WatchlistPool：从 data/watchlist.db 自选股池拿 codes
  - SemiconPool：从 data/semicon.db 半导体产业链拿 codes
  - CustomPool：CLI --codes 传入
- FlowService 高层 API：pull / top / show / stats
- FlowMonitor：持续轮询 + ratio-based 异动检测
- FlowReport：收盘日报（markdown）
"""
from __future__ import annotations

from mommy_chaogu.flows.monitor import FlowMonitor, TickResult
from mommy_chaogu.flows.pool import (
    CustomPool,
    PoolSource,
    SemiconPool,
    WatchlistPool,
)
from mommy_chaogu.flows.report import FlowReport
from mommy_chaogu.flows.service import (
    FlowService,
    FlowSummary,
    PullResult,
)
from mommy_chaogu.flows.signals import (
    FlowRule,
    FlowSignal,
    Severity,
    StockSnapshot,
    default_rules,
    evaluate,
)

__all__ = [
    "CustomPool",
    "FlowMonitor",
    "FlowReport",
    "FlowRule",
    "FlowService",
    "FlowSignal",
    "FlowSummary",
    "PoolSource",
    "PullResult",
    "SemiconPool",
    "Severity",
    "StockSnapshot",
    "TickResult",
    "WatchlistPool",
    "default_rules",
    "evaluate",
]
