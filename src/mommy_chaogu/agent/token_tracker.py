"""TokenTracker：LLM token 用量追踪（SQLite 持久化）。

记录每次 LLM 调用消耗的 token（prompt / completion / total / 缓存命中 /
推理 token），用于 LLM 回测的成本核算与 token 预算控制。

设计要点：
- 与 PredictionTracker / EpisodicMemory 同一套 SQLite + SQLAlchemy 模式
- ``record_from_response()`` 能直接吃 OpenAI SDK 的 response 对象，
  自动从 ``response.usage`` 提取 token 数（兼容 deepseek / openai / kimi）
- 聚合统计按 model / phase / day 维度，配合内置定价表估算成本

用法::

    tracker = TokenTracker(Path("data/agent.db"))
    tracker.record_from_response(openai_resp, model="deepseek-chat", phase="agent")
    totals = tracker.totals(phase="agent")
    cost  = tracker.cost_estimate()
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from mommy_chaogu.db import EngineOwner, create_sqlite_engine

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    phase TEXT,
    request_id TEXT,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_token_model ON token_usage(model);
CREATE INDEX IF NOT EXISTS ix_token_phase ON token_usage(phase);
CREATE INDEX IF NOT EXISTS ix_token_created ON token_usage(created_at);
CREATE INDEX IF NOT EXISTS ix_token_request ON token_usage(request_id);
"""

