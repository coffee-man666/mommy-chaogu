"""EpisodicMemory：结构化市场事件记忆（SQLite 持久化）。

存储市场快照、板块异动、个股事件等结构化记录，支持按 scope / event_type /
code / 日期范围查询，为后续回测与复盘提供可检索的事件流。
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
CREATE TABLE IF NOT EXISTS episodic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    trade_date TEXT,
    event_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    code TEXT,
    name TEXT,
    data TEXT NOT NULL,
    summary TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    data_coverage TEXT DEFAULT '{}',
    source TEXT DEFAULT 'agent',
    confidence REAL DEFAULT 0.5,
    prediction_id INTEGER,
    created_at TEXT NOT NULL,
    content_hash TEXT
);

CREATE INDEX IF NOT EXISTS ix_episodic_scope
    ON episodic_events(scope);

CREATE INDEX IF NOT EXISTS ix_episodic_type
    ON episodic_events(event_type);

CREATE INDEX IF NOT EXISTS ix_episodic_ts
    ON episodic_events(timestamp);

CREATE INDEX IF NOT EXISTS ix_episodic_code_date
    ON episodic_events(code, trade_date);
"""

# ALTER TABLE 兼容旧库：content_hash 列可能不存在。
_MIGRATION_SQL = """
ALTER TABLE episodic_events ADD COLUMN content_hash TEXT
"""

_CONTENT_HASH_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS ix_episodic_content_hash
    ON episodic_events(scope, content_hash)
