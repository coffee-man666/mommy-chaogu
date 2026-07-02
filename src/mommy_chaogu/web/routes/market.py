"""/api/market 路由：市场行情扫描 + 大盘指数 + 板块排行。"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from mommy_chaogu.market_data import MarketDataAdapter
from mommy_chaogu.market_data.rankings import (
    fetch_indexes,
    fetch_sector_ranking,
)
from mommy_chaogu.web.deps import get_adapter
from mommy_chaogu.web.schemas import IndexOut, SectorOut

router = APIRouter(prefix="/api/market", tags=["market"])


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
