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


@router.websocket("/ws/quotes")
async def ws_quotes(
    websocket: WebSocket,
    service: Annotated[BackgroundService, Depends(get_service)],
) -> None:
    """报价快照推送。"""
    await websocket.accept()
    service.add_quote_subscriber(websocket)  # type: ignore[arg-type]
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
    await websocket.accept()
    service.add_signal_subscriber(websocket)  # type: ignore[arg-type]
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
    """AI 对话流式 WebSocket。

    消息格式：
    - 客户端发: {"message": "...", "history": [...]}
    - 服务端回: {"type": "thinking"} (一次)
    - 服务端回: {"type": "chunk", "text": "..."} (多次)
    - 服务端回: {"type": "done", "tools_used": [...], "rounds": N}
    """
    import asyncio
    import json

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

            # agent.chat 是同步的，用 to_thread 包装
            resp = await asyncio.to_thread(agent.chat, user_message, None, None, memory)

            # 分段发送（小段快发）
            text = resp.text
            chunk_size = 12
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                await websocket.send_json({"type": "chunk", "text": chunk})
                await asyncio.sleep(0.01)

            await websocket.send_json(
                {
                    "type": "done",
                    "tools_used": [tc.name for tc in resp.tool_calls],
                    "rounds": resp.rounds,
                }
            )

    except WebSocketDisconnect:
        pass
