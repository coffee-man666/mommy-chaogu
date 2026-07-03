"""动态 system prompt 构建：注入历史事件 + 验证结果回顾。

当 episodic / tracker 为 None 或空时，返回原始 SYSTEM_PROMPT（完全向后兼容）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mommy_chaogu.agent.prompt import SYSTEM_PROMPT

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

_log = logging.getLogger(__name__)


def build_system_prompt(
    episodic: EpisodicMemory | None = None,
    tracker: PredictionTracker | None = None,
) -> str:
    """构建动态 system prompt。

    在基础分析原则后追加：
    1. ## 近期事件 — 最近 7 天的关键事件摘要（≤10 条）
    2. ## 最近判断回顾 — 最近 5 条验证结果

    如果都为空，返回原始 SYSTEM_PROMPT。
    """
    prompt = SYSTEM_PROMPT

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

    return prompt


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
