"""Unified basket service tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.services.basket_service import BasketService
from mommy_chaogu.services.theme_service import ThemeService
from mommy_chaogu.watchlist import WatchlistStore


@pytest.fixture()
def store(tmp_path: Path) -> WatchlistStore:
    return WatchlistStore(tmp_path / "portfolio.db")


@pytest.fixture(autouse=True)
def themes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ThemeService,
        "list_theme_details",
        lambda _self: [
            {
                "id": "chips",
                "name": "芯片",
                "description": "半导体产业链",
                "stocks": [
                    {"code": "600001", "name": "甲公司"},
                    {"code": "600002", "name": "乙公司"},
                ],
            }
        ],
    )


def test_unifies_theme_and_watchlist_group_with_server_preferences(
    store: WatchlistStore,
) -> None:
    group = store.add_group("我的组合", "长期观察")
    store.add_entry("600003", group.name, note="等待放量")
    store.backfill_name("600003", "丙公司")
    store.set_basket_preference(
        "theme:chips",
        followed=False,
        sort_order=8,
        reason="估值偏高",
        update_reason=True,
    )

    baskets = BasketService(store).list_baskets()

    assert [item["kind"] for item in baskets] == ["custom", "theme"]
    theme = baskets[1]
    assert theme["followed"] is False
    assert theme["reason"] == "估值偏高"
    custom = baskets[0]
    assert custom["id"] == f"group:{group.id}"
    assert custom["members"][0]["name"] == "丙公司"


def test_summary_reports_performance_movers_anomaly_and_partial_data(
    store: WatchlistStore,
) -> None:
    quotes = {
        "600001": SimpleNamespace(
            change_pct=Decimal("6.00"), timestamp=datetime(2026, 8, 1, tzinfo=UTC)
        )
    }
    adapter = MagicMock()
    adapter.get_quotes.return_value = []
    service = BasketService(store, adapter, quote_overrides=quotes)  # type: ignore[arg-type]
    basket = service.get_basket("theme:chips")

    assert basket is not None
    summary = service.summarize(basket)
    assert summary["change_pct"] == Decimal("6.00")
    assert summary["leader"]["name"] == "甲公司"
    assert summary["laggard"]["name"] == "甲公司"
    assert summary["anomaly"] == "甲公司波动 +6.00%"
    assert summary["status"] == "stale"
    assert summary["message"] == "1 只成分股行情未获取"
    adapter.get_quotes.assert_called_once_with(["600002"])


def test_summary_normalizes_mixed_naive_and_aware_quote_timestamps(
    store: WatchlistStore,
) -> None:
    now = datetime.now(UTC)
    quotes = {
        "600001": SimpleNamespace(change_pct=Decimal("1"), timestamp=now),
        "600002": SimpleNamespace(change_pct=Decimal("-1"), timestamp=now.replace(tzinfo=None)),
    }
    service = BasketService(store, quote_overrides=quotes)  # type: ignore[arg-type]
    basket = service.get_basket("theme:chips")

    assert basket is not None
    summary = service.summarize(basket)
    assert summary["as_of"].tzinfo is UTC
    assert summary["status"] == "ok"
