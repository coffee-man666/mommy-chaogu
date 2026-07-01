"""/api/agent 路由：AI 行情助手对话。

端点：
- POST /api/agent/chat  — 单轮问答（返回完整文本）
- WS  /ws/agent          — 流式对话（打字机效果，逐字返回）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from mommy_chaogu.web.deps import get_agent_service

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ---------- Schemas ----------


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str] = []
    rounds: int = 0


# ---------- REST 端点 ----------


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    agent: Annotated[Any, Depends(get_agent_service)],
) -> ChatResponse:
    """单轮问答。

    如果 agent 未配置（无 API key），返回降级提示。
    """
    if agent is None:
        return ChatResponse(
            reply="AI 助手未配置。请在服务端设置 DEEPSEEK_API_KEY 环境变量。",
            tools_used=[],
            rounds=0,
        )

    # AgentService.chat 是同步的（内部调 OpenAI SDK），用 to_thread 包装
    resp = await asyncio.to_thread(
        agent.chat,
        req.message,
        req.history,
    )

    return ChatResponse(
        reply=resp.text,
        tools_used=[tc.name for tc in resp.tool_calls],
        rounds=resp.rounds,
    )


# ---------- WebSocket 端点（流式） ----------


@router.websocket("/ws/agent")
async def agent_ws(
    websocket: WebSocket,
) -> None:
    """流式对话 WebSocket。

    消息格式：
    - 客户端发: {"message": "...", "history": [...]}
    - 服务端回: {"type": "chunk", "text": "..."} (多次)
    - 服务端回: {"type": "done", "tools_used": [...], "rounds": N}
    """
    await websocket.accept()

    # lazy import 避免 app 启动时拉 OpenAI
    from mommy_chaogu.web.deps import get_agent_service

    agent = get_agent_service()

    try:
        while True:
            raw = await websocket.receive_text()

            import json

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "无效的 JSON"})
                continue

            user_message = msg.get("message", "").strip()
            if not user_message:
                continue

            if agent is None:
                await websocket.send_json({
                    "type": "done",
                    "text": "AI 助手未配置。",
                    "tools_used": [],
                    "rounds": 0,
                })
                continue

            # 同步调用 agent → to_thread
            history = msg.get("history")

            # 先发一个 "thinking" 状态
            await websocket.send_json({"type": "thinking"})

            resp = await asyncio.to_thread(agent.chat, user_message, history)

            # 分段发送（模拟流式效果，每 ~50 字一段）
            text = resp.text
            chunk_size = 50
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                await websocket.send_json({"type": "chunk", "text": chunk})
                await asyncio.sleep(0.03)  # 30ms 间隔

            await websocket.send_json({
                "type": "done",
                "tools_used": [tc.name for tc in resp.tool_calls],
                "rounds": resp.rounds,
            })

    except WebSocketDisconnect:
        pass
