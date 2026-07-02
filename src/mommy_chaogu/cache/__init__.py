"""cache 包：行情数据本地缓存层。

设计哲学：
- 数据库是唯一真相源，每条记录带 fetched_at 时间戳
- 拉新失败时不抛弃旧数据（妈妈能看见数据新鲜度）
- 拉新有节流，避免对东财接口高频打

提供：
- CacheStore: SQLite-backed CRUD
- CachedMarketDataAdapter: 装饰器，包装任意 MarketDataAdapter
- CacheManager: warmup / stats / clear / refresh
"""

from mommy_chaogu.cache.adapter import CachedMarketDataAdapter
from mommy_chaogu.cache.config import CacheConfig, default_config
from mommy_chaogu.cache.manager import CacheManager
from mommy_chaogu.cache.schema import SCHEMA_SQL
from mommy_chaogu.cache.store import CacheStore, QuoteCacheEntry

__all__ = [
    "SCHEMA_SQL",
    "CacheConfig",
    "CacheManager",
    "CacheStore",
    "CachedMarketDataAdapter",
    "QuoteCacheEntry",
    "default_config",
]
