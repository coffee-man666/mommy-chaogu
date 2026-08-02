"""/api/agent 路由的行为测试。

覆盖 src/mommy_chaogu/web/routes/agent.py 的未测端点与分支：
- POST /api/agent/chat       — 单轮问答（降级 + 正常）
- POST /api/agent/route      — 工作流路由（未命中）
- GET  /api/agent/history    — 对话历史（含异常分支 + session_id 透传）
- GET  /api/agent/predictions — 预测记录（含异常分支）
- get_prediction_tracker_safe() — helper 的正常 / 异常两条分支
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.preferences import default_preferences
from mommy_chaogu.web.deps import get_agent_memory, get_agent_service

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeToolCall:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeChatResp:
    def __init__(self, text: str, tool_names: list[str], rounds: int) -> None:
        self.text = text
        self.tool_calls = [_FakeToolCall(n) for n in tool_names]
        self.rounds = rounds


class _FakeAgent:
    """同步 chat()，被 asyncio.to_thread 包装调用。"""

    def __init__(self, resp: _FakeChatResp) -> None:
        self._resp = resp
        self.last_call: tuple[Any, ...] | None = None
        self.last_kwargs: dict[str, Any] = {}

    def chat(
        self,
        message: str,
        history: Any,
        system_override: Any,
        memory_ctx: Any,
        **kwargs: Any,
    ) -> _FakeChatResp:
        self.last_call = (message, history, system_override, memory_ctx)
        self.last_kwargs = kwargs
        return self._resp


class _FakeChatMemory:
    """chat 端点 Depends(get_agent_memory) 用的假记忆（只需 for_session）。"""

    def for_session(self, session_id: str) -> list[dict[str, str]]:
        return [{"role": "user", "content": f"ctx-for-{session_id}"}]


class _FakeHistoryMemory:
    """history 端点直接调用 get_agent_memory() 的假记忆。"""

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._rows = rows if rows is not None else []
        self._exc = exc
        self.recent_calls: list[tuple[int, str]] = []

    def recent(self, limit: int = 50, session_id: str = "web-default") -> list[dict[str, Any]]:
        self.recent_calls.append((limit, session_id))
        if self._exc is not None:
            raise self._exc
        return self._rows


class _FakeTracker:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._rows = rows if rows is not None else []
        self._exc = exc

    def all(self, limit: int = 20) -> list[dict[str, Any]]:
        if self._exc is not None:
            raise self._exc
        return self._rows

    def by_code(self, code: str, limit: int = 20) -> list[dict[str, Any]]:
        if self._exc is not None:
            raise self._exc
        return [row for row in self._rows if row.get("code") == code][:limit]

    def count_by_code(self, code: str) -> int:
        if self._exc is not None:
            raise self._exc
        return sum(1 for row in self._rows if row.get("code") == code)


class _FakeRouteResult:
    def __init__(self, matched: bool = False) -> None:
        self.matched = matched
        self.workflow = None


class _FakeNLRouter:
    def __init__(self, route_result: Any) -> None:
        self._route_result = route_result
        self.route_calls: list[str] = []

    def route(self, message: str) -> Any:
        self.route_calls.append(message)
        return self._route_result


# ---------------------------------------------------------------------------
# POST /api/agent/chat
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    def test_no_agent_returns_degraded(self, client: TestClient) -> None:
        """agent 未配置（None）时返回降级提示。"""
        client.app.dependency_overrides[get_agent_service] = lambda: None
        client.app.dependency_overrides[get_agent_memory] = lambda: _FakeChatMemory()

        resp = client.post("/api/agent/chat", json={"message": "今天怎么样"})
        assert resp.status_code == 200
        body = resp.json()
        assert "DEEPSEEK_API_KEY" in body["reply"]
        assert body["tools_used"] == []
        assert body["rounds"] == 0

    def test_with_agent_returns_reply(self, client: TestClient) -> None:
        """agent 已配置时返回 chat 结果，并透传 memory 上下文。"""
        agent = _FakeAgent(
            _FakeChatResp(text="市场震荡", tool_names=["get_quote", "get_flow"], rounds=2)
        )
        client.app.dependency_overrides[get_agent_service] = lambda: agent
        client.app.dependency_overrides[get_agent_memory] = lambda: _FakeChatMemory()

        resp = client.post(
            "/api/agent/chat",
            json={"message": "茅台怎么样", "session_id": "sess-1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["reply"] == "市场震荡"
        assert body["tools_used"] == ["get_quote", "get_flow"]
        assert body["rounds"] == 2
        # message 与 memory.for_session() 结果都传到了 agent.chat
        assert agent.last_call is not None
        assert agent.last_call[0] == "茅台怎么样"
        assert agent.last_call[2] is None
        assert agent.last_call[3] == [{"role": "user", "content": "ctx-for-sess-1"}]
        assert "用户偏好均衡分析" in agent.last_kwargs["system_addendum"]

    def test_style_comes_from_server_preferences(
        self, client: TestClient, mock_watchlist_store: Any
    ) -> None:
        """交易风格从服务端偏好读取，客户端 style_preset 被忽略（兼容旧客户端）。"""
        agent = _FakeAgent(_FakeChatResp(text="ok", tool_names=[], rounds=1))
        client.app.dependency_overrides[get_agent_service] = lambda: agent
        client.app.dependency_overrides[get_agent_memory] = lambda: _FakeChatMemory()
        prefs = default_preferences()
        prefs["style"] = "conservative"
        mock_watchlist_store.get_user_preferences.return_value = prefs

        resp = client.post(
            "/api/agent/chat",
            json={"message": "看看风险", "style_preset": "aggressive"},
        )
        assert resp.status_code == 200
        assert agent.last_call is not None
        # 可见用户消息原样传递，不走 system_override
        assert agent.last_call[0] == "看看风险"
        assert agent.last_call[2] is None
        addendum = agent.last_kwargs["system_addendum"]
        # 服务端偏好生效（而不是客户端发的 aggressive）
        assert "稳健投资" in addendum
        assert "积极策略" not in addendum
        # 偏好块包含持有周期 / 回撤敏感度 / 通知摘要
        assert "波段" in addendum
        assert "通知偏好" in addendum

    def test_preference_read_failure_falls_back_to_defaults(
        self, client: TestClient, mock_watchlist_store: Any
    ) -> None:
        """偏好读取失败时回落默认值，对话仍可用。"""
        agent = _FakeAgent(_FakeChatResp(text="ok", tool_names=[], rounds=1))
        client.app.dependency_overrides[get_agent_service] = lambda: agent
        client.app.dependency_overrides[get_agent_memory] = lambda: _FakeChatMemory()
        mock_watchlist_store.get_user_preferences.side_effect = RuntimeError("db locked")

        resp = client.post("/api/agent/chat", json={"message": "今天怎么样"})
        assert resp.status_code == 200
        assert "用户偏好均衡分析" in agent.last_kwargs["system_addendum"]

    def test_validated_page_context_is_added_to_system_context(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent = _FakeAgent(_FakeChatResp(text="ok", tool_names=[], rounds=1))
        client.app.dependency_overrides[get_agent_service] = lambda: agent
        client.app.dependency_overrides[get_agent_memory] = lambda: _FakeChatMemory()
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.page_context_addendum",
            lambda context, _portfolio, _watchlist: (
                f"<page_context>{context.stock_code}:{context.tab}</page_context>"
            ),
        )

        response = client.post(
            "/api/agent/chat",
            json={
                "message": "接着分析",
                "page_context": {
                    "surface": "stock",
                    "stock_code": "600519",
                    "tab": "flow",
                },
            },
        )

        assert response.status_code == 200
        assert "<page_context>600519:flow</page_context>" in agent.last_kwargs["system_addendum"]

        invalid = client.post(
            "/api/agent/chat",
            json={
                "message": "test",
                "page_context": {"surface": "stock", "stock_code": "prompt", "tab": "flow"},
            },
        )
        assert invalid.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/agent/history
# ---------------------------------------------------------------------------


class TestHistoryEndpoint:
    def test_returns_history(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ]
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_agent_memory",
            lambda: _FakeHistoryMemory(rows=rows),
        )
        resp = client.get("/api/agent/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["messages"] == rows

    def test_exception_returns_empty(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_agent_memory",
            lambda: _FakeHistoryMemory(exc=RuntimeError("db locked")),
        )
        resp = client.get("/api/agent/history")
        assert resp.status_code == 200
        assert resp.json() == {"messages": [], "total": 0}

    def test_session_id_param(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeHistoryMemory(rows=[])
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_agent_memory",
            lambda: fake,
        )
        resp = client.get(
            "/api/agent/history",
            params={"session_id": "my-sess", "limit": 7},
        )
        assert resp.status_code == 200
        assert fake.recent_calls == [(7, "my-sess")]


# ---------------------------------------------------------------------------
# GET /api/agent/predictions
# ---------------------------------------------------------------------------


class TestPredictionsEndpoint:
    def test_no_tracker_returns_empty(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: None,
        )
        resp = client.get("/api/agent/predictions")
        assert resp.status_code == 200
        assert resp.json() == {"predictions": [], "total": 0}

    def test_code_filter_uses_filtered_total(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            {"code": "000001", "prediction": "A"},
            {"code": "600519", "prediction": "B"},
            {"code": "600519", "prediction": "C"},
        ]
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: _FakeTracker(rows=rows),
        )

        resp = client.get("/api/agent/predictions?code=600519&limit=1")
        assert resp.status_code == 200
        assert resp.json() == {
            "predictions": [{"code": "600519", "prediction": "B"}],
            "total": 2,
        }

    def test_returns_predictions(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [{"code": "600519", "prediction": "突破 1700", "status": "pending"}]
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: _FakeTracker(rows=rows),
        )
        resp = client.get("/api/agent/predictions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["predictions"][0]["code"] == "600519"

    def test_exception_returns_empty(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: _FakeTracker(exc=RuntimeError("boom")),
        )
        resp = client.get("/api/agent/predictions")
        assert resp.status_code == 200
        assert resp.json() == {"predictions": [], "total": 0}


# ---------------------------------------------------------------------------
# get_prediction_tracker_safe() helper
# ---------------------------------------------------------------------------


class TestPredictionTrackerSafeHelper:
    def test_returns_tracker_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mommy_chaogu.web.routes.agent as agent_mod

        monkeypatch.setattr(
            "mommy_chaogu.web.deps.get_prediction_tracker",
            lambda: "tracker-instance",
        )
        assert agent_mod.get_prediction_tracker_safe() == "tracker-instance"

    def test_returns_none_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mommy_chaogu.web.routes.agent as agent_mod

        def _boom() -> Any:
            raise RuntimeError("no db")

        monkeypatch.setattr(
            "mommy_chaogu.web.deps.get_prediction_tracker",
            _boom,
        )
        assert agent_mod.get_prediction_tracker_safe() is None


# ---------------------------------------------------------------------------
# POST /api/agent/route
# ---------------------------------------------------------------------------


class TestRouteEndpoint:
    def test_unmatched_returns_false(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_router = _FakeNLRouter(_FakeRouteResult(matched=False))
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent._get_router",
            lambda: fake_router,
        )
        resp = client.post("/api/agent/route", json={"message": "随便说点什么"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] is False
        assert body["workflow_id"] == ""
        assert body["reply"] == ""
        assert body["steps"] == []
        assert fake_router.route_calls == ["随便说点什么"]
