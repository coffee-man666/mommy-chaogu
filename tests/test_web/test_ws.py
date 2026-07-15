"""WebSocket routes and background broadcast integration tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from mommy_chaogu.web.background import BackgroundService, set_service

from .conftest import make_signal, make_snapshot


def _service() -> BackgroundService:
    return BackgroundService(
        adapter=MagicMock(),
        watchlist=MagicMock(),
        alerter=MagicMock(),
        poll_interval_seconds=60,
    )


class TestQuoteWebSocket:
    def test_registers_pushes_latest_and_removes(self, client: TestClient) -> None:
        service = _service()
        service._latest_snapshot = make_snapshot()
        set_service(service)

        with client.websocket_connect("/ws/quotes") as ws:
            payload = ws.receive_json()
            assert payload["type"] == "quote_update"
            assert payload["snapshot"]["n_codes"] == 2
            assert len(service._quote_subscribers) == 1

            ws.send_text("ping")
            assert ws.receive_text() == "pong"

        assert service._quote_subscribers == set()


class TestSignalWebSocket:
    def test_registers_pongs_and_removes(self, client: TestClient) -> None:
        service = _service()
        set_service(service)

        with client.websocket_connect("/ws/signals") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "pong"
            assert len(service._signal_subscribers) == 1

        assert service._signal_subscribers == set()


class TestBackgroundBroadcast:
    def test_quote_broadcast_removes_dead_client(self) -> None:
        service = _service()
        live = MagicMock()
        live.send_json = AsyncMock()
        dead = MagicMock()
        dead.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        service._quote_subscribers = {live, dead}

        asyncio.run(service._broadcast_quotes(make_snapshot()))

        live.send_json.assert_awaited_once()
        assert service._quote_subscribers == {live}

    def test_signal_broadcast_removes_dead_client(self) -> None:
        service = _service()
        live = MagicMock()
        live.send_json = AsyncMock()
        dead = MagicMock()
        dead.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        service._signal_subscribers = {live, dead}

        asyncio.run(service._broadcast_signals([make_signal()]))

        live.send_json.assert_awaited_once()
        assert service._signal_subscribers == {live}


class TestAgentWebSocket:
    def test_invalid_json_and_unconfigured_agent(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        from mommy_chaogu.web import deps

        monkeypatch.setattr(deps, "get_agent_service", lambda: None)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", MagicMock())  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_text("not-json")
            assert ws.receive_json() == {"type": "error", "message": "无效的 JSON"}

            ws.send_json({"message": "hello"})
            assert ws.receive_json() == {
                "type": "done",
                "text": "AI 助手未配置。",
                "tools_used": [],
                "rounds": 0,
            }

    def test_streams_configured_agent_response(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        from mommy_chaogu.web import deps

        agent = MagicMock()
        agent.chat.return_value = SimpleNamespace(
            text="abcdefghijklmnop",
            tool_calls=[SimpleNamespace(name="get_quote")],
            rounds=2,
        )
        memory = MagicMock()
        session_memory = MagicMock()
        memory.for_session.return_value = session_memory
        monkeypatch.setattr(deps, "get_agent_service", lambda: agent)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "hello"})
            assert ws.receive_json() == {"type": "thinking"}
            assert ws.receive_json() == {"type": "chunk", "text": "abcdefghijkl"}
            assert ws.receive_json() == {"type": "chunk", "text": "mnop"}
            assert ws.receive_json() == {
                "type": "done",
                "tools_used": ["get_quote"],
                "rounds": 2,
            }

        memory.for_session.assert_called_once_with("web-default")
        agent.chat.assert_called_once_with("hello", None, None, session_memory)

    def test_rejects_invalid_session_id(self, client: TestClient, monkeypatch: object) -> None:
        from mommy_chaogu.web import deps

        agent = MagicMock()
        memory = MagicMock()
        memory.for_session.side_effect = ValueError("bad session")
        monkeypatch.setattr(deps, "get_agent_service", lambda: agent)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "hello", "session_id": "../bad"})
            assert ws.receive_json() == {"type": "error", "message": "无效的会话 ID"}
