"""Unified basket API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.services.theme_service import ThemeService
from mommy_chaogu.watchlist import WatchlistStore


@pytest.fixture()
def basket_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from mommy_chaogu.web.app import create_app
    from mommy_chaogu.web.deps import get_adapter, get_watchlist_store

    store = WatchlistStore(tmp_path / "portfolio.db")
    group = store.add_group("我的组合", "自定义关注")
    store.add_entry("600003", group.name, note="等待放量")
    store.backfill_name("600003", "丙公司")
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
    adapter = MagicMock()

    def quote(code: str) -> object:
        changes = {"600001": Decimal("2.00"), "600002": Decimal("-1.00")}
        change = changes.get(code)
        if change is None:
            return None
        return SimpleNamespace(
            code=code,
            change_pct=change,
            timestamp=datetime.now(UTC),
        )

    adapter.get_quotes.side_effect = lambda codes: [item for code in codes if (item := quote(code))]
    app = create_app()
    app.dependency_overrides[get_watchlist_store] = lambda: store
    app.dependency_overrides[get_adapter] = lambda: adapter
    return TestClient(app, raise_server_exceptions=False)


def test_catalog_unifies_built_in_and_custom_baskets(basket_client: TestClient) -> None:
    response = basket_client.get("/api/baskets")
    assert response.status_code == 200
    items = response.json()
    assert [item["kind"] for item in items] == ["theme", "custom"]
    assert items[0]["id"] == "theme:chips"
    assert items[0]["followed"] is True
    assert items[1]["name"] == "我的组合"


def test_preference_update_is_reflected_by_catalog(basket_client: TestClient) -> None:
    response = basket_client.post(
        "/api/baskets/theme:chips/preference",
        json={"followed": False, "hidden": True, "sort_order": 7, "reason": "等估值回落"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["followed"] is False
    assert updated["hidden"] is True
    assert updated["reason"] == "等估值回落"

    catalog = basket_client.get("/api/baskets").json()
    chips = next(item for item in catalog if item["id"] == "theme:chips")
    assert chips["sort_order"] == 7


def test_detail_contains_decision_summary_and_members(basket_client: TestClient) -> None:
    response = basket_client.get("/api/baskets/theme:chips")
    assert response.status_code == 200
    body = response.json()
    assert body["change_pct"] == "0.50"
    assert body["leader"] == {"code": "600001", "name": "甲公司", "change_pct": "2.00"}
    assert body["laggard"]["name"] == "乙公司"
    assert len(body["members"]) == 2
    assert body["status"] == "ok"


def test_member_weights_persist_and_drive_weighted_summary(
    basket_client: TestClient,
) -> None:
    for code, weight in (("600001", "75"), ("600002", "25")):
        response = basket_client.post(
            f"/api/baskets/theme:chips/members/{code}/weight",
            json={"weight": weight},
        )
        assert response.status_code == 200
        assert Decimal(response.json()["weight"]) == Decimal(weight)

    detail = basket_client.get("/api/baskets/theme:chips").json()
    assert detail["change_pct"] == "1.25"
    assert [Decimal(member["weight"]) for member in detail["members"]] == [
        Decimal("75"),
        Decimal("25"),
    ]


def test_unknown_basket_is_404(basket_client: TestClient) -> None:
    assert basket_client.get("/api/baskets/theme:nope").status_code == 404
    assert (
        basket_client.post(
            "/api/baskets/theme:nope/preference", json={"followed": True}
        ).status_code
        == 404
    )


def test_weight_requires_explicit_value_and_valid_range(basket_client: TestClient) -> None:
    path = "/api/baskets/theme:chips/members/600001/weight"
    assert basket_client.post(path, json={}).status_code == 422
    assert basket_client.post(path, json={"weight": 101}).status_code == 422