# 内置定价（美元 / 1M tokens）。key 为模型名前缀匹配。
# input = 缓存未命中时的输入价；input_cached = 缓存命中价；output = 输出价。
# 仅用于粗略估算，实际计费以 provider 账单为准。
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.27, "input_cached": 0.07, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "input_cached": 0.14, "output": 2.19},
    "gpt-4o-mini": {"input": 0.15, "input_cached": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "input_cached": 1.25, "output": 10.00},
    "moonshot-v1-8k": {"input": 1.67, "input_cached": 1.67, "output": 1.67},
    "moonshot-v1-32k": {"input": 3.34, "input_cached": 3.34, "output": 3.34},
    "moonshot-v1-128k": {"input": 8.68, "input_cached": 8.68, "output": 8.68},
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将一行查询结果转为字典。"""
    cols = list(row._mapping.keys())
    return {col: row._mapping[col] for col in cols}


def _match_pricing(model: str, pricing: dict[str, dict[str, float]]) -> dict[str, float]:
    """按模型名匹配定价表，支持前缀匹配（如 "deepseek-chat-002"）。"""
    if model in pricing:
        return pricing[model]
    # 找最长公共前缀 key
    best: dict[str, float] | None = None
    best_len = 0
    for key, val in pricing.items():
        if model.startswith(key) and len(key) > best_len:
            best = val
            best_len = len(key)
    if best is not None:
        return best
    # 兜底：未知模型用 0 成本
    return {"input": 0.0, "input_cached": 0.0, "output": 0.0}


@dataclass
class TokenUsageRecord:
    """单次 LLM 调用的 token 用量记录。"""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    phase: str | None = None
    request_id: str | None = None
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens


class TokenTracker(EngineOwner):
    """LLM token 用量追踪：SQLite 持久化的逐次调用记录与聚合统计。

    用法::

        tracker = TokenTracker(Path("data/agent.db"))
        tracker.record_from_response(resp, model="deepseek-chat", phase="agent")
        totals = tracker.totals()
        cost = tracker.cost_estimate()
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_sqlite_engine(db_path)
        self._manage_engine()
        with self.engine.begin() as conn:
            for stmt in _SCHEMA_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self):  # type: ignore[no-untyped-def]
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int | None = None,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
        phase: str | None = None,
        request_id: str | None = None,
    ) -> int:
        """记录单次 LLM 调用的 token 用量，返回自增 id。

        *total_tokens* 为空时按 ``prompt + completion`` 自动计算。
        """
        rec = TokenUsageRecord(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens or 0,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            phase=phase,
            request_id=request_id,
        )
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO token_usage (
                        created_at, model, phase, request_id,
                        prompt_tokens, completion_tokens, total_tokens,
                        cached_tokens, reasoning_tokens
                    )
                    VALUES (
                        :created_at, :model, :phase, :request_id,
                        :prompt_tokens, :completion_tokens, :total_tokens,
                        :cached_tokens, :reasoning_tokens
                    )
                """),
                {
                    "created_at": rec.created_at,
                    "model": rec.model,
                    "phase": rec.phase,
                    "request_id": rec.request_id,
                    "prompt_tokens": rec.prompt_tokens,
                    "completion_tokens": rec.completion_tokens,
                    "total_tokens": rec.total_tokens,
                    "cached_tokens": rec.cached_tokens,
                    "reasoning_tokens": rec.reasoning_tokens,
                },
            )
            return result.lastrowid or 0

    def record_from_response(
        self,
        response: Any,
        model: str,
        phase: str | None = None,
        request_id: str | None = None,
    ) -> int:
        """从 OpenAI SDK response 对象提取 usage 并写入。

        兼容 deepseek / openai / kimi：优先读
        ``response.usage.prompt_tokens_details.cached_tokens``，缺失则按 0 处理；
        ``completion_tokens_details.reasoning_tokens``（deepseek-reasoner）同理。

        若 response 无 usage（模拟/异常），抛出 ValueError。
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            raise ValueError("response 没有 usage 字段，无法记录 token")

        prompt_tokens: int = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens: int = getattr(usage, "completion_tokens", 0) or 0
        total_tokens: int = getattr(usage, "total_tokens", 0) or 0

        # 缓存命中 token（prompt cache）— 不同 provider 放置位置不同
        cached_tokens = _extract_detail_tokens(usage, "prompt_tokens_details", "cached_tokens")
        # 推理 token（deepseek-reasoner / o1）
        reasoning_tokens = _extract_detail_tokens(
            usage, "completion_tokens_details", "reasoning_tokens"
        )

        return self.record(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            phase=phase,
            request_id=request_id,
        )

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def totals(
        self,
        model: str | None = None,
        phase: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """返回过滤条件下的 token 汇总：prompt / completion / total / cached / calls。"""
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if model is not None:
            clauses.append("model = :model")
            params["model"] = model
        if phase is not None:
            clauses.append("phase = :phase")
            params["phase"] = phase
        if request_id is not None:
            clauses.append("request_id = :request_id")
            params["request_id"] = request_id

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.session() as s:
            row = s.execute(
                text(f"""
                    SELECT
                        COUNT(*) AS calls,
                        COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                        COALESCE(SUM(total_tokens), 0) AS total_tokens,
                        COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                        COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens
                    FROM token_usage
                    {where}
                """),
                params,
            ).first()
        if row is None:
            return {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
                "reasoning_tokens": 0,
            }
        return _row_to_dict(row)

    def recent(
        self,
        limit: int = 100,
        model: str | None = None,
        phase: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回最近 *limit* 条记录，按 created_at 降序，可选过滤。"""
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if model is not None:
            clauses.append("model = :model")
            params["model"] = model
        if phase is not None:
            clauses.append("phase = :phase")
            params["phase"] = phase
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.session() as s:
            rows = s.execute(
                text(f"""
                    SELECT * FROM token_usage
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                params,
            ).all()
        return [_row_to_dict(r) for r in rows]

    def by_model(self) -> list[dict[str, Any]]:
        """按 model 聚合 token 用量。"""
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT
                        model,
                        COUNT(*) AS calls,
                        SUM(prompt_tokens) AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        SUM(total_tokens) AS total_tokens,
                        SUM(cached_tokens) AS cached_tokens
                    FROM token_usage
                    GROUP BY model
                    ORDER BY total_tokens DESC
                """)
            ).all()
        return [_row_to_dict(r) for r in rows]

    def by_phase(self) -> list[dict[str, Any]]:
        """按 phase 聚合 token 用量（phase 为 NULL 归入 'unknown'）。"""
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT
                        COALESCE(phase, 'unknown') AS phase,
                        COUNT(*) AS calls,
                        SUM(prompt_tokens) AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        SUM(total_tokens) AS total_tokens,
                        SUM(cached_tokens) AS cached_tokens
                    FROM token_usage
                    GROUP BY COALESCE(phase, 'unknown')
                    ORDER BY total_tokens DESC
                """)
            ).all()
        return [_row_to_dict(r) for r in rows]

    def by_day(self) -> list[dict[str, Any]]:
        """按日期（created_at 前 10 字符 YYYY-MM-DD）聚合 token 用量。"""
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT
                        substr(created_at, 1, 10) AS day,
                        COUNT(*) AS calls,
                        SUM(prompt_tokens) AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        SUM(total_tokens) AS total_tokens
                    FROM token_usage
                    GROUP BY substr(created_at, 1, 10)
                    ORDER BY day DESC
                """)
            ).all()
        return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 成本估算
    # ------------------------------------------------------------------

    def cost_estimate(
        self,
        pricing: dict[str, dict[str, float]] | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        """按内置/自定义定价表估算美元成本。

        缓存命中的 prompt token 按 ``input_cached`` 价计算，
        其余 prompt token 按 ``input`` 价计算。

        Returns:
            {"total_usd": float, "by_model": {model: {"usd":, "calls":, ...}}}
        """
        table = pricing if pricing is not None else DEFAULT_PRICING

        where = "WHERE phase = :phase" if phase is not None else ""
        params: dict[str, Any] = {"phase": phase} if phase is not None else {}

        with self.session() as s:
            rows = s.execute(
                text(f"""
                    SELECT
                        model,
                        COUNT(*) AS calls,
                        SUM(prompt_tokens) AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        SUM(cached_tokens) AS cached_tokens,
                        SUM(total_tokens) AS total_tokens
                    FROM token_usage
                    {where}
                    GROUP BY model
                """),
                params,
            ).all()

        by_model: dict[str, dict[str, float]] = {}
        grand_total = 0.0
        for row in rows:
            m = row._mapping["model"]
            price = _match_pricing(m, table)
            prompt = row._mapping["prompt_tokens"] or 0
            completion = row._mapping["completion_tokens"] or 0
            cached = row._mapping["cached_tokens"] or 0
            uncached_prompt = max(prompt - cached, 0)

            usd = (
                uncached_prompt / 1_000_000 * price["input"]
                + cached / 1_000_000 * price["input_cached"]
                + completion / 1_000_000 * price["output"]
            )
            grand_total += usd
            by_model[m] = {
                "usd": round(usd, 6),
                "calls": row._mapping["calls"],
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "cached_tokens": cached,
                "total_tokens": row._mapping["total_tokens"] or 0,
            }

        return {"total_usd": round(grand_total, 6), "by_model": by_model}

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def reset(self) -> int:
        """清空所有 token 记录，返回删除行数。用于回测前重置。"""
        with self.session() as s:
            count = s.execute(text("SELECT COUNT(*) FROM token_usage")).scalar() or 0
            s.execute(text("DELETE FROM token_usage"))
            return count

    def count(self) -> int:
        """返回总记录数。"""
        with self.session() as s:
            return s.execute(text("SELECT COUNT(*) FROM token_usage")).scalar() or 0


def _extract_detail_tokens(usage: Any, detail_attr: str, token_attr: str) -> int:
    """安全地从 usage 的嵌套 *_details 对象中取 token 数。

    不同 provider / SDK 版本字段位置不一，任何环节缺失都返回 0。
    """
    details = getattr(usage, detail_attr, None)
    if details is None:
        return 0
    val = getattr(details, token_attr, None)
    return val or 0
