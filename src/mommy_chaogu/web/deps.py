"""依赖注入：FastAPI Depends() 全局单例。

设计：
- Adapter / Store / Alerter / Cache 全部 lazy-init 单例
- 测试时用 app.dependency_overrides 替换
- 不在 import 时拉网络（fail-fast 但不起连接）
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
from mommy_chaogu.market_data import (
    EfinanceAdapter,
    FallbackAdapter,
    MarketDataAdapter,
    TencentAdapter,
)
from mommy_chaogu.portfolio import PortfolioStore
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import WatchlistStore


@lru_cache(maxsize=1)
def get_db_path() -> Path:
    """全局 DB 路径（默认 data/watchlist.db）。"""
    return Path("data/watchlist.db")


@lru_cache(maxsize=1)
def get_adapter() -> MarketDataAdapter:
    """全局数据源装饰器链：CachedMarketDataAdapter(Fallback([Efinance, Tencent]))。

    走项目核心设计（DESIGN §2 P2/P3/P4）：
    - Fallback：主源挂 → 备源
    - Cache：DB 有就用，没有才拉新，失败 fallback 旧数据
    """
    adapter = CachedMarketDataAdapter(
        FallbackAdapter([EfinanceAdapter(), TencentAdapter()]),
        CacheStore(get_db_path()),
    )
    return adapter


@lru_cache(maxsize=1)
def get_watchlist_store() -> WatchlistStore:
    """全局自选池存储。"""
    return WatchlistStore(get_db_path())


@lru_cache(maxsize=1)
def get_alerter() -> Alerter:
    """全局告警器。"""
    from pathlib import Path

    log_path = Path("data/signals.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return Alerter.default(log_path=log_path)


@lru_cache(maxsize=1)
def get_portfolio_store() -> PortfolioStore:
    """全局持仓存储。"""
    return PortfolioStore(get_db_path())
