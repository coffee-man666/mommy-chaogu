"""动态 system prompt 构建：注入历史事件 + 验证结果 + 已有知识。

当 episodic / tracker / semantic 为 None 或空时，返回原始 SYSTEM_PROMPT（完全向后兼容）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mommy_chaogu.agent.prompt import SYSTEM_PROMPT

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.agent.vector_search import VectorSearch

_log = logging.getLogger(__name__)


def build_system_prompt(
    episodic: EpisodicMemory | None = None,
    tracker: PredictionTracker | None = None,
    semantic: SemanticMemory | None = None,
    query: str | None = None,
    vector_search: VectorSearch | None = None,
) -> str:
    """构建动态 system prompt。

    在基础分析原则后追加：
    1. ## 已有认知 — 活跃的语义知识（板块叙事/市场状态/规律）
    2. ## 近期事件 — 最近 7 天的关键事件摘要（≤10 条）
    3. ## 最近判断回顾 — 最近 5 条验证结果
    4. ## 相似历史事件 — 与当前 query 语义最相近的 Top-3 历史事件（需提供 query + vector_search）

    如果都为空，返回原始 SYSTEM_PROMPT。
    """
    prompt = SYSTEM_PROMPT

    # 注入最近复盘摘要（放在最前，作为整体反思上下文）
    if semantic is not None:
        insight_text = _format_latest_insight(semantic)
        if insight_text:
            prompt += f"\n\n{insight_text}\n"

    # 注入语义知识（最重要，放在最前）
    if semantic is not None:
        knowledge_text = _format_active_knowledge(semantic)
        if knowledge_text:
            prompt += f"\n\n## 已有认知（经验沉淀）\n{knowledge_text}\n"

    # 注入近期事件
    if episodic is not None:
        events_text = _format_recent_events(episodic)
        if events_text:
            prompt += f"\n\n## 近期事件（过去 7 天）\n{events_text}\n"

    # 注入判断回顾
    if tracker is not None:
        calls_text = _format_recent_calls(tracker)
        if calls_text:
            prompt += f"\n\n## 最近判断回顾\n{calls_text}\n"

    # 注入相似历史事件（向量检索）
    if query and vector_search is not None:
        similar_text = _format_similar_events(vector_search, query)
        if similar_text:
            prompt += f"\n\n## 相似历史事件\n{similar_text}\n"

    return prompt


def _format_latest_insight(semantic: SemanticMemory) -> str:
    """格式化最近一条周期复盘为 prompt 文本，无则返回空串。"""
    try:
        insight = semantic.get_latest_insight()
    except Exception as e:
        _log.warning("build_prompt: failed to get latest insight: %s", e)
        return ""

    if not insight:
        return ""

    period_start = insight.get("period_start", "")
    period_end = insight.get("period_end", "")
    summary = insight.get("summary", "")
    hit_rate = insight.get("hit_rate")
    reviewed = insight.get("predictions_reviewed", 0)
    observations = insight.get("key_observations") or []

    lines: list[str] = [f"## 最近复盘（{period_start} ~ {period_end}）"]
    if summary:
        lines.append(summary)
    if hit_rate is not None and reviewed > 0:
        lines.append(f"验证预测 {reviewed} 条，命中率 {hit_rate:.0%}。")
    for obs in observations:
        lines.append(f"- {obs}")
    return "\n".join(lines)


def _format_active_knowledge(semantic: SemanticMemory) -> str:
    """格式化活跃的语义知识为 prompt 文本。"""
    try:
        knowledge = semantic.get_active(limit=10)
    except Exception as e:
        _log.warning("build_prompt: failed to get active knowledge: %s", e)
        return ""

    if not knowledge:
        return ""

    lines: list[str] = []
    for entry in knowledge:
        scope = entry.get("scope", "")
        content = entry.get("content", "")
        confidence = entry.get("confidence", 0.5)
        ktype = entry.get("knowledge_type", "")

        # 按类型给标签
        type_label = {
            "sector_thesis": "板块",
            "stock_insight": "个股",
            "market_regime": "市场",
            "pattern_observed": "规律",
        }.get(ktype, ktype)

        # 截断过长的知识
        content_short = content[:80] if len(content) > 80 else content
        lines.append(f"- [{type_label}] {scope}：{content_short}（置信度 {confidence:.0%}）")

    return "\n".join(lines)


def _format_recent_events(episodic: EpisodicMemory) -> str:
    """格式化近期事件为 prompt 文本。"""
    try:
        events = episodic.recent(days=7, limit=10)
    except Exception as e:
        _log.warning("build_prompt: failed to get recent events: %s", e)
        return ""

    if not events:
        return ""

    lines: list[str] = []
    for event in events:
        ts = event.get("timestamp", "")
        date_str = ts[:10] if ts else ""
        summary = event.get("summary", "")
        lines.append(f"- [{date_str}] {summary}")

    return "\n".join(lines)


def _format_recent_calls(tracker: PredictionTracker) -> str:
    """格式化最近验证结果为 prompt 文本。"""
    try:
        verified = tracker.recent_verified(limit=5)
    except Exception as e:
        _log.warning("build_prompt: failed to get recent calls: %s", e)
        return ""

    if not verified:
        return ""

    lines: list[str] = []
    for pred in verified:
        status = pred.get("status", "")
        prediction = pred.get("prediction", "")
        code = pred.get("code", "")
        name = pred.get("name", "") or ""

        if status == "hit":
            emoji = "✅ 印证"
        elif status == "missed":
            emoji = "❌ 失误"
        else:
            emoji = f"⚪ {status}"

        # 截断过长的 prediction 文本
        pred_short = prediction[:50] if len(prediction) > 50 else prediction
        lines.append(f"- {code} {name}：{pred_short} → {emoji}")

    return "\n".join(lines)


def _format_similar_events(vector_search: VectorSearch, query: str) -> str:
    """格式化向量检索到的相似历史事件为 prompt 文本。

    任何异常（embedding client 不可用 / sqlite-vec 未安装 / 查询失败）
    都会被捕获并静默降级——只记 warning 日志，返回空串不注入。
    """
    try:
        results = vector_search.search_similar(query, top_k=3)
    except Exception as e:
        _log.warning("build_prompt: vector search failed, degrading: %s", e)
        return ""

    if not results:
        return ""

    lines: list[str] = []
    for event in results:
        ts = event.get("timestamp", "")
        date_str = ts[:10] if ts else ""
        scope = event.get("scope", "")
        summary = event.get("summary", "")
        # 截断过长的 summary
        summary_short = summary[:80] if len(summary) > 80 else summary
        scope_part = f"[{scope}] " if scope else ""
        lines.append(f"- [{date_str}] {scope_part}{summary_short}")

    return "\n".join(lines)
