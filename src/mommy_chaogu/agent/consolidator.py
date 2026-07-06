"""语义记忆提炼：从情景记忆 + 预测验证中归纳知识。

离线任务（cron 每周跑一次），从 episodic_events 和 predictions 表中：
1. 提炼板块叙事（sector_thesis）
2. 判断市场状态（market_regime）
3. 归纳重复规律（pattern_observed）

知识写入 semantic_knowledge 表，confidence 由预测命中率校准。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

_log = logging.getLogger(__name__)


_SECTOR_THESIS_PROMPT = """\
基于以下关于「{scope}」的事件记录，提炼核心叙事。

事件（按时间排序）:
{events_text}

要求：
1. 提炼 1-2 句话的核心叙事（这个板块/股票的核心逻辑是什么？）
2. 如果叙事与之前不同或矛盾，明确标注变化
3. 不要罗列事件，要归纳

输出格式：直接输出叙事文本，不要加标题或列表。
"""


_MARKET_REGIME_PROMPT = """\
基于以下市场事件，判断当前市场状态。

最近 5 天事件:
{recent_text}

之前 10 天事件:
{prior_text}

要求：
1. 用 1-2 句话描述当前市场状态（如"牛市/熊市/震荡/高低切"）
2. 如果与之前状态不同，标注变化

输出格式：直接输出状态描述。
"""


_PATTERN_PROMPT = """\
从以下预测记录中归纳规律。

预测（含验证结果）:
{predictions_text}

要求：
1. 找出哪些类型的预测命中率高/低
2. 归纳出可复用的规律（如"flow_signal 类 bullish 在 5d 内命中率 70%"）
3. 如果样本不足（<3 条），返回"样本不足"

