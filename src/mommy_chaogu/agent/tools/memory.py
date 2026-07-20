"""记忆工具：事件语义搜索、预测历史、市场叙事、记忆上下文。"""

from __future__ import annotations

import logging
from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json

_log = logging.getLogger(__name__)


DEFS: list[ToolDef] = [
    ToolDef(
        name="search_similar_events",
        description=(
            "语义搜索历史事件记忆。用向量检索找与当前情况相似的历史事件，"
            "如'半导体暴跌'或'茅台大涨'。用于复盘'上次类似情况发生了什么'。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索文本，如 '半导体暴跌，主力大幅流出'",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    ),
    ToolDef(
        name="get_prediction_history",
        description=(
            "查询 agent 的历史预测记录及命中状态（hit/missed/pending）。"
            "用于回顾'我之前对某只股票的判断准不准'。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码（可选，按个股过滤），如 '600519'",
                },
                "status": {
                    "type": "string",
                    "enum": ["hit", "missed", "pending"],
                    "description": "按状态过滤（可选）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 10",
                    "default": 10,
                },
            },
        },
    ),
    ToolDef(
        name="get_market_narrative",
        description=(
            "生成过去 N 天的市场脉络叙述（转折点 → 因果链 → 当前状态）。"
            "基于情景记忆中的历史事件，用 LLM 生成复盘分析。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "回顾天数，默认 7",
                    "default": 7,
                }
            },
        },
    ),
    ToolDef(
        name="get_memory_context",
        description=(
            "获取项目积累的历史分析记忆。"
            "返回最近的 episodic events、predictions（含命中率）、semantic knowledge。"
            "在分析个股或板块前调用此工具，获取历史判断和准确率数据。"
            "适用于 MCP 等外部 agent — 内置 agent 已自动注入记忆，不需要手动调。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "查询关键词（如股票名 '茅台'、板块名 '半导体'）",
                },
            },
        },
    ),
]


def _handle_search_similar_events(ctx: ToolContext, args: dict[str, Any]) -> str:
    """语义搜索历史事件。embedding client 不可用时降级为关键词搜索。"""
    if ctx.db_path is None:
        return _json({"error": "记忆系统未配置（db_path is None）"})

    query = args["query"]
    limit = args.get("limit", 5)

    # lazy import 避免循环依赖
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    episodic = EpisodicMemory(ctx.db_path)

    # 有 embedding client → 向量语义搜索
    if ctx.client is not None:
        from mommy_chaogu.agent.vector_search import VectorSearch

        model = ctx.model or "text-embedding-3-small"
        try:
            vs = VectorSearch(episodic, ctx.client, model=model)
            results = vs.search_similar(query, top_k=limit)
            return _json(
                [
                    {
                        "id": r.get("id"),
                        "summary": r.get("summary"),
                        "timestamp": r.get("timestamp"),
                        "score": r.get("distance"),
                        "scope": r.get("scope"),
                    }
                    for r in results
                ]
            )
        except Exception as e:
            _log.warning("search_similar_events: 向量搜索失败，降级关键词搜索: %s", e)

    # 降级：拉最近事件做关键词过滤
    events = episodic.recent(days=90, limit=limit * 10)
    # 中文分词困难，用 2 字滑窗提取关键词
    cleaned = query.replace("，", " ").strip()
    tokens = cleaned.split()
    keywords: list[str] = []
    for token in tokens:
        if len(token) >= 2:
            keywords.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            keywords.append(token)
    if keywords:
        filtered = [
            e
            for e in events
            if any(kw in (e.get("summary") or "") or kw in (e.get("name") or "") for kw in keywords)
        ]
    else:
        filtered = events
    return _json(
        [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "timestamp": e.get("timestamp"),
                "score": None,
                "scope": e.get("scope"),
                "degraded": True,
            }
            for e in filtered[:limit]
        ]
    )


def _handle_get_prediction_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    """查询预测历史，可选按 code / status 过滤。"""
    if ctx.db_path is None:
        return _json({"error": "记忆系统未配置（db_path is None）"})

    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    code = args.get("code")
    status = args.get("status")
    limit = args.get("limit", 10)

    tracker = PredictionTracker(ctx.db_path)
    preds = tracker.all(limit=limit, status=status)

    # all() 不支持 code 过滤，在 Python 层过滤
    if code is not None:
        preds = [p for p in preds if p.get("code") == code]

    return _json(
        [
            {
                "id": p.get("id"),
                "code": p.get("code"),
                "name": p.get("name"),
                "prediction": p.get("prediction"),
                "direction": p.get("direction"),
                "status": p.get("status"),
                "score": p.get("accuracy_score"),
                "created_at": p.get("created_at"),
                "verified_at": p.get("verified_at"),
            }
            for p in preds
        ]
    )


def _handle_get_market_narrative(ctx: ToolContext, args: dict[str, Any]) -> str:
    """生成市场脉络叙述。LLM 不可用时降级为返回事件列表。"""
    if ctx.db_path is None:
        return _json({"error": "记忆系统未配置（db_path is None）"})

    days = args.get("days", 7)

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    episodic = EpisodicMemory(ctx.db_path)

    # 有 LLM client → 生成叙事
    if ctx.client is not None and ctx.model is not None:
        from mommy_chaogu.agent.narrative import MarketNarrative

        try:
            narrative = MarketNarrative(episodic, ctx.client, model=ctx.model)
            text = narrative.generate_narrative(days=days)
            return _json({"narrative": text, "days": days})
        except Exception as e:
            _log.warning("get_market_narrative: LLM 生成失败，降级事件列表: %s", e)

    # 降级：返回最近事件列表
    events = episodic.recent(days=days, limit=50)
    return _json(
        {
            "degraded": True,
            "days": days,
            "events": [
                {
                    "id": e.get("id"),
                    "timestamp": e.get("timestamp"),
                    "event_type": e.get("event_type"),
                    "scope": e.get("scope"),
                    "summary": e.get("summary"),
                }
                for e in events
            ],
        }
    )


def _handle_get_memory_context(ctx: ToolContext, args: dict[str, Any]) -> str:
    """获取记忆上下文（MCP 等外部 agent 用）。"""
    ms = ctx.memory_service
    if ms is None:
        return _json(
            {"error": "记忆服务未配置", "hint": "此工具仅在有记忆服务的入口可用（如 MCP Server）"}
        )

    query = args.get("query")
    context = ms.get_context(query=query)
    stats = ms.stats()

    return _json(
        {
            "context": context,
            "stats": stats,
            "has_memory": ms.has_memory,
        }
    )


HANDLERS: dict[str, ToolHandler] = {
    "search_similar_events": _handle_search_similar_events,
    "get_prediction_history": _handle_get_prediction_history,
    "get_market_narrative": _handle_get_market_narrative,
    "get_memory_context": _handle_get_memory_context,
}
