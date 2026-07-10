"""/api/agent 路由：AI 行情助手对话。

端点：
- POST /api/agent/chat  — 单轮问答（返回完整文本）
- POST /api/agent/route — 尝试工作流路由（返回是否命中 + 结果）
- WS  /ws/agent          — 流式对话（打字机效果，逐字返回）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from mommy_chaogu.web.deps import get_agent_memory, get_agent_service

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


class RouteRequest(BaseModel):
    message: str


class RouteResponse(BaseModel):
    matched: bool
    workflow_id: str = ""
    reply: str = ""
    steps: list[dict[str, Any]] = []


# ---------- REST 端点 ----------


def _get_router() -> Any:
    """懒加载 NLRouter（避免 app 启动时构建 adapter）。"""
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _build() -> Any:
        from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
        from mommy_chaogu.db_paths import AGENT_DB, PORTFOLIO_DB
        from mommy_chaogu.portfolio.store import PortfolioStore
        from mommy_chaogu.watchlist.store import WatchlistStore
        from mommy_chaogu.web.deps import get_adapter
        from mommy_chaogu.workflow.engine import WorkflowExecutor
        from mommy_chaogu.workflow.router import NLRouter

        adapter = get_adapter()
        ctx = ToolContext(
            adapter=adapter,
            watchlist_store=WatchlistStore(PORTFOLIO_DB),
            portfolio_store=PortfolioStore(PORTFOLIO_DB),
            db_path=AGENT_DB,
        )
        tool_registry = ToolRegistry(ctx)

        # 尝试构建 LLM summarizer
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
        return NLRouter(executor=executor)

    return _build()


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
        memory,
    )

    return ChatResponse(
        reply=resp.text,
        tools_used=[tc.name for tc in resp.tool_calls],
        rounds=resp.rounds,
    )


# ---------- WebSocket 端点（流式） ----------


@router.get("/history")
async def get_history(limit: int = 50) -> dict[str, Any]:
    """获取对话历史（从 agent_memory 表）。"""
    memory = get_agent_memory()
    try:
        rows = memory.recent(limit=limit)
        return {"messages": rows, "total": len(rows)}
    except Exception:
        return {"messages": [], "total": 0}


@router.get("/predictions")
async def get_predictions(limit: int = 20) -> dict[str, Any]:
    """获取预测记录。"""
    tracker = get_prediction_tracker_safe()
    if tracker is None:
        return {"predictions": [], "total": 0}
    try:
        rows = tracker.list_recent(limit=limit)  # type: ignore[attr-defined]
        return {"predictions": rows, "total": len(rows)}
    except Exception:
        return {"predictions": [], "total": 0}


def get_prediction_tracker_safe() -> Any:
    """安全获取 prediction tracker（可能未配置）。"""
    try:
        from mommy_chaogu.web.deps import get_prediction_tracker

        return get_prediction_tracker()
    except Exception:
        return None


# NOTE: WebSocket /ws/agent 定义在 ws.py（无 prefix），
# 因为本 router 有 prefix=/api/agent，会导致路径变成 /api/agent/ws/agent。
