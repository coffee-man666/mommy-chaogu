"""/api/cache 路由测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class TestCacheStats:
    """GET /api/cache/stats — 缓存命中率 + 新鲜度。"""

    def test_returns_stats(self, client: TestClient) -> None:
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hits"] == 10
        assert data["fetches"] == 5
        assert data["miss"] == 5
        assert data["hit_rate"] == 0.6667  # 10 / (10 + 5)

    def test_freshness_report(self, client: TestClient) -> None:
        resp = client.get("/api/cache/stats")
        data = resp.json()
        assert len(data["freshness"]) == 1
        assert data["freshness"][0]["code"] == "600519"

    def test_empty_stats(
        self, client: TestClient, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.stats_counters = {
            "hits": 0,
            "fetches": 0,
            "fetch_ok": 0,
            "fetch_fail": 0,
            "miss": 0,
        }
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hit_rate"] == 0.0