"""


def _ensure_content_hash_column(conn: Any) -> None:
    """旧库迁移：若 content_hash 列不存在则 ALTER TABLE 添加，并建索引。"""
    rows = conn.execute(text("PRAGMA table_info(episodic_events)")).all()
    cols = {row[1] for row in rows}
    if "content_hash" not in cols:
        conn.execute(text(_MIGRATION_SQL.strip()))
    conn.execute(text(_CONTENT_HASH_INDEX_SQL.strip()))


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EpisodicMemory:
    """结构化事件记忆：SQLite 持久化的市场事件流。

    用法::

        em = EpisodicMemory(Path("data/agent.db"))
        em.write(
            event_type="market_snapshot",
            scope="market",
            summary="沪指收涨 1.2%",
            data={"sh_index": 3200, "volume": 500e8},
        )
        events = em.recent(days=7, scope="market")
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
            _ensure_content_hash_column(conn)
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

    def write(
        self,
        event_type: str,
        scope: str,
        summary: str,
        data: dict[str, Any],
        code: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
        data_coverage: dict[str, bool] | None = None,
        source: str = "agent",
        confidence: float = 0.5,
        trade_date: str | None = None,
        prediction_id: int | None = None,
        content_hash: str | None = None,
    ) -> int:
        """写入一条结构化事件，返回自增 id。

        *data* / *tags* / *data_coverage* 以 JSON 字符串形式存储，
        *timestamp* 与 *created_at* 设为当前 UTC 时间（ISO8601）。
        *content_hash* 可选，用于内容去重（同 scope + content_hash 已存在
        时由调用方负责跳过）。
        """
        now_iso = _utcnow().isoformat()
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO episodic_events (
                        timestamp, trade_date, event_type, scope,
                        code, name, data, summary,
                        tags, data_coverage, source, confidence,
                        prediction_id, created_at, content_hash
                    )
                    VALUES (
                        :timestamp, :trade_date, :event_type, :scope,
                        :code, :name, :data, :summary,
                        :tags, :data_coverage, :source, :confidence,
                        :prediction_id, :created_at, :content_hash
                    )
                """),
                {
                    "timestamp": now_iso,
                    "trade_date": trade_date,
                    "event_type": event_type,
                    "scope": scope,
                    "code": code,
                    "name": name,
                    "data": json.dumps(data, ensure_ascii=False),
                    "summary": summary,
                    "tags": json.dumps(tags or [], ensure_ascii=False),
                    "data_coverage": json.dumps(data_coverage or {}, ensure_ascii=False),
                    "source": source,
                    "confidence": confidence,
                    "prediction_id": prediction_id,
                    "created_at": now_iso,
                    "content_hash": content_hash,
                },
            )
            return result.lastrowid or 0

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """将一行记录转换为带解析后 JSON 字段的字典。"""
        return {
            "id": row[0],
            "timestamp": row[1],
            "trade_date": row[2],
            "event_type": row[3],
            "scope": row[4],
            "code": row[5],
            "name": row[6],
            "data": json.loads(row[7]),
            "summary": row[8],
            "tags": json.loads(row[9]),
            "data_coverage": json.loads(row[10]),
            "source": row[11],
            "confidence": row[12],
            "prediction_id": row[13],
            "created_at": row[14],
            "content_hash": row[15] if len(row) > 15 else None,
        }

    def _query_select_sql(self) -> str:
        return """
            SELECT id, timestamp, trade_date, event_type, scope,
                   code, name, data, summary, tags, data_coverage,
                   source, confidence, prediction_id, created_at, content_hash
            FROM episodic_events
        """

    def exists_by_hash(self, scope: str, content_hash: str) -> bool:
        """同 scope + content_hash 的事件是否已存在（用于去重）。"""
        with self.session() as s:
            row = s.execute(
                text(
                    "SELECT 1 FROM episodic_events"
                    " WHERE scope = :scope AND content_hash = :content_hash LIMIT 1"
                ),
                {"scope": scope, "content_hash": content_hash},
            ).first()
            return row is not None

    def query(
        self,
        scope: str | None = None,
        event_type: str | None = None,
        code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按条件查询事件，返回列表（按 timestamp 倒序）。

        *scope* 支持前缀匹配：传入 ``"sector:"`` 会匹配所有以 ``sector:`` 开头的
        scope（如 ``sector:创新药``）。其余字段为精确匹配。
        *start_date* / *end_date* 基于 ``trade_date`` 字段做闭区间过滤。
        """
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}

        if scope is not None:
            if scope.endswith(":"):
                conditions.append("scope LIKE :scope")
                params["scope"] = f"{scope}%"
            else:
                conditions.append("scope = :scope")
                params["scope"] = scope
        if event_type is not None:
            conditions.append("event_type = :event_type")
            params["event_type"] = event_type
        if code is not None:
            conditions.append("code = :code")
            params["code"] = code
        if start_date is not None:
            conditions.append("trade_date >= :start_date")
            params["start_date"] = start_date
        if end_date is not None:
            conditions.append("trade_date <= :end_date")
            params["end_date"] = end_date

        sql = self._query_select_sql()
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY timestamp DESC LIMIT :limit"

        with self.session() as s:
            rows = s.execute(text(sql), params).all()
            return [self._row_to_dict(r) for r in rows]

    def recent(
        self,
        days: int = 7,
        scope: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """返回最近 *days* 天内的事件（按 timestamp 倒序）。

        *scope* 同 :meth:`query` 支持前缀匹配。
        """
        cutoff = (_utcnow() - timedelta(days=days)).isoformat()
        conditions = ["timestamp >= :cutoff"]
        params: dict[str, Any] = {"cutoff": cutoff, "limit": limit}

        if scope is not None:
            if scope.endswith(":"):
                conditions.append("scope LIKE :scope")
                params["scope"] = f"{scope}%"
            else:
                conditions.append("scope = :scope")
                params["scope"] = scope

        sql = self._query_select_sql()
        sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY timestamp DESC LIMIT :limit"

        with self.session() as s:
            rows = s.execute(text(sql), params).all()
            return [self._row_to_dict(r) for r in rows]

    def get_by_id(self, event_id: int) -> dict[str, Any] | None:
        """按主键取单条事件，不存在返回 None。"""
        sql = self._query_select_sql() + " WHERE id = :event_id"
        with self.session() as s:
            row = s.execute(text(sql), {"event_id": event_id}).first()
            return self._row_to_dict(row) if row else None

    def update_prediction_id(self, event_id: int, prediction_id: int) -> None:
        """回填已存在事件的 ``prediction_id``（验证后建立 traceability 链）。

        用于 :func:`~mommy_chaogu.agent.verify_engine.verify_pending` 在预测
        hit/missed 后，把验证结果反向关联到产生该预测的源 observation 事件。
        """
        with self.session() as s:
            s.execute(
                text("UPDATE episodic_events SET prediction_id = :pid WHERE id = :id"),
                {"pid": prediction_id, "id": event_id},
            )

    def cleanup_old(self, days: int = 90) -> int:
        """删除 *days* 天前的事件，返回删除条数。

        分两层 TTL：
        - ``analysis_record`` / ``market_snapshot`` 保留更久（180 天），
          因为它们有长期复盘价值；
        - 其余类型（如 ``signal_event`` / ``trade_decision``）按 *days*
          天清理（默认 90 天）。
        """
        long_retain_types = ("analysis_record", "market_snapshot")
        long_days = max(days, 180)
        short_cutoff = (_utcnow() - timedelta(days=days)).isoformat()
        long_cutoff = (_utcnow() - timedelta(days=long_days)).isoformat()

        placeholders = ",".join([f":t{i}" for i in range(len(long_retain_types))])
        params: dict[str, Any] = {
            "short_cutoff": short_cutoff,
            "long_cutoff": long_cutoff,
        }
        for i, t in enumerate(long_retain_types):
            params[f"t{i}"] = t

        with self.session() as s:
            result = s.execute(
                text(f"""
                    DELETE FROM episodic_events
                    WHERE (
                        timestamp < :short_cutoff
                        AND event_type NOT IN ({placeholders})
                    )
                    OR (
                        timestamp < :long_cutoff
                        AND event_type IN ({placeholders})
                    )
                """),
                params,
            )
            return result.rowcount or 0

    def summary(self) -> dict[str, Any]:
        """返回统计摘要：总条数、按 event_type / scope 分组计数、时间跨度。"""
        with self.session() as s:
            total = s.execute(text("SELECT COUNT(*) FROM episodic_events")).scalar() or 0

            type_rows = s.execute(
                text("SELECT event_type, COUNT(*) FROM episodic_events GROUP BY event_type")
            ).all()
            by_type = {r[0]: r[1] for r in type_rows}

            scope_rows = s.execute(
                text("SELECT scope, COUNT(*) FROM episodic_events GROUP BY scope")
            ).all()
            by_scope = {r[0]: r[1] for r in scope_rows}

            earliest = s.execute(text("SELECT MIN(timestamp) FROM episodic_events")).scalar()
            latest = s.execute(text("SELECT MAX(timestamp) FROM episodic_events")).scalar()

        return {
            "total": total,
            "by_type": by_type,
            "by_scope": by_scope,
            "earliest": earliest,
            "latest": latest,
        }
