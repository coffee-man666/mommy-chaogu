"""记忆工具：事件语义搜索、预测历史、市场叙事、记忆上下文。"""

from __future__ import annotations

import logging
import re
from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _clamp_int, _json

_log = logging.getLogger(__name__)


DEFS: list[ToolDef] = [
    ToolDef(
        name="search_similar_events",
        description=(
            "语义搜索历史事件记忆。用向量检索找与当前情况相似的历史事件，"
            "如'半导体暴跌'或'茅台大涨'。用于复盘'上次类似情况发生了什么'。"
            "（当前 LLM provider 无 embedding 接口时自动降级为关键词搜索，"
            "返回结果带 degraded 标记）"
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
                    "description": "返回条数，默认 5（最大 100）",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query"],
        },
    ),
    ToolDef(
        name="get_prediction_history",
        description=(
            "查询 agent 的历史预测记录及命中状态与阶段。"
            "status（hit/missed/pending）衡量价格方向验证结局；"
            "stage（candidate 候选/confirmed 已确认/retired 已退出）衡量"
            "左侧候选是否等到右侧确认——方向对了（hit）不等于右侧已确认。"
            "用于回顾'我之前记的左侧候选后来怎么样了'。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母，可选，按个股过滤），如 '600519' 或 'AAPL'",
                },
                "status": {
                    "type": "string",
                    "enum": ["hit", "missed", "pending"],
                    "description": "按状态过滤（可选）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 10（最大 100）",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
    ),
    ToolDef(
        name="update_prediction_stage",
        description=(
            "回写预测的阶段（左侧→右侧纪律闭环）。stage 与 status 独立："
            "status 管价格验证结局（verify 自动回填），stage 管心法阶段——"
            "confirmed = 右侧确认信号出现（如 check_kline_signal 的 "
            "high_20_breakout / price_above_ma20 命中，或用户人工判定），"
            "status=hit 本身不升 confirmed；retired = 显式放弃该候选"
            "（右侧迟迟不确认则退出；missed/expired 的自动退出由验证引擎负责）。"
            "basis 必填，写明确认依据（如信号名与数值）或退出原因。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "prediction_id": {
                    "type": "integer",
                    "description": "预测记录 id（get_prediction_history 返回的 id）",
                    "minimum": 1,
                },
                "stage": {
                    "type": "string",
                    "enum": ["confirmed", "retired"],
                    "description": "目标阶段：confirmed（右侧已确认）/ retired（已退出）",
                },
                "basis": {
                    "type": "string",
                    "description": (
                        "确认依据或退出原因，必填。如 'high_20_breakout 命中："
                        "收盘 105 > 20日高点 100' 或 '用户人工判定放弃'"
                    ),
                },
            },
            "required": ["prediction_id", "stage", "basis"],
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
                    "description": "回顾天数，默认 7（最大 365）",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 365,
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
    ToolDef(
        name="get_memory_health",
        description="检查记忆数据库、检索模式和维护任务的最近运行状态。",
        parameters={"type": "object", "properties": {}},
    ),
]


def _handle_search_similar_events(ctx: ToolContext, args: dict[str, Any]) -> str:
    """语义搜索历史事件。embedding client 不可用时降级为关键词搜索。"""
    db_path = ctx.resolved_agent_db
    if db_path is None:
        return _json({"error": "记忆系统未配置（agent_db is None）"})

    query = args["query"]
    limit = _clamp_int(args.get("limit", 5), 5, 1, 100)

    # lazy import 避免循环依赖
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    episodic = EpisodicMemory(db_path)

    # 有 embedding client + 专用 embedding 模型 → 向量语义搜索。
    # embedding_model 为 None 表示 provider 无 embedding 接口，
    # 显式走关键词降级（不能把聊天模型名当 embedding 模型传）。
    if ctx.client is not None and ctx.embedding_model is not None:
        from mommy_chaogu.agent.vector_search import VectorSearch

        try:
            vs = VectorSearch(episodic, ctx.client, model=ctx.embedding_model)
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

    # 降级：拉最近事件做关键词过滤。股票代码必须完整匹配，禁止数字滑窗。
    events = episodic.recent(days=90, limit=limit * 10)
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(query), flags=re.UNICODE).strip()
    tokens: list[str] = []
    for token in cleaned.split():
        if len(token) < 2:
            continue
        if token.isdigit():
            tokens.append(token)
        elif re.search(r"[\u4e00-\u9fff]", token):
            tokens.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            tokens.append(token)
    if tokens:
        filtered = [
            e
            for e in events
            if any(
                (kw.isdigit() and str(e.get("code") or "") == kw)
                or (
                    not kw.isdigit()
                    and (kw in (e.get("summary") or "") or kw in (e.get("name") or ""))
                )
                for kw in tokens
            )
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
    db_path = ctx.resolved_agent_db
    if db_path is None:
        return _json({"error": "记忆系统未配置（agent_db is None）"})

    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    code = args.get("code")
    status = args.get("status")
    limit = _clamp_int(args.get("limit", 10), 10, 1, 100)

    tracker = PredictionTracker(db_path)
    # code/status 过滤在 SQL 层下推：先截断后过滤会漏掉不在最近 N 条内的冷门股记录
    preds = tracker.all(limit=limit, status=status, code=code)

    return _json(
        [
            {
                "id": p.get("id"),
                "code": p.get("code"),
                "name": p.get("name"),
                "prediction": p.get("prediction"),
                "direction": p.get("direction"),
                "status": p.get("status"),
                "stage": p.get("stage") or "candidate",
                "score": p.get("accuracy_score"),
                "created_at": p.get("created_at"),
                "confirmed_at": p.get("confirmed_at"),
                "verified_at": p.get("verified_at"),
            }
            for p in preds
        ]
    )


def _handle_update_prediction_stage(ctx: ToolContext, args: dict[str, Any]) -> str:
    """回写预测阶段（confirmed/retired），basis 必填并留痕到 verify_log。"""
    db_path = ctx.resolved_agent_db
    if db_path is None:
        return _json({"error": "记忆系统未配置（agent_db is None）"})

    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    raw_id = args.get("prediction_id")
    if raw_id is None:
        return _json({"error": "prediction_id 必须是整数"})
    try:
        pred_id = int(raw_id)
    except (TypeError, ValueError):
        return _json({"error": "prediction_id 必须是整数"})
    if pred_id < 1:
        return _json({"error": "prediction_id 必须是正整数"})
    stage = str(args.get("stage") or "")
    basis = str(args.get("basis") or "").strip()
    if not basis:
        return _json({"error": "basis 必填：写明确认依据（右侧信号命中数值）或退出原因"})

    tracker = PredictionTracker(db_path)
    try:
        row = tracker.update_stage(pred_id, stage, note=basis)
    except ValueError as e:
        return _json({"error": str(e)})
    if row is None:
        return _json({"error": f"预测 #{pred_id} 不存在"})
    return _json(
        {
            "id": row.get("id"),
            "code": row.get("code"),
            "name": row.get("name"),
            "stage": row.get("stage"),
            "status": row.get("status"),
            "confirmed_at": row.get("confirmed_at"),
            "verified_at": row.get("verified_at"),
            "basis": basis,
        }
    )


def _handle_get_market_narrative(ctx: ToolContext, args: dict[str, Any]) -> str:
    """生成市场脉络叙述。LLM 不可用时降级为返回事件列表。"""
    db_path = ctx.resolved_agent_db
    if db_path is None:
        return _json({"error": "记忆系统未配置（agent_db is None）"})

    days = _clamp_int(args.get("days", 7), 7, 1, 365)

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    episodic = EpisodicMemory(db_path)

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
    structured = getattr(ms, "get_structured_context", None)
    if callable(structured):
        context = structured(query=query, tool_context=ctx)
    else:
        context = {"legacy_prompt": ms.get_context(query=query)}
    stats = ms.stats()

    return _json(
        {
            "context": context,
            "stats": stats,
            "has_memory": ms.has_memory,
        }
    )


def _handle_get_memory_health(ctx: ToolContext, _args: dict[str, Any]) -> str:
    """返回健康状态；无 LLM 时明确说明降级而不是报告故障。"""
    ms = ctx.memory_service
    if ms is not None and callable(getattr(ms, "health", None)):
        return _json(ms.health())
    db_path = ctx.resolved_agent_db
    if db_path is None:
        return _json({"status": "disabled", "reason": "记忆数据库未配置"})
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    summary = EpisodicMemory(db_path).summary()
    return _json(
        {
            "status": "degraded",
            "reason": "memory service 未装配",
            "episodic_count": summary["total"],
            "retrieval_mode": "exact+keyword",
        }
    )


HANDLERS: dict[str, ToolHandler] = {
    "search_similar_events": _handle_search_similar_events,
    "get_prediction_history": _handle_get_prediction_history,
    "update_prediction_stage": _handle_update_prediction_stage,
    "get_market_narrative": _handle_get_market_narrative,
    "get_memory_context": _handle_get_memory_context,
    "get_memory_health": _handle_get_memory_health,
}
