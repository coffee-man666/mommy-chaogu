"""/ws 路由：WebSocket 实时推送。

端点：
- WS /ws/quotes   — 推送最新报价快照（每 5s）
- WS /ws/signals  — 推送触发的信号（有就推）
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mommy_chaogu.web.agent_context import AgentPageContext, page_context_addendum
from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.mappers import signal_to_out, snapshot_to_out
from mommy_chaogu.web.trading_style import (
    DEFAULT_TRADING_STYLE,
    parse_trading_style,
    trading_style_context,
)

_log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ---------- 辅助函数 ----------


async def push_snapshot(ws: WebSocket, snapshot: Any) -> None:
    """推送报价快照。"""
    payload = snapshot_to_out(snapshot).model_dump(mode="json")
    await ws.send_json({"type": "quote_update", "snapshot": payload})


async def push_signals(ws: WebSocket, signals: list[Any]) -> None:
    """推送信号列表。"""
    payload = [signal_to_out(s).model_dump(mode="json") for s in signals]
    await ws.send_json({"type": "signal_triggered", "signals": payload})


# ---------- 端点 ----------


async def _authorize(websocket: WebSocket) -> bool:
    security = websocket.app.state.web_security
    if security.validate_ws_ticket(websocket.query_params.get("ticket")):
        return True
    await websocket.close(code=1008, reason="Missing or invalid WebSocket ticket")
    return False


@router.websocket("/ws/quotes")
async def ws_quotes(
    websocket: WebSocket,
    service: Annotated[BackgroundService, Depends(get_service)],
) -> None:
    """报价快照推送。"""
    if not await _authorize(websocket):
        return
    await websocket.accept()
    await service.add_quote_subscriber(websocket)  # type: ignore[arg-type]
    try:
        # 保持连接，接收客户端心跳（无业务消息，只是 keep-alive）
        while True:
            msg = await websocket.receive_text()
            # 简单回 pong（前端用来检测断线）
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        service.remove_quote_subscriber(websocket)  # type: ignore[arg-type]


@router.websocket("/ws/signals")
async def ws_signals(
    websocket: WebSocket,
    service: Annotated[BackgroundService, Depends(get_service)],
) -> None:
    """信号推送。"""
    if not await _authorize(websocket):
        return
    await websocket.accept()
    await service.add_signal_subscriber(websocket)  # type: ignore[arg-type]
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        service.remove_signal_subscriber(websocket)  # type: ignore[arg-type]


# ---------- Agent 流式对话 WebSocket ----------


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket) -> None:
    """AI 对话流式 WebSocket（真流式：逐 LLM delta 转发 + 工具调用事件）。

    消息格式：
    - 客户端发: {"message": "...", "history": [...], "session_id": "..."}
    - 服务端回: {"type": "thinking"} (一次)
    - 服务端回: {"type": "tool_call_started", "tool": "...", "args": {...}} (每次工具执行前)
    - 服务端回: {"type": "tool_call_finished", "tool": "...", "status": "done|fail", "elapsed_ms": N, "result": "..."} (每次工具执行后)
    - 服务端回: {"type": "chunk", "text": "..."} (多次，真实 LLM delta)
    - 服务端回: {"type": "done", "tools_used": [...], "rounds": N}

    兜底：若 agent 层流式不可用（provider 不支持 stream），on_chunk 不会
    被调用，此时把 resp.text 作为单个 chunk 补发，保证前端一定有回答。
    """
    import asyncio
    import json

    if not await _authorize(websocket):
        return
    await websocket.accept()

    from mommy_chaogu.web.deps import (
        get_agent_memory,
        get_agent_service,
        get_portfolio_store,
        get_watchlist_store,
    )

    agent = get_agent_service()
    memory = get_agent_memory()

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "无效的 JSON"})
                continue

            if not isinstance(msg, dict):
                await websocket.send_json({"type": "error", "message": "无效的消息格式"})
                continue

            raw_message = msg.get("message", "")
            if not isinstance(raw_message, str):
                await websocket.send_json({"type": "error", "message": "无效的消息格式"})
                continue

            user_message = raw_message.strip()
            if not user_message:
                continue

            session_id = msg.get("session_id", "web-default")
            try:
                style_preset = parse_trading_style(msg.get("style_preset", DEFAULT_TRADING_STYLE))
            except ValueError:
                await websocket.send_json({"type": "error", "message": "无效的交易风格设置"})
                continue
            try:
                raw_page_context = msg.get("page_context")
                page_context = (
                    AgentPageContext.model_validate(raw_page_context)
                    if raw_page_context is not None
                    else None
                )
            except ValidationError:
                await websocket.send_json({"type": "error", "message": "无效的页面上下文"})
                continue
            try:
                session_memory = memory.for_session(session_id)
            except (TypeError, ValueError):
                await websocket.send_json({"type": "error", "message": "无效的会话 ID"})
                continue

            if agent is None:
                await websocket.send_json(
                    {
                        "type": "done",
                        "text": "AI 助手未配置。",
                        "tools_used": [],
                        "rounds": 0,
                    }
                )
                continue

            # thinking 状态
            await websocket.send_json({"type": "thinking"})

            security = websocket.app.state.web_security
            if not await security.try_acquire_agent():
                await websocket.send_json({"type": "error", "message": "AI 助手忙，请稍后重试"})
                continue

            # 真流式：asyncio.Queue 桥接 worker 线程的所有回调 → 事件循环发送。
            # 一个 queue 承载 chunk + tool_call_started + tool_call_finished，保证顺序。
            loop = asyncio.get_running_loop()
            event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            streamed_any = False  # on_chunk 是否真的推过 delta（流式不可用时为 False）

            def _emit(event: dict[str, Any]) -> None:
                """worker 线程内调用，线程安全地把事件推入 queue。"""
                loop.call_soon_threadsafe(event_queue.put_nowait, event)  # noqa: B023

            def on_chunk(delta: str) -> None:
                nonlocal streamed_any
                streamed_any = True
                _emit({"type": "chunk", "text": delta})

            def on_tool_call(fn_name: str, fn_args: dict[str, Any]) -> None:
                _emit({"type": "tool_call_started", "tool": fn_name, "args": fn_args})

            def on_tool_result(fn_name: str, success: bool, elapsed_ms: int, digest: str) -> None:
                _emit(
                    {
                        "type": "tool_call_finished",
                        "tool": fn_name,
                        "status": "done" if success else "fail",
                        "elapsed_ms": elapsed_ms,
                        "result": digest,
                    }
                )

            async def _drain_stream() -> None:
                """持续从 queue 取事件发给前端，直到收到 None sentinel。"""
                while True:
                    event = await event_queue.get()  # noqa: B023
                    if event is None:
                        break
                    await websocket.send_json(event)

            # 启动 drain task，与 agent.chat worker 并发
            drain_task = asyncio.create_task(_drain_stream())
            try:
                # agent.chat 在 worker 线程跑，三个回调实时推事件
                addenda = [trading_style_context(style_preset)]
                if page_addendum := page_context_addendum(
                    page_context,
                    get_portfolio_store(),
                    get_watchlist_store(),
                ):
                    addenda.append(page_addendum)
                resp = await asyncio.to_thread(
                    agent.chat,
                    user_message,
                    None,
                    None,
                    session_memory,
                    on_tool_call,
                    on_tool_result,
                    on_chunk,
                    system_addendum="\n\n".join(addenda),
                )
            finally:
                # 通知 drain 结束 + 等 drain 把剩余事件发完
                loop.call_soon_threadsafe(event_queue.put_nowait, None)
                await drain_task
                await security.release_agent()

            # 流式兜底：on_chunk 从未触发（provider 不支持 stream）时，
            # 把非流式兜底文本作为单个 chunk 补发，否则前端会收到空回答。
            if not streamed_any and resp.text:
                await websocket.send_json({"type": "chunk", "text": resp.text})

            await websocket.send_json(
                {
                    "type": "done",
                    "tools_used": [tc.name for tc in resp.tool_calls],
                    "rounds": resp.rounds,
                }
            )

    except WebSocketDisconnect:
        pass
