"""SemanticMemory：提取后的知识记忆（SQLite 持久化）。

存储从市场事件中提炼出的结构化知识，包括板块逻辑、个股洞察、市场状态、
观察到的形态等。支持按 scope / knowledge_type 查询、关键词检索、置信度
校准与新旧知识 supersede。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
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
