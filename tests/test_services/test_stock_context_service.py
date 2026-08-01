from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from mommy_chaogu.services.stock_context_service import StockContextService


def test_aggregates_open_positions_and_basket_memberships(monkeypatch) -> None:
    portfolio = MagicMock()
    portfolio.summary.return_value = {
        "positions": [
            {
                "position": SimpleNamespace(code="600519"),
                "shares": 100,
                "total_cost": Decimal("150000"),
            },
            {
                "position": SimpleNamespace(code="600519"),
                "shares": 50,
                "total_cost": Decimal("80000"),
            },
            {
                "position": SimpleNamespace(code="000858"),
                "shares": 10,
                "total_cost": Decimal("1000"),
            },
        ]
    }
    watchlist = MagicMock()
    monkeypatch.setattr(
        "mommy_chaogu.services.stock_context_service.BasketService.list_baskets",
        lambda _self: [
            {
                "id": "theme:liquor",
                "name": "白酒",
                "kind": "theme",
                "reason": "消费复苏",
                "members": [{"code": "600519"}],
            },
            {
                "id": "group:1",
                "name": "观察",
                "kind": "custom",
                "reason": "",
                "members": [{"code": "000858"}],
            },
        ],
    )

    result = StockContextService(portfolio, watchlist).get("600519")

    assert result["holding"] == {
        "position_count": 2,
        "shares": 150,
        "avg_cost": Decimal("1533.3333"),
        "total_cost": Decimal("230000"),
    }
    assert result["baskets"] == [
        {"id": "theme:liquor", "name": "白酒", "kind": "theme", "reason": "消费复苏"}
    ]


def test_returns_empty_context_for_unheld_stock(monkeypatch) -> None:
    portfolio = MagicMock()
    portfolio.summary.return_value = {"positions": []}
    monkeypatch.setattr(
        "mommy_chaogu.services.stock_context_service.BasketService.list_baskets",
        lambda _self: [],
    )

    result = StockContextService(portfolio, MagicMock()).get("688981")

    assert result == {"code": "688981", "holding": None, "baskets": []}
