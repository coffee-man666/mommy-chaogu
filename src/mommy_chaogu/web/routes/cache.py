"""/api/cache 路由：缓存统计。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from mommy_chaogu.cache import CachedMarketDataAdapter
from mommy_chaogu.web.deps import get_adapter
from mommy_chaogu.web.schemas import CacheStatsOut

router = APIRouter(prefix="/api/cache", tags=["cache"])


@router.get("/stats", response_model=CacheStatsOut)
def cache_stats(
    adapter: Annotated[CachedMarketDataAdapter, Depends(get_adapter)],
) -> CacheStatsOut:
    """缓存命中率 + 数据新鲜度。"""
    stats = adapter.stats_counters
    freshness = adapter.data_freshness_report()
    hits = int(stats.get("hits", 0))
    fetches = int(stats.get("fetches", 0))
    miss = int(stats.get("miss", 0))
    total = hits + miss
    hit_rate = (hits / total) if total > 0 else 0.0
    return CacheStatsOut(
        hits=hits,
        fetches=fetches,
        fetch_ok=int(stats.get("fetch_ok", 0)),
        fetch_fail=int(stats.get("fetch_fail", 0)),
        miss=miss,
        hit_rate=round(hit_rate, 4),
        freshness=freshness,
    )
