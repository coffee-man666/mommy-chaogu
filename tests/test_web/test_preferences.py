"""/api/preferences 路由测试。

契约（前端按此对接，勿改）：
- GET  /api/preferences        → 完整偏好对象（未定制字段回落默认值，updated_at=null）
- PUT  /api/preferences        → 部分更新，返回完整对象；非法值 422
- POST /api/preferences/reset  → 恢复默认，返回完整对象
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.deps import get_watchlist_store

_DEFAULT_BODY = {
    "style": "balanced",
    "holding_period": "swing",
    "drawdown_sensitivity": "medium",
    "notify_min_severity": "warning",
    "watched_rules": [],
    "reminder_windows": [],
    "default_hold_days": 5,
    "updated_at": None,
}


@pytest.fixture()
def prefs_store(client: TestClient, tmp_path: Path) -> WatchlistStore:
    """用真实 WatchlistStore（tmp db）替换 mock，验证端到端持久化。"""
    store = WatchlistStore(tmp_path / "portfolio.db")
    client.app.dependency_overrides[get_watchlist_store] = lambda: store
    return store


class TestGetPreferences:
    def test_defaults(self, client: TestClient, prefs_store: WatchlistStore) -> None:
        resp = client.get("/api/preferences")
        assert resp.status_code == 200
        assert resp.json() == _DEFAULT_BODY


class TestUpdatePreferences:
    def test_partial_update_returns_full_object(
        self, client: TestClient, prefs_store: WatchlistStore
    ) -> None:
        resp = client.put("/api/preferences", json={"style": "conservative"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["style"] == "conservative"
        assert body["holding_period"] == "swing"
        assert body["updated_at"] is not None

        # GET 能读到持久化的更新
        got = client.get("/api/preferences").json()
        assert got["style"] == "conservative"
        assert got["updated_at"] == body["updated_at"]

    def test_empty_body_is_noop(self, client: TestClient, prefs_store: WatchlistStore) -> None:
        resp = client.put("/api/preferences", json={})
        assert resp.status_code == 200
        assert resp.json() == _DEFAULT_BODY

    @pytest.mark.parametrize(
        "payload",
        [
            {"style": "yolo"},
            {"holding_period": "forever"},
            {"drawdown_sensitivity": "extreme"},
            {"notify_min_severity": "fatal"},
            {"reminder_windows": [{"start": "9:30", "end": "15:00"}]},
            {"reminder_windows": [{"start": "24:00", "end": "15:00"}]},
            {"reminder_windows": [{"start": "09:30"}]},
            {"unknown_field": "x"},
        ],
    )
    def test_invalid_values_422(
        self, client: TestClient, prefs_store: WatchlistStore, payload: dict
    ) -> None:
        resp = client.put("/api/preferences", json=payload)
        assert resp.status_code == 422
        # 非法写入不落库
        assert client.get("/api/preferences").json() == _DEFAULT_BODY

    def test_watched_rules_normalized(
        self, client: TestClient, prefs_store: WatchlistStore
    ) -> None:
        resp = client.put(
            "/api/preferences",
            json={"watched_rules": [" rule_a ", "rule_b", "", "  ", "rule_a"]},
        )
        assert resp.status_code == 200
        assert resp.json()["watched_rules"] == ["rule_a", "rule_b"]

    def test_reminder_windows_roundtrip(
        self, client: TestClient, prefs_store: WatchlistStore
    ) -> None:
        windows = [{"start": "09:30", "end": "15:00"}, {"start": "22:00", "end": "07:00"}]
        resp = client.put("/api/preferences", json={"reminder_windows": windows})
        assert resp.status_code == 200
        assert resp.json()["reminder_windows"] == windows


class TestDefaultHoldDays:
    @pytest.mark.parametrize(
        ("holding_period", "days"),
        [("short", 3), ("swing", 5), ("long", 20)],
    )
    def test_mapping(
        self,
        client: TestClient,
        prefs_store: WatchlistStore,
        holding_period: str,
        days: int,
    ) -> None:
        """default_hold_days 派生映射（未来回测入口的单一真相源）。"""
        resp = client.put("/api/preferences", json={"holding_period": holding_period})
        assert resp.status_code == 200
        assert resp.json()["default_hold_days"] == days


class TestResetPreferences:
    def test_reset_restores_defaults(self, client: TestClient, prefs_store: WatchlistStore) -> None:
        client.put(
            "/api/preferences",
            json={"style": "aggressive", "watched_rules": ["rule_a"]},
        )
        resp = client.post("/api/preferences/reset")
        assert resp.status_code == 200
        assert resp.json() == _DEFAULT_BODY
        assert client.get("/api/preferences").json() == _DEFAULT_BODY
