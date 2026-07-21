"""/api/agent 路由：AI 行情助手对话。

端点：
- POST /api/agent/chat  — 单轮问答（返回完整文本）
- POST /api/agent/route — 尝试工作流路由（返回是否命中 + 结果）
- WS  /ws/agent          — 流式对话（打字机效果，逐字返回）
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from mommy_chaogu.web.deps import (
    get_adapter,
    get_agent_memory,
    get_agent_service,
    get_portfolio_store,
    get_watchlist_store,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# tracker 缺失或统计异常时的兜底返回（调用方需拷贝，勿原地修改）
_EMPTY_PREDICTION_STATS: dict[str, Any] = {
    "total": 0,
    "pending": 0,
    "hit": 0,
    "missed": 0,
    "expired": 0,
    "unverifiable": 0,
    "hit_rate": 0.0,
}


# ---------- Schemas ----------


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None
    session_id: str = Field(default="web-default", pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str] = []
    rounds: int = 0


class RouteRequest(BaseModel):
    message: str


class RouteResponse(BaseModel):
    matched: bool
    workflow_id: str = ""
    reply: str = ""
    steps: list[dict[str, Any]] = []


# ---------- REST 端点 ----------


@lru_cache(maxsize=1)
def _get_router() -> Any:
    """Build the process-wide router from explicit application dependencies."""
    from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
    from mommy_chaogu.db_paths import AGENT_DB
    from mommy_chaogu.workflow.definitions import get_default_registry
    from mommy_chaogu.workflow.engine import WorkflowExecutor
    from mommy_chaogu.workflow.router import NLRouter

    ctx = ToolContext(
        adapter=get_adapter(),
        watchlist_store=get_watchlist_store(),
        portfolio_store=get_portfolio_store(),
        db_path=AGENT_DB,
    )
    tool_registry = ToolRegistry(ctx)

    llm_summarizer = None
    agent = get_agent_service()
    if agent is not None:

        class _AgentSummarizer:
            def __init__(self, svc: Any) -> None:
                self._svc = svc

            def summarize(self, template: str, context: str) -> str:
                prompt = template.format(context=context)
                resp = self._svc.chat_raw([{"role": "user", "content": prompt}])
                return resp.text

        llm_summarizer = _AgentSummarizer(agent)

    executor = WorkflowExecutor(tool_registry, llm_summarizer=llm_summarizer)
    return NLRouter(get_default_registry(), executor=executor)


@router.post("/route", response_model=RouteResponse)
async def route_message(req: RouteRequest) -> RouteResponse:
    """尝试工作流路由。

    如果命中预定义工作流，执行并返回结果。
    如果未命中，返回 matched=false 让前端 fallback 到 /chat。
    """
    nl_router = _get_router()
    route = nl_router.route(req.message)

    if not route.matched or route.workflow is None:
        return RouteResponse(matched=False)

    result = await asyncio.to_thread(nl_router.execute_route, route, req.message)

    steps_data = [
        {
            "name": s.display_name,
            "tool": s.tool_name,
            "success": s.success,
        }
        for s in result.steps
    ]

    return RouteResponse(
        matched=True,
        workflow_id=route.workflow.id,
        reply=result.summary,
        steps=steps_data,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    agent: Annotated[Any, Depends(get_agent_service)],
    memory: Annotated[Any, Depends(get_agent_memory)],
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
        None,  # history 不单独传，由 memory 提供上下文
        None,  # system_override
        memory.for_session(req.session_id),
    )

    return ChatResponse(
        reply=resp.text,
        tools_used=[tc.name for tc in resp.tool_calls],
        rounds=resp.rounds,
    )


# ---------- WebSocket 端点（流式） ----------


@router.get("/history")
async def get_history(
    session_id: str = Query(default="web-default", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """获取对话历史（从 agent_memory 表）。"""
    memory = get_agent_memory()
    try:
        rows = memory.recent(limit=limit, session_id=session_id)
        return {"messages": rows, "total": len(rows)}
    except Exception:
        return {"messages": [], "total": 0}


@router.get("/predictions")
async def get_predictions(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    """获取预测记录（按 created_at 降序）。"""
    tracker = get_prediction_tracker_safe()
    if tracker is None:
        return {"predictions": [], "total": 0}
    try:
        rows = tracker.all(limit=limit)
        return {"predictions": rows, "total": len(rows)}
    except Exception:
        return {"predictions": [], "total": 0}


@router.get("/predictions/stats")
async def get_prediction_stats() -> dict[str, Any]:
    """获取预测统计（命中率分布，供 Web 预测页顶部统计条用）。

    背后是 PredictionTracker.stats()，无 tracker 或统计异常时返回空统计。
    """
    tracker = get_prediction_tracker_safe()
    if tracker is None:
        return dict(_EMPTY_PREDICTION_STATS)
    try:
        stats = tracker.stats()
        # 确保 hit_rate 是 float（JSON 可序列化）
        stats["hit_rate"] = float(stats.get("hit_rate", 0.0))
        return stats
    except Exception as exc:
        _log.warning("预测统计查询失败，返回空统计: %s", exc)
        return dict(_EMPTY_PREDICTION_STATS)


def get_prediction_tracker_safe() -> Any:
    """安全获取 prediction tracker（可能未配置）。"""
    try:
        from mommy_chaogu.web.deps import get_prediction_tracker

        return get_prediction_tracker()
    except Exception:
        return None


# NOTE: WebSocket /ws/agent 定义在 ws.py（无 prefix），
# 因为本 router 有 prefix=/api/agent，会导致路径变成 /api/agent/ws/agent。
