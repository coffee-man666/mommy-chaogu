"""Server-owned decision context for one stock."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict, cast

from mommy_chaogu.portfolio import PortfolioStore
from mommy_chaogu.services.basket_service import BasketService
from mommy_chaogu.watchlist import WatchlistStore


class StockHoldingContext(TypedDict):
    position_count: int
    shares: int
    avg_cost: Decimal
    total_cost: Decimal


class StockBasketContext(TypedDict):
    id: str
    name: str
    kind: str
    reason: str


class StockDecisionContext(TypedDict):
    code: str
    holding: StockHoldingContext | None
    baskets: list[StockBasketContext]


class StockContextService:
    """Assemble holdings and basket membership without fetching market data."""

    def __init__(self, portfolio: PortfolioStore, watchlist: WatchlistStore) -> None:
        self._portfolio = portfolio
        self._watchlist = watchlist

    def get(self, code: str) -> StockDecisionContext:
        raw_positions = cast(
            list[dict[str, Any]],
            self._portfolio.summary({})["positions"],
        )
        position_rows = [
            row for row in raw_positions if row["position"].code == code and int(row["shares"]) > 0
        ]
        total_shares = sum(int(row["shares"]) for row in position_rows)
        total_cost = sum(
            (cast(Decimal, row["total_cost"]) for row in position_rows),
            Decimal("0"),
        )
        holding: StockHoldingContext | None = None
        if total_shares > 0:
            holding = StockHoldingContext(
                position_count=len(position_rows),
                shares=total_shares,
                avg_cost=(total_cost / total_shares).quantize(Decimal("0.0001")),
                total_cost=total_cost,
            )

        baskets = [
            StockBasketContext(
                id=basket["id"],
                name=basket["name"],
                kind=basket["kind"],
                reason=basket["reason"],
            )
            for basket in BasketService(self._watchlist).list_baskets()
            if any(member["code"] == code for member in basket["members"])
        ]
        return StockDecisionContext(code=code, holding=holding, baskets=baskets)
