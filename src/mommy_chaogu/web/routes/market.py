"""/api/market 路由：市场行情扫描 + 大盘指数 + 板块排行。"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from mommy_chaogu.cache import CacheStore
from mommy_chaogu.market_data import MarketDataAdapter
from mommy_chaogu.market_data.rankings import (
    fetch_indexes,
    fetch_sector_ranking,
)
from mommy_chaogu.semicon import SemiconStore
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.deps import (
    get_adapter,
    get_cache_store,
    get_semicon_store,
    get_watchlist_store,
)
from mommy_chaogu.web.schemas import IndexOut, SectorOut, StockSearchOut

router = APIRouter(prefix="/api/market", tags=["market"])
stocks_router = APIRouter(prefix="/api/stocks", tags=["market"])


@stocks_router.get("/search", response_model=list[StockSearchOut])
def search_stocks(
    q: Annotated[str, Query(min_length=1, max_length=64)],
    watchlist: Annotated[WatchlistStore, Depends(get_watchlist_store)],
    cache: Annotated[CacheStore, Depends(get_cache_store)],
    semicon: Annotated[SemiconStore, Depends(get_semicon_store)],
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
) -> list[StockSearchOut]:
    """按名称子串或代码前缀联想股票，优先返回自选股。"""
    needle = q.strip().casefold()
    if not needle:
        return []
    candidates: dict[str, StockSearchOut] = {}
    cached_names: dict[str, str] = {}

    for entry in cache.get_all_quote_entries():
        name = str(getattr(entry.quote, "name", "") or "")
        cached_names[entry.code] = name

    def add(
        code: str,
        name: str,
        source: Literal["watchlist", "semicon", "cache"],
    ) -> None:
        if not code or code in candidates:
            return
        candidates[code] = StockSearchOut(
            code=code, name=name or cached_names.get(code, ""), source=source
        )

    for entry in watchlist.list_entries():
        add(entry.code, entry.name or "", "watchlist")
    for stock in semicon.list_all():
        add(stock.code, stock.name, "semicon")
    for code, name in cached_names.items():
        add(code, name, "cache")

    source_order = {"watchlist": 0, "semicon": 1, "cache": 2}

    def score(item: StockSearchOut) -> tuple[int, int, str]:
        code = item.code.casefold()
        name = item.name.casefold()
        if code == needle or name == needle:
            match_rank = 0
        elif code.startswith(needle):
            match_rank = 1
        elif name.startswith(needle):
            match_rank = 2
        else:
            match_rank = 3
        return match_rank, source_order[item.source], item.code

    matched = [
        item
        for item in candidates.values()
        if item.code.casefold().startswith(needle) or needle in item.name.casefold()
    ]
    return sorted(matched, key=score)[:limit]


@router.get("/indexes", response_model=list[IndexOut])
def get_indexes() -> list[IndexOut]:
    """大盘核心指数（上证/深证/创业板/沪深300/科创50/上证50）。"""
    return [
        IndexOut(
            code=i.code,
            name=i.name,
            price=i.price,
            change_pct=i.change_pct,
            prev_close=i.prev_close,
        )
        for i in fetch_indexes()
    ]


@router.get("/sectors", response_model=list[SectorOut])
def get_sectors(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[SectorOut]:
    """板块涨幅榜（行业 + 概念合并去重）。"""
    items = fetch_sector_ranking(limit=limit)
    return [
        SectorOut(
            code=i["code"],  # type: ignore[arg-type]
            name=i["name"],  # type: ignore[arg-type]
            change_pct=i["change_pct"],  # type: ignore[arg-type]
            price=i.get("price") or Decimal("0"),
        )
        for i in items
    ]


@router.get("/gainers")
def get_gainers(
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, object]]:
    """全市场涨幅榜 TOP N（过滤停牌/ST/退市）。"""
    return _ranking(adapter.list_market_quotes(), top="up", limit=limit)


@router.get("/losers")
def get_losers(
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, object]]:
    """全市场跌幅榜 TOP N。"""
    return _ranking(adapter.list_market_quotes(), top="down", limit=limit)


def _ranking(quotes: list[object], top: str, limit: int) -> list[dict[str, object]]:
    """从全市场 quote 列表筛选 + 排序。"""
    filtered: list[tuple[object, float]] = []
    for q in quotes:
        try:
            name = str(getattr(q, "name", "") or "")
            pct = float(getattr(q, "change_pct", 0) or 0)
            code = str(getattr(q, "code", ""))
            # 过滤 ST / 退市 / 停牌
            if "ST" in name or "退" in name or "N " in name:
                continue
            # 过滤异常值（涨跌幅 > 11% 或 < -11% 大概率是新上市）
            if abs(pct) > 11:
                continue
            # 过滤 PE 为负且退市迹象
            if not code or len(code) != 6:
                continue
            filtered.append((q, pct))
        except Exception:
            continue

    filtered.sort(key=lambda x: x[1], reverse=(top == "up"))
    out: list[dict[str, object]] = []
    for q, pct in filtered[:limit]:
        out.append(
            {
                "code": str(getattr(q, "code", "")),
                "name": str(getattr(q, "name", "")),
                "price": str(getattr(q, "price", 0)),
                "change_pct": str(pct),
                "change": str(getattr(q, "change", 0)),
                "volume": int(getattr(q, "volume", 0)),
                "turnover": str(q.turnover.amount if getattr(q, "turnover", None) else 0),
                "market": q.market.value if getattr(q, "market", None) else "",
            }
        )
    return out
