"""Single-owner Web authentication and WebSocket ticket tests."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mommy_chaogu.web.app import create_app
from mommy_chaogu.web.background import BackgroundService, set_service
from mommy_chaogu.web.security import WebSecurity

from .conftest import make_mock_service


def _client(token: str = "owner-secret", **kwargs: object) -> tuple[TestClient, WebSecurity]:
    set_service(make_mock_service())
    app = create_app(api_token=token, **kwargs)  # type: ignore[arg-type]
    return TestClient(app, raise_server_exceptions=False), app.state.web_security


class TestRestAuthentication:
    def test_health_is_public_and_hides_db_path(self) -> None:
        client, _ = _client()
        response = client.get("/api/health")
        assert response.status_code == 200
        assert "db_path" not in response.json()

    def test_protected_api_rejects_missing_and_invalid_token(self) -> None:
        client, _ = _client()
        missing = client.post("/api/auth/ws-ticket")
        invalid = client.post("/api/auth/ws-ticket", headers={"Authorization": "Bearer wrong"})
        assert missing.status_code == 401
        assert invalid.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"

    def test_protected_api_accepts_owner_token(self) -> None:
        client, _ = _client()
        response = client.post(
            "/api/auth/ws-ticket",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert response.status_code == 200
        assert response.json()["ticket"]
        assert response.json()["expires_at"] > 0

    def test_authentication_is_disabled_without_configured_token(self) -> None:
        client, _ = _client(token="")
        response = client.post("/api/auth/ws-ticket")
        assert response.status_code == 200


class TestWebSocketTickets:
    def test_socket_rejects_missing_ticket(self) -> None:
        client, _ = _client()
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            client.websocket_connect("/ws/quotes"),
        ):
            pass
        assert exc.value.code == 1008

    def test_socket_accepts_valid_ticket(self) -> None:
        client, security = _client()
        service = BackgroundService(MagicMock(), MagicMock(), MagicMock())
        set_service(service)
        ticket, _ = security.issue_ws_ticket()

        with client.websocket_connect(f"/ws/quotes?ticket={ticket}") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "pong"

    def test_tampered_and_expired_tickets_are_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        security = WebSecurity(api_token="secret", ticket_ttl_seconds=10)
        monkeypatch.setattr("mommy_chaogu.web.security.time.time", lambda: 100)
        ticket, _ = security.issue_ws_ticket()
        assert security.validate_ws_ticket(ticket)
        assert not security.validate_ws_ticket(f"{ticket}x")

        monkeypatch.setattr("mommy_chaogu.web.security.time.time", lambda: 111)
        assert not security.validate_ws_ticket(ticket)


class TestAgentConcurrency:
    def test_limit_is_bounded_and_releasable(self) -> None:
        security = WebSecurity(agent_max_concurrency=1)
        assert asyncio.run(security.try_acquire_agent()) is True
        assert asyncio.run(security.try_acquire_agent()) is False
        asyncio.run(security.release_agent())
        assert asyncio.run(security.try_acquire_agent()) is True

    def test_rest_agent_returns_429_when_saturated(self) -> None:
        client, security = _client(agent_max_concurrency=1)
        assert asyncio.run(security.try_acquire_agent())
        response = client.post(
            "/api/agent/chat",
            headers={"Authorization": "Bearer owner-secret"},
            json={"message": "hello"},
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"
        asyncio.run(security.release_agent())


class TestCors:
    def test_only_configured_origin_is_allowed(self) -> None:
        client, _ = _client(cors_origins=["https://stocks.example.com"])
        allowed = client.options(
            "/api/watchlist",
            headers={
                "Origin": "https://stocks.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        denied = client.options(
            "/api/watchlist",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "https://stocks.example.com"
        assert "access-control-allow-origin" not in denied.headers
