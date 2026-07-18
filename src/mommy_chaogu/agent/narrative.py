"""市场脉络生成：基于情景记忆生成叙事分析。

从 episodic_events 中拉取历史事件，用 LLM 生成：
- generate_narrative(): 过去 N 天的市场叙事（转折点 → 因果链 → 当前状态）
- detect_changes(): 最近 3 天 vs 之前 10 天的关键变化
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

_log = logging.getLogger(__name__)


_NARRATIVE_PROMPT = """\
基于以下事件，生成一段市场脉络叙述。

事件（按时间排序，最早在前）:
{events_text}

要求：
1. 提炼主线（如"科技股高低切""流动性收紧"）
2. 标注关键转折点（日期 + 事件）
3. 因果链：A 发生 → 导致 B
4. 当前状态总结（1-2 句）
5. 控制在 300 字以内
6. 用自然语言，不要列表格式
"""


_CHANGES_PROMPT = """\
对比最近 3 天 vs 之前 10 天的事件，找出关键变化。

最近 3 天:
{recent_text}

之前 10 天:
{prior_text}

要求：
1. 只输出"变了什么"（不是罗列所有事件）
2. 最多 5 条变化
3. 每条格式：[变化维度] 之前是 X，现在变成 Y
4. 如果没有明显变化，返回"无明显变化"
"""


class MarketNarrative:
    """基于情景记忆生成市场脉络分析。

    用法::

        narrative = MarketNarrative(episodic, agent_client, model="deepseek-chat")
        text = narrative.generate_narrative(days=30)
        changes = narrative.detect_changes()
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        client: Any,
        model: str,
    ) -> None:
        self._episodic = episodic
        self._client = client
        self._model = model

    def generate_narrative(
        self,
        scope: str = "market",
        days: int = 30,
    ) -> str:
        """生成一段市场脉络叙述。

        Args:
            scope: 检索范围（"market" / "sector:创新药" / "stock:603662"）
            days: 回溯天数

        Returns:
            脉络叙述文本（~300 字）
        """
        events = self._episodic.recent(days=days, scope=scope, limit=50)

        if not events:
            return f"（过去 {days} 天没有 {scope} 的记录）"

        events_text = self._format_events(events)
        prompt = _NARRATIVE_PROMPT.format(events_text=events_text)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是投资复盘助手，擅长从历史事件中提炼市场脉络。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            _log.warning("narrative: LLM 调用失败: %s", e)
            return f"（生成失败: {e}）"

    def detect_changes(self, scope: str = "market") -> str:
        """检测最近 3 天 vs 之前 10 天的关键变化。

        Args:
            scope: 检索范围

        Returns:
            变化描述文本
        """
        now = datetime.now(UTC)

        recent_events = self._episodic.recent(days=3, scope=scope, limit=30)

        # 之前 10 天（排除最近 3 天）
        prior_raw = self._episodic.query(
            scope=scope,
            start_date=(now - timedelta(days=13)).strftime("%Y-%m-%d"),
            end_date=(now - timedelta(days=3)).strftime("%Y-%m-%d"),
            limit=50,
        )

        if not recent_events and not prior_raw:
            return "（数据不足，无法对比）"

        recent_text = self._format_events(recent_events)
        prior_text = self._format_events(prior_raw)

        prompt = _CHANGES_PROMPT.format(
            recent_text=recent_text or "（无事件）",
            prior_text=prior_text or "（无事件）",
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是投资复盘助手，擅长检测市场状态变化。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            _log.warning("detect_changes: LLM 调用失败: %s", e)
            return f"（检测失败: {e}）"

    def compare_periods(
        self,
        scope: str,
        date1: str,
        date2: str,
    ) -> dict[str, Any]:
        """对比两个时间点的事件数据。

        Args:
            scope: 检索范围
            date1: 第一个日期 (YYYY-MM-DD)
            date2: 第二个日期

        Returns:
            {"date1_events": [...], "date2_events": [...], "summary": "..."}
        """
        events1 = self._episodic.query(scope=scope, start_date=date1, end_date=date1, limit=50)
        events2 = self._episodic.query(scope=scope, start_date=date2, end_date=date2, limit=50)

        return {
            "date1": date1,
            "date2": date2,
            "date1_events": len(events1),
            "date2_events": len(events2),
            "date1_summaries": [e.get("summary", "") for e in events1],
            "date2_summaries": [e.get("summary", "") for e in events2],
        }

    @staticmethod
    def _format_events(events: list[dict[str, Any]]) -> str:
        """格式化事件列表为 prompt 文本。"""
        lines: list[str] = []
        for e in events:
            ts = e.get("timestamp", "")[:10]
            etype = e.get("event_type", "")
            summary = e.get("summary", "")
            lines.append(f"- [{ts}] ({etype}) {summary}")
        return "\n".join(lines)
