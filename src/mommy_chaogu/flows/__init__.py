"""资金流监控 + 缓存。

设计：
- 复用现有 CachedMarketDataAdapter（节流 + 缓存已经写好）
- 加 PoolSource 抽象：把「拉哪几只」从「怎么拉」里解耦
  - WatchlistPool：从 data/watchlist.db 自选股池拿 codes
  - SemiconPool：从 data/semicon.db 半导体产业链拿 codes
  - CustomPool：CLI --codes 传入
- FlowService 高层 API：pull / top / show / stats

不重新发明缓存层，不重复 schema。
"""
from __future__ import annotations

from mommy_chaogu.flows.pool import (
    CustomPool,
    PoolSource,
    SemiconPool,
    WatchlistPool,
)
from mommy_chaogu.flows.service import (
    FlowService,
    FlowSummary,
    PullResult,
)

__all__ = [
    "CustomPool",
    "FlowService",
    "FlowSummary",
    "PoolSource",
    "PullResult",
    "SemiconPool",
    "WatchlistPool",
]
