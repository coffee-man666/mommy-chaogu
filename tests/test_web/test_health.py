"""/api/health 路由测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class TestHealth:
    """GET /api/health — 服务健康检查。"""

    def test_returns_health(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "adapter_name" in data
        assert "uptime_seconds" in data
        assert "db_path" not in data

    def test_health_with_last_snapshot(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.last_poll_at.return_value = datetime.now(UTC)
        resp = client.get("/api/health")
        data = resp.json()
        assert data["ok"] is True
