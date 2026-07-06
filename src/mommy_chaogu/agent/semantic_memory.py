"""SemanticMemory：提取后的知识记忆（SQLite 持久化）。

存储从市场事件中提炼出的结构化知识，包括板块逻辑、个股洞察、市场状态、
观察到的形态等。支持按 scope / knowledge_type 查询、关键词检索、置信度
校准与新旧知识 supersede。

``search_hybrid`` 提供向量召回 + 关键词混合排序：如果注入了 embedding client
（``attach_vector_search``），先用 sqlite-vec 语义召回；否则降级为多关键词
匹配 + 相关性排序。两种模式结果都带 ``relevance_score`` 并按其降序。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS semantic_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source_event_ids TEXT DEFAULT '[]',
    status TEXT DEFAULT 'active',
    hit_count INTEGER DEFAULT 0,
    miss_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_semantic_scope
    ON semantic_knowledge(scope);

CREATE INDEX IF NOT EXISTS ix_semantic_type
    ON semantic_knowledge(knowledge_type);

CREATE INDEX IF NOT EXISTS ix_semantic_status
    ON semantic_knowledge(status);

CREATE TABLE IF NOT EXISTS insight_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_observations TEXT DEFAULT '[]',
    predictions_reviewed INTEGER DEFAULT 0,
    hit_rate REAL,
    confidence_adjustment REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_insight_period
    ON insight_summary(period_end);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SemanticMemory:
    """知识记忆：SQLite 持久化的提取知识库。

    用法::

        sm = SemanticMemory(Path("data/watchlist.db"))
        sm.upsert(
            knowledge_type="sector_thesis",
            scope="sector:创新药",
            content="创新药板块进入上行周期",
            confidence=0.85,
        )
        active = sm.get_active()
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True,
        )
        with self.engine.begin() as conn:
            for stmt in _SCHEMA_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
        self._Session = sessionmaker(self.engine, expire_on_commit=False)
        # 可选：向量召回（由 attach_vector_search 注入）
        self._vec_client: Any = None
        self._vec_model: str = "text-embedding-3-small"
        self._vec_dim: int = 1536
        self._vec_available: bool = False

    # ------------------------------------------------------------------
    # 向量索引（search_hybrid 用）
    # ------------------------------------------------------------------

    _SEMANTIC_VEC_TABLE = "semantic_knowledge_vec"
    _SEMANTIC_VEC_META = "semantic_knowledge_embeddings"

    def attach_vector_search(
        self,
        client: Any,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
    ) -> bool:
        """注入 embedding client 并初始化 semantic_knowledge 向量索引。

        成功返回 True；若 sqlite-vec 不可用则返回 False（``search_hybrid``
        会自动降级为关键词搜索）。
        """
        self._vec_client = client
        self._vec_model = model
        self._vec_dim = dim
        try:
            import sqlite_vec

            with self.engine.raw_connection() as raw_conn:
                raw_conn.enable_load_extension(True)
                sqlite_vec.load(raw_conn)
                raw_conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {self._SEMANTIC_VEC_TABLE} "
                    f"USING vec0(embedding float[{dim}])"
                )
                # 元数据表
                raw_conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._SEMANTIC_VEC_META} (
                        entry_id INTEGER PRIMARY KEY,
                        embedding BLOB,
                        model TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                raw_conn.commit()
            self._vec_available = True
        except Exception:
            self._vec_available = False
        return self._vec_available

    def _generate_embedding(self, text_content: str) -> list[float] | None:
        if self._vec_client is None:
            return None
        try:
            response = self._vec_client.embeddings.create(
                model=self._vec_model,
                input=text_content[:2000],
            )
            return response.data[0].embedding
        except Exception:
            return None

    def index_knowledge_vector(self, entry_id: int, content: str) -> bool:
        """为单条知识生成并存储 embedding。需要先 ``attach_vector_search``。"""
        if not self._vec_available:
            return False
        import struct

        vec = self._generate_embedding(content)
        if vec is None:
            return False
        packed = struct.pack(f"{len(vec)}f", *vec)
        now_iso = _utcnow().isoformat()
        try:
            import sqlite_vec

            with self.engine.raw_connection() as raw_conn:
                raw_conn.enable_load_extension(True)
                sqlite_vec.load(raw_conn)
                raw_conn.execute(
                    f"INSERT OR REPLACE INTO {self._SEMANTIC_VEC_META} "
                    f"(entry_id, embedding, model, created_at) "
                    f"VALUES (?, ?, ?, ?)",
                    (entry_id, packed, self._vec_model, now_iso),
                )
                raw_conn.execute(
                    f"DELETE FROM {self._SEMANTIC_VEC_TABLE} WHERE rowid = ?",
                    (entry_id,),
                )
                raw_conn.execute(
                    f"INSERT INTO {self._SEMANTIC_VEC_TABLE} (rowid, embedding) VALUES (?, ?)",
                    (entry_id, packed),
                )
                raw_conn.commit()
            return True
        except Exception:
            return False

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

    def upsert(
        self,
        knowledge_type: str,
        scope: str,
        content: str,
        confidence: float = 0.8,
        source_ids: list[int] | None = None,
    ) -> int:
        """写入一条知识；若同 (knowledge_type, scope) 的 active 条目已存在，
        则将其标记为 ``superseded`` 再插入新条目。返回新条目 id。

        *source_ids* 以 JSON 字符串形式存储。
        """
        now_iso = _utcnow().isoformat()
        with self.session() as s:
            row = s.execute(
                text("""
                    SELECT id FROM semantic_knowledge
                    WHERE knowledge_type = :knowledge_type
                      AND scope = :scope
                      AND status = 'active'
                """),
                {"knowledge_type": knowledge_type, "scope": scope},
            ).first()
            if row is not None:
                s.execute(
                    text("""
                        UPDATE semantic_knowledge
                        SET status = 'superseded', updated_at = :now
                        WHERE id = :old_id
                    """),
                    {"now": now_iso, "old_id": row[0]},
                )

            result = s.execute(
                text("""
                    INSERT INTO semantic_knowledge (
                        knowledge_type, scope, content, confidence,
                        source_event_ids, status, hit_count, miss_count,
                        created_at, updated_at
                    )
                    VALUES (
                        :knowledge_type, :scope, :content, :confidence,
                        :source_event_ids, 'active', 0, 0,
                        :created_at, :updated_at
                    )
                """),
                {
                    "knowledge_type": knowledge_type,
                    "scope": scope,
                    "content": content,
                    "confidence": confidence,
                    "source_event_ids": json.dumps(source_ids or [], ensure_ascii=False),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )
            return result.lastrowid or 0

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """将一行记录转换为带解析后 JSON 字段的字典。"""
        return {
            "id": row[0],
            "knowledge_type": row[1],
            "scope": row[2],
            "content": row[3],
            "confidence": row[4],
            "source_event_ids": json.loads(row[5]),
            "status": row[6],
            "hit_count": row[7],
            "miss_count": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }

    def _query_select_sql(self) -> str:
        return """
            SELECT id, knowledge_type, scope, content, confidence,
                   source_event_ids, status, hit_count, miss_count,
                   created_at, updated_at
            FROM semantic_knowledge
        """

    def query(
        self,
        scope: str | None = None,
        knowledge_type: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按条件查询知识条目，返回列表（按 updated_at 倒序）。"""
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}

        if scope is not None:
            conditions.append("scope = :scope")
            params["scope"] = scope
        if knowledge_type is not None:
            conditions.append("knowledge_type = :knowledge_type")
            params["knowledge_type"] = knowledge_type
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status

        sql = self._query_select_sql()
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC LIMIT :limit"

        with self.session() as s:
            rows = s.execute(text(sql), params).all()
            return [self._row_to_dict(r) for r in rows]

    def get_active(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回最近更新的 active 条目（按 updated_at 倒序）。"""
        sql = self._query_select_sql()
        sql += " WHERE status = 'active' ORDER BY updated_at DESC LIMIT :limit"
        with self.session() as s:
            rows = s.execute(text(sql), {"limit": limit}).all()
            return [self._row_to_dict(r) for r in rows]

    def search(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """简单的关键词检索：content LIKE '%query_text%'，仅限 active 条目。"""
        sql = self._query_select_sql()
        sql += (
            " WHERE content LIKE :pattern AND status = 'active'"
            " ORDER BY updated_at DESC LIMIT :top_k"
        )
        with self.session() as s:
            rows = s.execute(text(sql), {"pattern": f"%{query_text}%", "top_k": top_k}).all()
            return [self._row_to_dict(r) for r in rows]

    def search_hybrid(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """向量召回 + 关键词混合排序的语义检索。

        优先级：

        1. 若已通过 :meth:`attach_vector_search` 注入 embedding client 且
           sqlite-vec 可用，先用向量搜索 ``semantic_knowledge``，再叠加关键词
           重排（命中查询词额外加分）。
        2. 否则降级为多关键词匹配 + 相关性排序（把 query 拆成多个关键词，
           按 content 里命中的关键词数 / 频次排序，不再是单一 LIKE）。

        返回结果统一带 ``relevance_score``（0-1）字段并按其降序。
        """
        vec_results = self._vector_recall(query, limit=limit * 3)
        if vec_results is not None:
            return self._rerank_with_keywords(vec_results, query, limit)
        return self._keyword_search_ranked(query, limit)

    # ------------------------------------------------------------------
    # search_hybrid 内部实现
    # ------------------------------------------------------------------

    def _vector_recall(self, query: str, limit: int) -> list[dict[str, Any]] | None:
        """向量召回。返回 None 表示不可用（应降级）。"""
        if not self._vec_available or self._vec_client is None:
            return None
        import struct

        query_vec = self._generate_embedding(query)
        if query_vec is None:
            return None
        packed = struct.pack(f"{len(query_vec)}f", *query_vec)
        try:
            import sqlite_vec

            with self.engine.raw_connection() as raw_conn:
                raw_conn.enable_load_extension(True)
                sqlite_vec.load(raw_conn)
                cursor = raw_conn.execute(
                    f"SELECT rowid, distance FROM {self._SEMANTIC_VEC_TABLE} "
                    f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                    (packed, limit),
                )
                vec_rows = cursor.fetchall()
        except Exception:
            return None

        if not vec_rows:
            return []
        distance_map = {r[0]: r[1] for r in vec_rows}
        ids = list(distance_map)
        placeholders = ",".join(str(i) for i in ids)
        sql = self._query_select_sql() + f" WHERE id IN ({placeholders}) AND status = 'active'"
        with self.session() as s:
            rows = s.execute(text(sql)).all()
        results: list[dict[str, Any]] = []
        for row in rows:
            entry = self._row_to_dict(row)
            dist = distance_map.get(entry["id"], 1.0)
            # distance 越小越相似；cosine distance ∈ [0, 2]，转成相似度
            entry["relevance_score"] = max(0.0, min(1.0, 1.0 - dist / 2))
            results.append(entry)
        return results

    def _keyword_search_ranked(self, query: str, limit: int) -> list[dict[str, Any]]:
        """多关键词匹配 + 相关性排序（降级模式，无 embedding）。"""
        # 把 query 拆成关键词（按空格/标点切分，过滤空）
        import re

        keywords = [w for w in re.split(r"[\s,，、；;。.]+", query.strip()) if w]
        if not keywords:
            keywords = [query.strip()]
        if not any(keywords):
            return []

        sql = self._query_select_sql() + " WHERE status = 'active'"
        params: dict[str, Any] = {}
        # 至少命中一个关键词（OR）才进入候选
        like_clauses: list[str] = []
        for idx, kw in enumerate(keywords):
            key = f"kw{idx}"
            like_clauses.append(f"content LIKE :{key}")
            params[key] = f"%{kw}%"
        sql += " AND (" + " OR ".join(like_clauses) + ")"
        with self.session() as s:
            rows = s.execute(text(sql), params).all()

        scored: list[dict[str, Any]] = []
        for row in rows:
            entry = self._row_to_dict(row)
            content_lower = (entry["content"] or "").lower()
            hit_count = sum(1 for kw in keywords if kw.lower() in content_lower)
            # relevance = 命中关键词占比（0-1）
            entry["relevance_score"] = hit_count / len(keywords) if keywords else 0.0
            scored.append(entry)
        scored.sort(key=lambda e: (e["relevance_score"], e.get("confidence", 0.0)), reverse=True)
        return scored[:limit]

    def _rerank_with_keywords(
        self,
        candidates: list[dict[str, Any]],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """在向量召回结果上叠加关键词重排（混合排序）。"""
        import re

        keywords = [w for w in re.split(r"[\s,，、；;。.]+", query.strip()) if w]
        for entry in candidates:
            content_lower = (entry["content"] or "").lower()
            kw_boost = 0.0
            if keywords:
                hit = sum(1 for kw in keywords if kw.lower() in content_lower)
                kw_boost = 0.2 * (hit / len(keywords))
            # 向量相似度权重 0.8 + 关键词权重 0.2
            base = entry.get("relevance_score", 0.0) * 0.8
            entry["relevance_score"] = min(1.0, base + kw_boost)
        candidates.sort(
            key=lambda e: (e["relevance_score"], e.get("confidence", 0.0)), reverse=True
        )
        return candidates[:limit]

    def get_by_id(self, entry_id: int) -> dict[str, Any] | None:
        """按主键取单条知识，不存在返回 None。"""
        sql = self._query_select_sql() + " WHERE id = :entry_id"
        with self.session() as s:
            row = s.execute(text(sql), {"entry_id": entry_id}).first()
            return self._row_to_dict(row) if row else None

    def supersede(self, entry_id: int, reason: str = "") -> int:
        """将指定条目标记为 ``superseded``，*reason* 追加到 content 末尾。
        返回该条目 id 供调用方引用。"""
        now_iso = _utcnow().isoformat()
        with self.session() as s:
            row = s.execute(
                text("SELECT content FROM semantic_knowledge WHERE id = :entry_id"),
                {"entry_id": entry_id},
            ).first()
            if row is None:
                return entry_id
            new_content = row[0]
            if reason:
                new_content = f"{new_content} [superseded: {reason}]"
            s.execute(
                text("""
                    UPDATE semantic_knowledge
                    SET status = 'superseded', content = :content, updated_at = :now
                    WHERE id = :entry_id
                """),
                {"content": new_content, "now": now_iso, "entry_id": entry_id},
            )
        return entry_id

    def update_confidence(
        self,
        entry_id: int,
        confidence: float,
        hit_count: int | None = None,
        miss_count: int | None = None,
    ) -> None:
        """更新单条知识的置信度，可选更新 hit/miss 计数。"""
        now_iso = _utcnow().isoformat()
        sets = ["confidence = :confidence", "updated_at = :now"]
        params: dict[str, Any] = {
            "confidence": confidence,
            "now": now_iso,
            "entry_id": entry_id,
        }
        if hit_count is not None:
            sets.append("hit_count = :hit_count")
            params["hit_count"] = hit_count
        if miss_count is not None:
            sets.append("miss_count = :miss_count")
            params["miss_count"] = miss_count

        with self.session() as s:
            s.execute(
                text(f"UPDATE semantic_knowledge SET {', '.join(sets)} WHERE id = :entry_id"),
                params,
            )

    def recalibrate(self, entries_and_rates: list[dict[str, Any]]) -> None:
        """批量校准置信度：confidence = 0.5 * old_confidence + 0.5 * hit_rate。

        *entries_and_rates* 为列表，每个元素含
        ``entry_id`` / ``hit_rate`` / ``hit_count`` / ``miss_count``。
        """
        now_iso = _utcnow().isoformat()
        with self.session() as s:
            for item in entries_and_rates:
                entry_id = item["entry_id"]
                hit_rate = item["hit_rate"]
                old = s.execute(
                    text("SELECT confidence FROM semantic_knowledge WHERE id = :entry_id"),
                    {"entry_id": entry_id},
                ).scalar()
                if old is None:
                    continue
                new_confidence = 0.5 * old + 0.5 * hit_rate
                hit_count = item.get("hit_count")
                miss_count = item.get("miss_count")
                sets = ["confidence = :confidence", "updated_at = :now"]
                params: dict[str, Any] = {
                    "confidence": new_confidence,
                    "now": now_iso,
                    "entry_id": entry_id,
                }
                if hit_count is not None:
                    sets.append("hit_count = :hit_count")
                    params["hit_count"] = hit_count
                if miss_count is not None:
                    sets.append("miss_count = :miss_count")
                    params["miss_count"] = miss_count
                s.execute(
                    text(f"UPDATE semantic_knowledge SET {', '.join(sets)} WHERE id = :entry_id"),
                    params,
                )

    def cleanup_inactive(self, days: int = 180) -> int:
        """删除 *days* 天未更新的非 active 知识，返回删除条数。

        只删 ``status != 'active'`` 的（已被 supersede / 废弃的条目）；
        active 条目无论多旧都保留。判定时间用 ``updated_at``。
        """
        cutoff = (_utcnow() - timedelta(days=days)).isoformat()
        with self.session() as s:
            result = s.execute(
                text("""
                    DELETE FROM semantic_knowledge
                    WHERE status != 'active' AND updated_at < :cutoff
                """),
                {"cutoff": cutoff},
            )
            return result.rowcount or 0

    def summary(self) -> dict[str, Any]:
        """返回统计摘要：总条数、active / superseded 计数、按 type / scope 分组计数。"""
        with self.session() as s:
            total = s.execute(text("SELECT COUNT(*) FROM semantic_knowledge")).scalar() or 0
            n_active = (
                s.execute(
                    text("SELECT COUNT(*) FROM semantic_knowledge WHERE status = 'active'")
                ).scalar()
                or 0
            )
            n_superseded = (
                s.execute(
                    text("SELECT COUNT(*) FROM semantic_knowledge WHERE status = 'superseded'")
                ).scalar()
                or 0
            )

            type_rows = s.execute(
                text(
                    "SELECT knowledge_type, COUNT(*) FROM semantic_knowledge "
                    "GROUP BY knowledge_type"
                )
            ).all()
            by_type = {r[0]: r[1] for r in type_rows}

            scope_rows = s.execute(
                text("SELECT scope, COUNT(*) FROM semantic_knowledge GROUP BY scope")
            ).all()
            by_scope = {r[0]: r[1] for r in scope_rows}

        return {
            "total": total,
            "active": n_active,
            "superseded": n_superseded,
            "by_type": by_type,
            "by_scope": by_scope,
        }

    # ------------------------------------------------------------------
    # insight_summary：周期复盘摘要（周度闭环用）
    # ------------------------------------------------------------------

    def save_insight(self, insight: dict[str, Any]) -> int:
        """写入一条周期复盘摘要，返回新条目 id。

        *insight* 字段：``period_start`` / ``period_end`` / ``summary``（必填），
        ``key_observations`` (list[str]) / ``predictions_reviewed`` (int) /
        ``hit_rate`` (float | None) / ``confidence_adjustment`` (float | None)。
        """
        now_iso = _utcnow().isoformat()
        key_observations = insight.get("key_observations") or []
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO insight_summary (
                        period_start, period_end, summary, key_observations,
                        predictions_reviewed, hit_rate, confidence_adjustment,
                        created_at
                    )
                    VALUES (
                        :period_start, :period_end, :summary, :key_observations,
                        :predictions_reviewed, :hit_rate, :confidence_adjustment,
                        :created_at
                    )
                """),
                {
                    "period_start": insight["period_start"],
                    "period_end": insight["period_end"],
                    "summary": insight["summary"],
                    "key_observations": json.dumps(key_observations, ensure_ascii=False),
                    "predictions_reviewed": insight.get("predictions_reviewed", 0),
                    "hit_rate": insight.get("hit_rate"),
                    "confidence_adjustment": insight.get("confidence_adjustment"),
                    "created_at": now_iso,
                },
            )
            return result.lastrowid or 0

    def get_latest_insight(self) -> dict[str, Any] | None:
        """取最近一条 insight_summary（按 created_at 倒序），无则返回 None。"""
        with self.session() as s:
            row = s.execute(
                text("""
                    SELECT id, period_start, period_end, summary, key_observations,
                           predictions_reviewed, hit_rate, confidence_adjustment, created_at
                    FROM insight_summary
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
            ).first()
            if row is None:
                return None
            return {
                "id": row[0],
                "period_start": row[1],
                "period_end": row[2],
                "summary": row[3],
                "key_observations": json.loads(row[4] or "[]"),
                "predictions_reviewed": row[5],
                "hit_rate": row[6],
                "confidence_adjustment": row[7],
                "created_at": row[8],
            }
