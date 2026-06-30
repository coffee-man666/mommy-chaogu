"""/api/quotes 路由：实时报价 + K 线 + 盘口。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mommy_chaogu.market_data import BarInterval, MarketDataAdapter
from mommy_chaogu.market_data.types import AdjustmentType
from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.deps import get_adapter
from mommy_chaogu.web.mappers import (
    _quote_to_out,
    bar_to_out,
    orderbook_to_out,
    snapshot_to_out,
)
from mommy_chaogu.web.schemas import (
    BarOut,
    OrderBookOut,
    QuoteOut,
    SnapshotOut,
)

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("", response_model=SnapshotOut)
def get_snapshot(service: Annotated[BackgroundService, Depends(get_service)]) -> SnapshotOut:
    """自选股实时快照（从后台缓存拿，不走 DB/网络）。"""
    snap = service.latest_snapshot
    if snap is None:
        raise HTTPException(status_code=503, detail="快照尚未生成（首次轮询中）")
    return snapshot_to_out(snap)


@router.get("/{code}", response_model=QuoteOut)
def get_quote(
    code: str,
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
    service: Annotated[BackgroundService, Depends(get_service)],
) -> QuoteOut:
    """单股实时报价。优先走缓存，miss 再走网络。"""
    snap = service.latest_snapshot
    if snap is not None:
        for row in snap.rows:
            if row.entry.code == code:
                return _quote_to_out(row)
    # fallback：单独拉一次
    quote = adapter.get_quote(code)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 报价（数据源可能挂了）")
    # 构造伪 row
    from mommy_chaogu.monitor import SnapshotRow
    from mommy_chaogu.watchlist.models import StockEntry

    entry = StockEntry(code=code, group_id=0, name=quote.name)
    row = SnapshotRow(entry=entry, group_name="查询", quote=quote)
    return _quote_to_out(row)


@router.get("/{code}/bars", response_model=list[BarOut])
def get_bars(
    code: str,
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
    interval: Annotated[BarInterval, Query(description="K 线周期")] = BarInterval.D1,
    limit: Annotated[int, Query(ge=1, le=500)] = 120,
    adjustment: Annotated[AdjustmentType, Query(description="复权方式")] = AdjustmentType.FORWARD,
) -> list[BarOut]:
    """K 线数据。"""
    bars = adapter.get_bars(code, interval=interval, limit=limit, adjustment=adjustment)  # type: ignore[arg-type]
    return [bar_to_out(b) for b in bars]


@router.get("/{code}/orderbook", response_model=OrderBookOut)
def get_orderbook(
    code: str,
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
) -> OrderBookOut:
    """5 档盘口。"""
    ob = adapter.get_order_book(code)
    if ob is None:
        raise HTTPException(status_code=404, detail=f"未获取到 {code} 盘口")
    return orderbook_to_out(code, ob)


@router.get("/{code}/money_flow/today")
def get_today_money_flow(
    code: str,
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
) -> dict[str, Any]:
    """当日资金流（含累计汇总）。

    注意：efinance get_today_bill 返回的每条数据是到该时刻的**累计值**，
    不是增量。最后一条即为当日全天累计。
    """
    flows = adapter.get_today_money_flow(code)
    items = [
        {
            "timestamp": f.timestamp.isoformat(),
            "main_net": str(f.main_net.amount),
            "super_net": str(f.super_large_net.amount) if f.super_large_net else None,
            "big_net": str(f.large_net.amount) if f.large_net else None,
            "medium_net": str(f.medium_net.amount) if f.medium_net else None,
            "small_net": str(f.small_net.amount) if f.small_net else None,
            "main_ratio": str(f.main_net_ratio) if f.main_net_ratio is not None else None,
        }
        for f in flows
    ]
    # 当日累计 = 最后一条（已经是累计值）
    cumulative = items[-1] if items else {}
    return {"items": items, "cumulative": {
        "main_net": cumulative.get("main_net", "0"),
        "super_net": cumulative.get("super_net") or "0",
        "big_net": cumulative.get("big_net") or "0",
        "medium_net": cumulative.get("medium_net") or "0",
        "small_net": cumulative.get("small_net") or "0",
    }}


@router.get("/{code}/money_flow/history")
def get_history_money_flow(
    code: str,
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """历史资金流（每日一条 + 累计汇总）。

    返回：
    - items: 每日资金流列表（按日期升序）
    - cumulative: 整个时间段累计
    """
    flows = adapter.get_history_money_flow(code, days=days)
    items = [
        {
            "timestamp": f.timestamp.isoformat(),
            "date": f.timestamp.strftime("%Y-%m-%d"),
            "main_net": str(f.main_net.amount),
            "super_net": str(f.super_large_net.amount) if f.super_large_net else None,
            "big_net": str(f.large_net.amount) if f.large_net else None,
            "medium_net": str(f.medium_net.amount) if f.medium_net else None,
            "small_net": str(f.small_net.amount) if f.small_net else None,
            "main_ratio": str(f.main_net_ratio) if f.main_net_ratio is not None else None,
        }
        for f in flows
    ]
    cumulative = _cumulative_from_items(items)
    return {"items": items, "cumulative": cumulative, "days": days}


def _cumulative_from_items(items: list[dict[str, Any]]) -> dict[str, str]:
    """从资金流列表算累计。"""
    from decimal import Decimal

    fields = ["main_net", "super_net", "big_net", "medium_net", "small_net"]
    totals: dict[str, Decimal] = {f: Decimal("0") for f in fields}
    for item in items:
        for f in fields:
            v = item.get(f)
            if v is not None:
                totals[f] += Decimal(v)
    return {f: str(totals[f]) for f in fields}
