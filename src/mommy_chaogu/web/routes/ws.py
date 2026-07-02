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
