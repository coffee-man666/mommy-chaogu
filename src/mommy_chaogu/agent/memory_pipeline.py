"""记忆系统统一管道：把零散的记忆组件调用封装成一行代码接入的 facade。

任何分析入口（回测 / 对话 / report）都可以用 ``MemoryPipeline`` 统一接入
episodic + tracker + semantic 三层记忆，而不必关心各自的调用顺序与降级逻辑::

    pipe = MemoryPipeline(episodic, tracker, semantic, client=client, model="deepseek-chat")
    prompt = pipe.build_prompt(query="柯力传感")
    # ... 用 prompt 做 LLM 分析 ...
    pipe.record_analysis(user_msg, assistant_resp, adapter=adapter)
    pipe.verify_predictions(adapter)
    pipe.consolidate()
    snapshot = pipe.stats()

设计原则（与单模块保持一致）：
- 所有记忆组件都是可选的（``None`` 时对应能力静默降级）；
- ``client`` 为 ``None`` 时不调 LLM（extract / consolidate 直接跳过）；
- 任何异常都不向上抛，只记 warning 日志，保证主分析流程不被记忆系统阻塞。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from mommy_chaogu.agent.consolidator import MemoryConsolidator
from mommy_chaogu.agent.extractor import extract_from_conversation, store_extraction
from mommy_chaogu.agent.prompt_builder import build_system_prompt
from mommy_chaogu.agent.verify_engine import verify_pending

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.agent.vector_search import VectorSearch
    from mommy_chaogu.market_data.adapter import MarketDataAdapter

_log = logging.getLogger(__name__)


class MemoryPipeline:
    """记忆系统统一管道：构建 prompt → [分析] → 提取存储 → 验证 → 提炼。

    所有组件均可选，传 ``None`` 即对应能力降级。
    """

    def __init__(
        self,
        episodic: EpisodicMemory | None,
        tracker: PredictionTracker | None,
        semantic: SemanticMemory | None,
        vector_search: VectorSearch | None = None,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self._episodic = episodic
        self._tracker = tracker
        self._semantic = semantic
        self._vector_search = vector_search
        self._client = client
        self._model = model

    # ------------------------------------------------------------------
    # 1. 构建 prompt
    # ------------------------------------------------------------------

    def build_prompt(self, query: str | None = None) -> str:
        """构建注入了记忆的 system prompt。

        调 :func:`build_system_prompt`，把 episodic / tracker / semantic /
        vector_search + query 一并注入。所有组件为 ``None`` 时返回基础
        ``SYSTEM_PROMPT``（向后兼容）。
        """
        return build_system_prompt(
            episodic=self._episodic,
            tracker=self._tracker,
            semantic=self._semantic,
            query=query,
            vector_search=self._vector_search,
        )

    # ------------------------------------------------------------------
    # 2. 记录分析（事实抽取）
    # ------------------------------------------------------------------

    def record_analysis(
        self,
        user_msg: str,
        assistant_response: str,
        adapter: MarketDataAdapter | None = None,
    ) -> None:
        """对话结束后从 (user, assistant) 中抽取 observations / predictions 并落库。

        - ``client`` 为 ``None`` → 跳过（不调 LLM）；
        - episodic 或 tracker 为 ``None`` → 跳过（无落库目标）；
        - 抽取 / 落库任何异常 → 静默降级（log warning）。
        """
        if self._client is None or self._model is None:
            _log.debug("record_analysis: no LLM client/model, skipping extraction")
            return
        if self._episodic is None or self._tracker is None:
            _log.debug("record_analysis: episodic/tracker missing, skipping")
            return

        try:
            extraction = extract_from_conversation(
                user_msg, assistant_response, self._client, self._model
            )
        except Exception as e:
            _log.warning("record_analysis: extract_from_conversation failed: %s", e)
            return

        if extraction is None:
            return

        try:
            store_extraction(extraction, self._episodic, self._tracker, adapter)
        except Exception as e:
            _log.warning("record_analysis: store_extraction failed: %s", e)

    # ------------------------------------------------------------------
    # 3. 验证预测
    # ------------------------------------------------------------------

    def verify_predictions(
        self,
        adapter: MarketDataAdapter,
        cache_store: Any | None = None,
    ) -> dict[str, int]:
        """验证所有到期的 pending 预测，返回统计 dict。

        tracker 为 ``None`` → 返回空统计（全 0）。
        """
        if self._tracker is None:
            _log.debug("verify_predictions: tracker missing, returning empty stats")
            return {
                "total": 0,
                "hit": 0,
                "missed": 0,
                "data_unavailable": 0,
                "expired": 0,
                "unverifiable": 0,
            }

        return verify_pending(
            tracker=self._tracker,
            episodic=self._episodic,
            adapter=adapter,
            cache_store=cache_store,
        )

    # ------------------------------------------------------------------
    # 4. 提炼（离线知识归纳）
    # ------------------------------------------------------------------

    def consolidate(self) -> None:
        """从 episodic + tracker 提炼语义知识（板块叙事 / 市场状态 / 规律）。

        - ``client`` 为 ``None`` → 跳过（提炼依赖 LLM）；
        - episodic / tracker / semantic 任一缺失 → 跳过；
        - 提炼过程任何异常 → 静默降级。
        """
        if self._client is None or self._model is None:
            _log.debug("consolidate: no LLM client/model, skipping")
            return
        if self._episodic is None or self._tracker is None or self._semantic is None:
            _log.debug("consolidate: memory components missing, skipping")
            return

        try:
            consolidator = MemoryConsolidator(
                self._episodic,
                self._semantic,
                self._tracker,
                self._client,
                self._model,
            )
            consolidator.consolidate_all()
        except Exception as e:
            _log.warning("consolidate: failed: %s", e)

    # ------------------------------------------------------------------
    # 5. 状态快照
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """返回当前记忆系统状态快照。

        缺失的组件对应字段返回 0 / 空结构，不会抛异常。
        """
        snapshot: dict[str, Any] = {
            "episodic_count": 0,
            "prediction_stats": {},
            "semantic_count": 0,
            "insight_count": 0,
        }

        if self._episodic is not None:
            try:
                snapshot["episodic_count"] = self._episodic.summary().get("total", 0)
            except Exception as e:
                _log.warning("stats: episodic.summary failed: %s", e)

        if self._tracker is not None:
            try:
                snapshot["prediction_stats"] = self._tracker.stats()
            except Exception as e:
                _log.warning("stats: tracker.stats failed: %s", e)

        if self._semantic is not None:
            try:
                active = self._semantic.get_active()
                snapshot["semantic_count"] = len(active)
            except Exception as e:
                _log.warning("stats: semantic.get_active failed: %s", e)
            snapshot["insight_count"] = self._count_insights()

        return snapshot

    def _count_insights(self) -> int:
        """统计 semantic 库里 insight_summary 表的条数（表不存在则返回 0）。"""
        if self._semantic is None:
            return 0
        try:
            with self._semantic.engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM insight_summary")).scalar() or 0
        except Exception as e:
            _log.debug("stats: insight_summary count failed: %s", e)
            return 0
