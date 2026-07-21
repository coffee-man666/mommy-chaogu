"""/ws 路由：WebSocket 实时推送。

端点：
- WS /ws/quotes   — 推送最新报价快照（每 5s）
- WS /ws/signals  — 推送触发的信号（有就推）
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.mappers import signal_to_out, snapshot_to_out

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
    """AI 对话流式 WebSocket（真流式：逐 LLM delta 转发，#4）。

    消息格式（前端零改动，纯累加 chunk.text）：
    - 客户端发: {"message": "...", "history": [...]}
    - 服务端回: {"type": "thinking"} (一次)
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

    from mommy_chaogu.web.deps import get_agent_memory, get_agent_service

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

            user_message = msg.get("message", "").strip()
            if not user_message:
                continue

            session_id = msg.get("session_id", "web-default")
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

            # 真流式：asyncio.Queue 桥接 worker 线程的 on_chunk → 事件循环发送
            loop = asyncio.get_running_loop()
            chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
            streamed_any = False  # on_chunk 是否真的推过 delta（流式不可用时为 False）

            def on_chunk(delta: str) -> None:
                """worker 线程内调用，线程安全地把 delta 推入 asyncio Queue。"""
                nonlocal streamed_any
                streamed_any = True
                loop.call_soon_threadsafe(chunk_queue.put_nowait, delta)  # noqa: B023

            async def _drain_stream() -> None:
                """持续从 queue 取 delta 发给前端，直到收到 None sentinel。"""
                while True:
                    delta = await chunk_queue.get()  # noqa: B023
                    if delta is None:
                        break
                    await websocket.send_json({"type": "chunk", "text": delta})

            # 启动 drain task，与 agent.chat worker 并发
            drain_task = asyncio.create_task(_drain_stream())
            try:
                # agent.chat 在 worker 线程跑，on_chunk 实时推 delta
                resp = await asyncio.to_thread(
                    agent.chat,
                    user_message,
                    None,
                    None,
                    session_memory,
                    None,  # on_tool_call
                    None,  # on_tool_result
                    on_chunk,
                )
            finally:
                # 通知 drain 结束 + 等 drain 把剩余 delta 发完
                loop.call_soon_threadsafe(chunk_queue.put_nowait, None)
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
