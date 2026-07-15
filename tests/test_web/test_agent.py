"""Agent REST session behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from mommy_chaogu.web.app import create_app
from mommy_chaogu.web.background import set_service
from mommy_chaogu.web.deps import get_agent_memory, get_agent_service

from .conftest import make_mock_service


def test_chat_uses_requested_session() -> None:
    set_service(make_mock_service())
    app = create_app()
    agent = MagicMock()
    agent.chat.return_value = SimpleNamespace(text="ok", tool_calls=[], rounds=1)
    memory = MagicMock()
    session_memory = MagicMock()
    memory.for_session.return_value = session_memory
    app.dependency_overrides[get_agent_service] = lambda: agent
    app.dependency_overrides[get_agent_memory] = lambda: memory
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/agent/chat",
        json={"message": "hello", "session_id": "browser-one"},
    )

    assert response.status_code == 200
    memory.for_session.assert_called_once_with("browser-one")
    agent.chat.assert_called_once_with("hello", None, None, session_memory)


def test_chat_rejects_invalid_session() -> None:
    set_service(make_mock_service())
    app = create_app()
    app.dependency_overrides[get_agent_service] = MagicMock()
    app.dependency_overrides[get_agent_memory] = MagicMock()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/agent/chat",
        json={"message": "hello", "session_id": "../bad"},
    )
    assert response.status_code == 422


def test_history_limit_is_capped() -> None:
    set_service(make_mock_service())
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.get("/api/agent/history?session_id=browser-one&limit=201")
    assert response.status_code == 422