输出格式：直接输出规律描述。
"""


class MemoryConsolidator:
    """从情景记忆提炼语义记忆的离线任务。

    用法::

        cons = MemoryConsolidator(episodic, semantic, tracker, client, "deepseek-chat")
        cons.consolidate_all()
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        tracker: PredictionTracker,
        client: Any,
        model: str,
    ) -> None:
        self._episodic = episodic
        self._semantic = semantic
        self._tracker = tracker
        self._client = client
        self._model = model

    def consolidate_all(self) -> dict[str, int]:
        """全量提炼（每周跑一次）。

        Returns:
            {"sector_theses": N, "market_regime": M, "patterns": K}
        """
        results: dict[str, int] = {
            "sector_theses": 0,
            "market_regime": 0,
            "patterns": 0,
        }

        # 提炼板块叙事
        try:
            n = self._consolidate_sector_theses()
            results["sector_theses"] = n
        except Exception as e:
            _log.warning("consolidate sector_theses failed: %s", e)

        # 判断市场状态
        try:
            n = self._consolidate_market_regime()
            results["market_regime"] = n
        except Exception as e:
            _log.warning("consolidate market_regime failed: %s", e)

        # 归纳规律
        try:
            n = self._consolidate_patterns()
            results["patterns"] = n
        except Exception as e:
            _log.warning("consolidate patterns failed: %s", e)

        # 校准置信度
        try:
            self._recalibrate_confidence()
        except Exception as e:
            _log.warning("recalibrate confidence failed: %s", e)

        # 生成周期复盘摘要
        try:
            self._save_insight_summary()
        except Exception as e:
            _log.warning("save insight summary failed: %s", e)

        _log.info("consolidate_all: %s", results)
        return results

    def _consolidate_sector_theses(self, days: int = 14) -> int:
        """提炼板块叙事（sector_thesis + stock_insight）。

        从过去 N 天的事件中，按 scope 分组，用 LLM 提炼叙事。

        Returns:
            新增的知识条数
        """
        events = self._episodic.recent(days=days, limit=200)

        # 按 scope 分组
        by_scope: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            scope = e.get("scope", "")
            if scope and scope != "market":
                by_scope.setdefault(scope, []).append(e)

        count = 0
        for scope, scoped_events in by_scope.items():
            if len(scoped_events) < 2:
                continue  # 事件太少不提炼

            events_text = self._format_events(scoped_events)
            prompt = _SECTOR_THESIS_PROMPT.format(scope=scope, events_text=events_text)

            content = self._llm_call(prompt, temperature=0.5)
            if not content or len(content) < 5:
                continue

            knowledge_type = "stock_insight" if scope.startswith("stock:") else "sector_thesis"
            self._semantic.upsert(
                knowledge_type=knowledge_type,
                scope=scope,
                content=content,
                confidence=0.7,
                source_ids=[e["id"] for e in scoped_events],
            )
            count += 1

        return count

    def _consolidate_market_regime(self) -> int:
        """判断当前市场状态。

        Returns:
            1 if written, 0 if skipped
        """
        now = datetime.now(UTC)
        recent = self._episodic.recent(days=5, scope="market", limit=30)

        prior = self._episodic.query(
            scope="market",
            start_date=(now - timedelta(days=15)).strftime("%Y-%m-%d"),
            end_date=(now - timedelta(days=5)).strftime("%Y-%m-%d"),
            limit=50,
        )

        if not recent:
            return 0

        prompt = _MARKET_REGIME_PROMPT.format(
            recent_text=self._format_events(recent),
            prior_text=self._format_events(prior) or "（无事件）",
        )

        content = self._llm_call(prompt, temperature=0.3)
        if not content or len(content) < 5:
            return 0

        self._semantic.upsert(
            knowledge_type="market_regime",
            scope="market",
            content=content,
            confidence=0.6,
            source_ids=[e["id"] for e in recent],
        )
        return 1

    def _consolidate_patterns(self) -> int:
        """从预测验证结果中归纳规律。

        Returns:
            新增规律条数
        """
        stats = self._tracker.stats()
        total = stats.get("total", 0)
        if total < 5:
            _log.info("patterns: only %d predictions, skipping", total)
            return 0

        # 获取所有已验证预测
        verified = []
        for status in ("hit", "missed"):
            verified.extend(self._tracker.all(limit=50, status=status))

        if len(verified) < 5:
            return 0

        predictions_text = self._format_predictions(verified)
        prompt = _PATTERN_PROMPT.format(predictions_text=predictions_text)

        content = self._llm_call(prompt, temperature=0.3)
        if not content or "样本不足" in content:
            return 0

        self._semantic.upsert(
            knowledge_type="pattern_observed",
            scope="market",
            content=content,
            confidence=0.7,
        )
        return 1

    def _recalibrate_confidence(self) -> None:
        """根据预测命中率校准知识置信度。

        对每条 active 知识，查找关联的 predictions（通过 source_event_ids），
        计算命中率并更新 confidence。
        """
        active_knowledge = self._semantic.get_active(limit=50)

        updates: list[dict[str, Any]] = []

        for knowledge in active_knowledge:
            source_ids = knowledge.get("source_event_ids", [])
            if not source_ids or len(source_ids) < 2:
                continue

            # 通过 source_event_ids 找关联的 predictions
            related_preds: list[dict[str, Any]] = []
            for eid in source_ids:
                event = self._episodic.get_by_id(eid)
                if event and event.get("prediction_id"):
                    pred = self._tracker.get_by_id(event["prediction_id"])
                    if pred:
                        related_preds.append(pred)

            if len(related_preds) < 3:
                continue  # 样本太少不校准

            hits = sum(1 for p in related_preds if p.get("status") == "hit")
            misses = sum(1 for p in related_preds if p.get("status") == "missed")
            total = hits + misses
            if total == 0:
                continue

            hit_rate = hits / total
            updates.append(
                {
                    "entry_id": knowledge["id"],
                    "hit_rate": hit_rate,
                    "hit_count": hits,
                    "miss_count": misses,
                }
            )

        if updates:
            self._semantic.recalibrate(updates)
            _log.info("recalibrated %d knowledge entries", len(updates))

    def _save_insight_summary(self) -> int:
        """汇总本次提炼结果，写入一条 insight_summary 周期复盘。

        Returns:
            写入的 insight_summary id，0 表示未写入
        """
        now = datetime.now(UTC)
        period_end = now.strftime("%Y-%m-%d")
        period_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        stats = self._tracker.stats()
        predictions_reviewed = stats.get("hit", 0) + stats.get("missed", 0)
        hit_rate = stats.get("hit_rate", 0.0)

        # 收集本周新增的 active 知识，作为关键观察
        knowledge = self._semantic.get_active(limit=10)
        key_observations: list[str] = []
        for k in knowledge:
            scope = k.get("scope", "")
            content = k.get("content", "")
            ktype = k.get("knowledge_type", "")
            key_observations.append(f"[{ktype}] {scope}：{content[:80]}")

        summary_parts: list[str] = []
        if predictions_reviewed > 0:
            summary_parts.append(f"本周复盘 {predictions_reviewed} 条预测，命中率 {hit_rate:.0%}。")
        if knowledge:
            summary_parts.append(f"沉淀 {len(knowledge)} 条知识。")
        summary_text = " ".join(summary_parts) or "本周无足够数据生成复盘。"

        # 置信度调整方向：命中率高于 0.5 上调，低于则下调
        confidence_adjustment = (hit_rate - 0.5) * 0.2 if predictions_reviewed > 0 else 0.0

        return self._semantic.save_insight(
            {
                "period_start": period_start,
                "period_end": period_end,
                "summary": summary_text,
                "key_observations": key_observations,
                "predictions_reviewed": predictions_reviewed,
                "hit_rate": hit_rate if predictions_reviewed > 0 else None,
                "confidence_adjustment": confidence_adjustment,
            }
        )

    def _llm_call(self, prompt: str, temperature: float = 0.3) -> str:
        """调用 LLM，返回文本。失败返回空字符串。"""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是投资知识提炼助手。从市场事件中归纳出简洁的知识。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            _log.warning("consolidator LLM call failed: %s", e)
            return ""

    @staticmethod
    def _format_events(events: list[dict[str, Any]]) -> str:
        """格式化事件列表。"""
        lines: list[str] = []
        for e in events:
            ts = e.get("timestamp", "")[:10]
            summary = e.get("summary", "")
            lines.append(f"- [{ts}] {summary}")
        return "\n".join(lines)

    @staticmethod
    def _format_predictions(preds: list[dict[str, Any]]) -> str:
        """格式化预测列表。"""
        lines: list[str] = []
        for p in preds:
            code = p.get("code", "")
            direction = p.get("direction", "")
            status = p.get("status", "")
            pred_text = (p.get("prediction") or "")[:50]
            score = p.get("accuracy_score", 0)
            lines.append(f"- {code} {direction} '{pred_text}' → {status} (score {score})")
        return "\n".join(lines)
