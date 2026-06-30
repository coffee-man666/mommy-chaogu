"""/api/portfolio 路由：持仓管理 + 盈亏计算。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from mommy_chaogu.portfolio import PortfolioStore
from mommy_chaogu.portfolio.store import PositionNotFoundError
from mommy_chaogu.web.deps import get_adapter, get_portfolio_store
from mommy_chaogu.web.mappers import (
    adjustment_to_out,
    position_detail_to_out,
    position_to_out,
)
from mommy_chaogu.web.schemas import (
    AddAdjustmentIn,
    AddPositionIn,
    AdjustmentOut,
    PortfolioSummaryOut,
    PositionDetailOut,
    PositionOut,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSummaryOut)
def get_portfolio(
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
    adapter: Annotated[object, Depends(get_adapter)],
) -> PortfolioSummaryOut:
    """持仓总览（含实时盈亏）。"""
    positions = store.list_positions()
    if not positions:
        return PortfolioSummaryOut(
            positions=[],
            total_cost=Decimal("0"),
            total_market_value=None,
            total_unrealized_pnl=None,
            total_unrealized_pnl_pct=None,
            n_positions=0,
        )

    # 拉实时价格
    codes = list({p.code for p in positions})
    current_prices: dict[str, Decimal] = {}
    try:
        for code in codes:
            q = adapter.get_quote(code)
            if q is not None:
                current_prices[code] = q.price
    except Exception:
        pass  # 价格拉不到就只返回成本

    raw = store.summary(current_prices)
    detail_list: list[PositionDetailOut] = []
    for item in raw["positions"]:
        pos = item["position"]  # type: ignore[assignment]
        detail_list.append(
            position_detail_to_out(
                pos=pos,  # type: ignore[arg-type]
                avg_cost=item["avg_cost"],  # type: ignore[arg-type]
                shares=item["shares"],  # type: ignore[arg-type]
                current_price=item["current_price"],  # type: ignore[arg-type]
                market_value=item["market_value"],  # type: ignore[arg-type]
                total_cost=item["total_cost"],  # type: ignore[arg-type]
                unrealized_pnl=item["unrealized_pnl"],  # type: ignore[arg-type]
                unrealized_pnl_pct=item["unrealized_pnl_pct"],  # type: ignore[arg-type]
            )
        )

    return PortfolioSummaryOut(
        positions=detail_list,
        total_cost=raw["total_cost"],  # type: ignore[arg-type]
        total_market_value=raw["total_market_value"],  # type: ignore[arg-type]
        total_unrealized_pnl=raw["total_unrealized_pnl"],  # type: ignore[arg-type]
        total_unrealized_pnl_pct=raw["total_unrealized_pnl_pct"],  # type: ignore[arg-type]
        n_positions=raw["n_positions"],  # type: ignore[arg-type]
    )


@router.get("/positions", response_model=list[PositionOut])
def list_positions(
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> list[PositionOut]:
    """所有持仓（不含盈亏，轻量）。"""
    return [position_to_out(p) for p in store.list_positions()]


@router.post("/positions", response_model=PositionOut, status_code=201)
def add_position(
    body: AddPositionIn,
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> PositionOut:
    """录入买入持仓。"""
    buy_dt: date | None = None
    if body.buy_date:
        try:
            buy_dt = date.fromisoformat(body.buy_date)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"buy_date 格式应为 YYYY-MM-DD: {e}",
            ) from e

    pos = store.add_position(
        code=body.code,
        name=body.name,
        buy_price=body.buy_price,
        shares=body.shares,
        buy_date=buy_dt,
        note=body.note or None,
    )
    return position_to_out(pos)


@router.delete("/positions/{position_id}", status_code=204)
def remove_position(
    position_id: int,
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> None:
    """删除持仓（清仓，级联删 adjustments）。"""
    try:
        store.remove_position(position_id)
    except PositionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/positions/{position_id}/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    position_id: int,
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> list[AdjustmentOut]:
    """某持仓的加减仓记录。"""
    try:
        store.get_position(position_id)
    except PositionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [adjustment_to_out(a) for a in store.list_adjustments(position_id)]


@router.post("/positions/{position_id}/adjustments", response_model=AdjustmentOut, status_code=201)
def add_adjustment(
    position_id: int,
    body: AddAdjustmentIn,
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> AdjustmentOut:
    """加仓 / 减仓 / 分红。"""
    try:
        adj = store.add_adjustment(
            position_id=position_id,
            action=body.action,
            price=body.price,
            shares=body.shares,
            note=body.note or None,
        )
    except PositionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return adjustment_to_out(adj)
