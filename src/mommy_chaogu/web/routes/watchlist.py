"""/api/watchlist 路由：自选池 CRUD。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from mommy_chaogu.web.deps import get_watchlist_store
from mommy_chaogu.web.mappers import group_to_out, stock_entry_to_out
from mommy_chaogu.web.schemas import (
    AddGroupIn,
    AddStockIn,
    WatchlistGroupOut,
    WatchlistStockOut,
)
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.watchlist.store import (
    GroupAlreadyExistsError,
    GroupNotFoundError,
    StockEntryNotFoundError,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistStockOut])
def list_stocks(
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> list[WatchlistStockOut]:
    """所有自选股（带分组名）。"""
    result: list[WatchlistStockOut] = []
    for entry in store.list_entries():
        result.append(stock_entry_to_out(entry, entry.group.name))
    return result


@router.get("/groups", response_model=list[WatchlistGroupOut])
def list_groups(
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> list[WatchlistGroupOut]:
    """所有分组（带股票数）。"""
    return [
        group_to_out(group, count)
        for group, count in store.list_groups()
    ]


@router.post("/groups", response_model=WatchlistGroupOut, status_code=201)
def add_group(
    body: AddGroupIn,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> WatchlistGroupOut:
    """新建分组。"""
    try:
        group = store.add_group(body.name, description=body.description)
    except GroupAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return group_to_out(group, 0)


@router.delete("/groups/{name}", status_code=204)
def remove_group(
    name: str,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> None:
    """删除分组（连带删自选股）。"""
    try:
        store.remove_group(name)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/stocks", response_model=WatchlistStockOut, status_code=201)
def add_stock(
    body: AddStockIn,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> WatchlistStockOut:
    """添加自选股。"""
    try:
        entry = store.add_entry(body.code, body.group, note=body.note)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return stock_entry_to_out(entry, body.group)


@router.delete("/stocks/{code}", status_code=204)
def remove_stock(
    code: str,
    group: str,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> None:
    """删除自选股。"""
    try:
        store.remove_entry(code, group)
    except StockEntryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
