"""Unified built-in theme and user custom-basket API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from mommy_chaogu.market_data import MarketDataAdapter
from mommy_chaogu.services.basket_service import BasketDefinition, BasketService
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.background import get_service
from mommy_chaogu.web.deps import get_adapter, get_watchlist_store
from mommy_chaogu.web.schemas import (
    BasketDetailOut,
    BasketMemberOut,
    BasketMemberWeightIn,
    BasketOut,
    BasketPreferenceIn,
)

router = APIRouter(prefix="/api/baskets", tags=["baskets"])


def _catalog_item(item: BasketDefinition) -> dict[str, Any]:
    # Members are deliberately included in the catalog response.  The iOS
    # client can render the basket immediately from this static directory and
    # hydrate live quote fields separately, instead of blocking the first
    # screen on a large quote request.
    return dict(item)


@router.get("", response_model=list[BasketOut])
def list_baskets(
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> list[dict[str, Any]]:
    """List built-in themes and watchlist groups through one ordered contract."""
    return [_catalog_item(item) for item in BasketService(store).list_baskets()]


@router.get("/{basket_id}", response_model=BasketDetailOut)
def get_basket(
    basket_id: str,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
) -> dict[str, Any]:
    # The background poller is the single owner of live quote fetching in a
    # running server.  Reusing its snapshot keeps this endpoint fast and
    # prevents opening a 100+ member basket from triggering a new network
    # batch.  Test clients without a lifespan fall back to the injected
    # adapter so the endpoint remains easy to exercise in isolation.
    try:
        background = get_service()
    except RuntimeError:
        background = None

    if background is None:
        service = BasketService(store, adapter)
    else:
        snapshot = background.latest_snapshot
        quote_overrides = (
            {row.entry.code: row.quote for row in snapshot.rows}
            if snapshot is not None
            else {}
        )
        service = BasketService(store, quote_overrides=quote_overrides)
    item = service.get_basket(basket_id)
    if item is None:
        raise HTTPException(status_code=404, detail="篮子不存在")
    return {**item, **service.summarize(item)}


@router.post("/{basket_id}/preference", response_model=BasketOut)
def update_basket_preference(
    basket_id: str,
    body: BasketPreferenceIn,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> dict[str, Any]:
    service = BasketService(store)
    if service.get_basket(basket_id) is None:
        raise HTTPException(status_code=404, detail="篮子不存在")
    fields = body.model_fields_set
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要更新的偏好")
    store.set_basket_preference(
        basket_id,
        followed=body.followed if "followed" in fields else None,
        hidden=body.hidden if "hidden" in fields else None,
        sort_order=body.sort_order if "sort_order" in fields else None,
        reason=body.reason.strip() if body.reason is not None else None,
        update_reason="reason" in fields,
    )
    updated = BasketService(store).get_basket(basket_id)
    if updated is None:  # pragma: no cover - definition cannot disappear in this request
        raise HTTPException(status_code=404, detail="篮子不存在")
    return _catalog_item(updated)


@router.post("/{basket_id}/members/{code}/weight", response_model=BasketMemberOut)
def update_basket_member_weight(
    basket_id: str,
    code: str,
    body: BasketMemberWeightIn,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> dict[str, Any]:
    service = BasketService(store)
    item = service.get_basket(basket_id)
    if item is None:
        raise HTTPException(status_code=404, detail="篮子不存在")
    member = next((candidate for candidate in item["members"] if candidate["code"] == code), None)
    if member is None:
        raise HTTPException(status_code=404, detail="篮子中没有这只股票")
    store.set_basket_member_weight(basket_id, code, body.weight)
    return {**member, "weight": body.weight}
