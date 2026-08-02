"""WebSocket routes and background broadcast integration tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from mommy_chaogu.preferences import default_preferences
from mommy_chaogu.web.background import BackgroundService, set_service

from .conftest import make_signal, make_snapshot


def _fake_watchlist_store() -> MagicMock:
    """确定性的偏好来源（不读真实 data/portfolio.db）。"""
    store = MagicMock()
    store.get_user_preferences.return_value = default_preferences()
    return store


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

    def test_weixin_queue_is_bounded_and_keeps_latest_state(self) -> None:
        async def scenario() -> None:
            service = BackgroundService(
                adapter=MagicMock(),
                watchlist=MagicMock(),
                alerter=MagicMock(),
                weixin_sender=MagicMock(),
            )
            service._weixin_queue = asyncio.Queue(maxsize=1)
            first = [make_signal()]
            second: list[object] = []
            service._enqueue_weixin(first)
            service._enqueue_weixin(second)
            assert await service._weixin_queue.get() == second

        asyncio.run(scenario())

    def test_tick_broadcasts_before_notification_enqueue(self) -> None:
        async def scenario() -> None:
            service = _service()
            snapshot = make_snapshot()
            signals = [make_signal()]
            service.watchlist.get_all_codes.return_value = ["600519"]
            service.monitor.snapshot_now = MagicMock(return_value=snapshot)
            service.alerter.evaluate.return_value = signals
            service._quote_subscribers = {MagicMock()}
            service._signal_subscribers = {MagicMock()}
            order: list[str] = []
            service._broadcast_quotes = AsyncMock(
                side_effect=lambda _snapshot: order.append("quotes")
            )
            service._broadcast_signals = AsyncMock(
                side_effect=lambda _signals: order.append("signals")
            )
            service._enqueue_weixin = MagicMock(side_effect=lambda _signals: order.append("weixin"))

            await service._tick()

            assert order == ["quotes", "signals", "weixin"]

        asyncio.run(scenario())


class TestAgentWebSocket:
    def test_invalid_json_and_unconfigured_agent(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        from mommy_chaogu.web import deps

        monkeypatch.setattr(deps, "get_agent_service", lambda: None)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", MagicMock())  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_watchlist_store", _fake_watchlist_store)  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_text("not-json")
            assert ws.receive_json() == {"type": "error", "message": "无效的 JSON"}

            ws.send_json(["not", "an", "object"])
            assert ws.receive_json() == {"type": "error", "message": "无效的消息格式"}

            ws.send_json({"message": {"unexpected": "object"}})
            assert ws.receive_json() == {"type": "error", "message": "无效的消息格式"}

            ws.send_json(
                {
                    "message": "hello",
                    "page_context": {"surface": "stock", "stock_code": "prompt"},
                }
            )
            assert ws.receive_json() == {"type": "error", "message": "无效的页面上下文"}

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

        def fake_chat(message, history, system_override, sess_memory, *args, **kwargs):
            # 模拟 agent 层通过 on_chunk 回调推送真实 delta（#4 真流式）
            on_chunk = args[2] if len(args) > 2 else kwargs.get("on_chunk")
            if on_chunk is not None:
                on_chunk("abcdefghijkl")
                on_chunk("mnop")
            return SimpleNamespace(
                text="abcdefghijklmnop",
                tool_calls=[SimpleNamespace(name="get_quote")],
                rounds=2,
            )

        agent.chat.side_effect = fake_chat
        memory = MagicMock()
        session_memory = MagicMock()
        memory.for_session.return_value = session_memory
        monkeypatch.setattr(deps, "get_agent_service", lambda: agent)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_watchlist_store", _fake_watchlist_store)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            "mommy_chaogu.web.routes.ws.page_context_addendum",
            lambda context, _portfolio, _watchlist: (
                f"<page_context>{context.stock_code}:{context.tab}</page_context>"
                if context is not None
                else ""
            ),
        )

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json(
                {
                    "message": "hello",
                    "page_context": {
                        "surface": "stock",
                        "stock_code": "600519",
                        "tab": "flow",
                    },
                }
            )
            assert ws.receive_json() == {"type": "thinking"}
            # 真流式：on_chunk 推送的 delta 原样转发（不再是 12 字符切片）
            assert ws.receive_json() == {"type": "chunk", "text": "abcdefghijkl"}
            assert ws.receive_json() == {"type": "chunk", "text": "mnop"}
            assert ws.receive_json() == {
                "type": "done",
                "tools_used": ["get_quote"],
                "rounds": 2,
            }

        memory.for_session.assert_called_once_with("web-default")
        agent.chat.assert_called_once()
        call = agent.chat.call_args
        assert call.args[0] == "hello"
        assert call.args[2] is None
        assert "用户偏好均衡分析" in call.kwargs["system_addendum"]
        assert "<page_context>600519:flow</page_context>" in call.kwargs["system_addendum"]

    def test_style_comes_from_server_preferences(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        """WS 与 REST 一致：风格从服务端偏好读取，客户端 style_preset 被忽略。"""
        from mommy_chaogu.web import deps

        agent = MagicMock()
        agent.chat.return_value = SimpleNamespace(text="ok", tool_calls=[], rounds=1)
        memory = MagicMock()
        memory.for_session.return_value = MagicMock()
        store = _fake_watchlist_store()
        prefs = default_preferences()
        prefs["style"] = "conservative"
        store.get_user_preferences.return_value = prefs
        monkeypatch.setattr(deps, "get_agent_service", lambda: agent)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_watchlist_store", lambda: store)  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "看看风险", "style_preset": "aggressive"})
            assert ws.receive_json() == {"type": "thinking"}
            assert ws.receive_json() == {"type": "chunk", "text": "ok"}
            assert ws.receive_json() == {"type": "done", "tools_used": [], "rounds": 1}

        call = agent.chat.call_args
        assert call.args[0] == "看看风险"
        assert call.args[2] is None
        assert "稳健投资" in call.kwargs["system_addendum"]
        assert "积极策略" not in call.kwargs["system_addendum"]

    def test_streams_tool_call_events(self, client: TestClient, monkeypatch: object) -> None:
        """验证 on_tool_call/on_tool_result 回调被桥接成 tool_call_started/finished WS 帧。"""
        from mommy_chaogu.web import deps

        agent = MagicMock()

        def fake_chat(message, history, system_override, sess_memory, *args, **kwargs):
            # 位置参数顺序: on_tool_call, on_tool_result, on_chunk
            on_tool_call = args[0] if len(args) > 0 else kwargs.get("on_tool_call")
            on_tool_result = args[1] if len(args) > 1 else kwargs.get("on_tool_result")
            on_chunk = args[2] if len(args) > 2 else kwargs.get("on_chunk")
            # 模拟一次工具调用：started → finished(done)
            if on_tool_call is not None:
                on_tool_call("get_quote", {"code": "600519"})
            if on_tool_result is not None:
                on_tool_result("get_quote", True, 1200, '{"price": 1689.5}')
            if on_chunk is not None:
                on_chunk("茅台涨了")
            return SimpleNamespace(
                text="茅台涨了",
                tool_calls=[SimpleNamespace(name="get_quote")],
                rounds=1,
            )

        agent.chat.side_effect = fake_chat
        memory = MagicMock()
        session_memory = MagicMock()
        memory.for_session.return_value = session_memory
        monkeypatch.setattr(deps, "get_agent_service", lambda: agent)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_watchlist_store", _fake_watchlist_store)  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "茅台"})
            assert ws.receive_json() == {"type": "thinking"}
            # 工具事件帧必须在 chunk 之前（agent 先调工具再产出文本）
            assert ws.receive_json() == {
                "type": "tool_call_started",
                "tool": "get_quote",
                "args": {"code": "600519"},
            }
            assert ws.receive_json() == {
                "type": "tool_call_finished",
                "tool": "get_quote",
                "status": "done",
                "elapsed_ms": 1200,
                "result": '{"price": 1689.5}',
            }
            assert ws.receive_json() == {"type": "chunk", "text": "茅台涨了"}
            assert ws.receive_json() == {
                "type": "done",
                "tools_used": ["get_quote"],
                "rounds": 1,
            }

    def test_fallback_sends_full_text_when_streaming_unsupported(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        """provider 不支持 stream 时 on_chunk 不触发，resp.text 必须兜底补发。

        回归：此前真流式改造删掉了切片转发逻辑，流式不可用时前端会收到
        空回答——这里钉死兜底行为。
        """
        from mommy_chaogu.web import deps

        agent = MagicMock()
        agent.chat.return_value = SimpleNamespace(
            text="这是非流式兜底回答",
            tool_calls=[],
            rounds=1,
        )
        memory = MagicMock()
        session_memory = MagicMock()
        memory.for_session.return_value = session_memory
        monkeypatch.setattr(deps, "get_agent_service", lambda: agent)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)  # type: ignore[attr-defined]
        monkeypatch.setattr(deps, "get_watchlist_store", _fake_watchlist_store)  # type: ignore[attr-defined]

        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "hello"})
            assert ws.receive_json() == {"type": "thinking"}
            # on_chunk 从未触发 → 兜底：完整文本作为单个 chunk 补发
            assert ws.receive_json() == {"type": "chunk", "text": "这是非流式兜底回答"}
            assert ws.receive_json() == {
                "type": "done",
                "tools_used": [],
                "rounds": 1,
            }

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
