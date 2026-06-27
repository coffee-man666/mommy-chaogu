"""/api/watchlist 路由测试。"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from mommy_chaogu.watchlist.models import Group, StockEntry
from mommy_chaogu.watchlist.store import (
    GroupAlreadyExistsError,
    GroupNotFoundError,
    StockEntryNotFoundError,
)


def make_mock_store() -> MagicMock:
    """造一个 in-memory-like mock store。"""
    store = MagicMock()
    group = Group(name="持仓", description="核心持仓")
    entry = StockEntry(
        code="600519",
        name="贵州茅台",
        group_id=1,
        note="核心",
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    entry.group = group  # type: ignore[attr-defined]
    store.list_entries.return_value = [entry]
    store.list_groups.return_value = [(group, 1)]
    store.add_group.return_value = group
    store.add_entry.return_value = entry
    return store


class TestListStocks:
    """GET /api/watchlist — 列出自选股。"""

    def test_list(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        client.app.dependency_overrides[get_watchlist_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "600519"


class TestListGroups:
    """GET /api/watchlist/groups — 列出分组。"""

    def test_list(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        client.app.dependency_overrides[get_watchlist_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.get("/api/watchlist/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "持仓"
        assert data[0]["n_stocks"] == 1


class TestAddGroup:
    """POST /api/watchlist/groups — 新建分组。"""

    def test_add_success(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.post("/api/watchlist/groups", json={"name": "观察", "description": "观察仓"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "持仓"  # mock 返回默认 group

    def test_duplicate_409(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        store.add_group.side_effect = GroupAlreadyExistsError("已存在")
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.post("/api/watchlist/groups", json={"name": "持仓", "description": ""})
        assert resp.status_code == 409


class TestRemoveGroup:
    """DELETE /api/watchlist/groups/{name} — 删除分组。"""

    def test_remove_success(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.delete("/api/watchlist/groups/持仓")
        assert resp.status_code == 204

    def test_not_found_404(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        store.remove_group.side_effect = GroupNotFoundError("不存在")
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.delete("/api/watchlist/groups/不存在")
        assert resp.status_code == 404


class TestAddStock:
    """POST /api/watchlist/stocks — 添加自选股。"""

    def test_add_success(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.post(
            "/api/watchlist/stocks",
            json={"code": "000858", "group": "持仓", "note": "白酒"},
        )
        assert resp.status_code == 201

    def test_group_not_found(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        store.add_entry.side_effect = GroupNotFoundError("分组不存在")
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.post(
            "/api/watchlist/stocks",
            json={"code": "000858", "group": "不存在", "note": ""},
        )
        assert resp.status_code == 404


class TestRemoveStock:
    """DELETE /api/watchlist/stocks/{code}?group=xxx — 删除自选股。"""

    def test_remove_success(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.delete("/api/watchlist/stocks/600519?group=持仓")
        assert resp.status_code == 204

    def test_not_found_404(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_watchlist_store

        store = make_mock_store()
        store.remove_entry.side_effect = StockEntryNotFoundError("不存在")
        client.app.dependency_overrides[get_watchlist_store] = lambda: store

        resp = client.delete("/api/watchlist/stocks/999999?group=持仓")
        assert resp.status_code == 404
