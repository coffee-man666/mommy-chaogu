"""ConversationMemory：Agent 对话记忆（SQLite 持久化）。

在多次对话之间保持上下文。表 agent_memory 存储所有 user/assistant 消息，
带时间戳，支持按 limit 取最近 N 条、清空、统计。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT 'default',
    timestamp TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_memory_id
    ON agent_memory(id);
"""

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_session_id(session_id: str) -> str:
    """Return a safe session id or raise ValueError."""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("session_id must be 1-64 characters: letters, numbers, _ or -")
    return session_id


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConversationMemory:
    """对话记忆：SQLite 持久化的聊天历史。

    用法::

        mem = ConversationMemory(Path("data/agent.db"))
        mem.add("user", "茅台多少钱")
        mem.add("assistant", "茅台现价 1680")
        recent = mem.recent(limit=10)
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
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_memory)"))}
            if "session_id" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_memory "
                        "ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'"
                    )
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_memory_session_id_id "
                    "ON agent_memory(session_id, id)"
                )
            )
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

    def add(self, role: str, content: str, session_id: str = "default") -> int:
        """添加一条消息，返回自增 id。"""
        session_id = validate_session_id(session_id)
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO agent_memory (role, content, session_id, timestamp)
                    VALUES (:role, :content, :session_id, :ts)
                """),
                {"role": role, "content": content, "session_id": session_id, "ts": _utcnow()},
            )
            return result.lastrowid or 0

    def recent(self, limit: int = 20, session_id: str = "default") -> list[dict[str, Any]]:
        """返回最近 *limit* 条消息（按时间正序排列，最旧在前）。

        正序排列方便直接作为 LLM 的 history 使用。
        """
        session_id = validate_session_id(session_id)
        limit = max(1, min(limit, 200))
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT id, role, content, timestamp
                    FROM agent_memory
                    WHERE session_id = :session_id
                    ORDER BY id DESC LIMIT :limit
                """),
                {"limit": limit, "session_id": session_id},
            ).all()
            return [
                {
                    "id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "timestamp": (
                        r[3] if isinstance(r[3], datetime) else datetime.fromisoformat(r[3])
                    ),
                }
                for r in reversed(rows)
            ]

    def clear(self, session_id: str = "default") -> int:
        """清空所有记忆，返回删除条数。"""
        session_id = validate_session_id(session_id)
        with self.session() as s:
            result = s.execute(
                text("DELETE FROM agent_memory WHERE session_id = :session_id"),
                {"session_id": session_id},
            )
            return result.rowcount or 0

    def summary(self, session_id: str = "default") -> dict[str, Any]:
        """返回统计摘要：总条数 + 按 role 分组的计数。"""
        session_id = validate_session_id(session_id)
        with self.session() as s:
            total = (
                s.execute(
                    text("SELECT COUNT(*) FROM agent_memory WHERE session_id = :session_id"),
                    {"session_id": session_id},
                ).scalar()
                or 0
            )
            n_user = (
                s.execute(
                    text(
                        "SELECT COUNT(*) FROM agent_memory "
                        "WHERE role = 'user' AND session_id = :session_id"
                    ),
                    {"session_id": session_id},
                ).scalar()
                or 0
            )
            n_assistant = (
                s.execute(
                    text(
                        "SELECT COUNT(*) FROM agent_memory "
                        "WHERE role = 'assistant' AND session_id = :session_id"
                    ),
                    {"session_id": session_id},
                ).scalar()
                or 0
            )
        return {
            "total": total,
            "user": n_user,
            "assistant": n_assistant,
        }

    def for_session(self, session_id: str) -> SessionMemory:
        """Return a lightweight view bound to one conversation session."""
        return SessionMemory(self, validate_session_id(session_id))

    def prune_inactive_sessions(self, retention_days: int) -> int:
        """Delete non-default sessions whose newest message is older than the retention window."""
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        cutoff = _utcnow() - timedelta(days=retention_days)
        with self.session() as s:
            result = s.execute(
                text("""
                    DELETE FROM agent_memory
                    WHERE session_id != 'default'
                      AND session_id IN (
                        SELECT session_id
                        FROM agent_memory
                        GROUP BY session_id
                        HAVING MAX(timestamp) < :cutoff
                      )
                """),
                {"cutoff": cutoff},
            )
            return result.rowcount or 0


class SessionMemory:
    """ConversationMemory view that always scopes operations to one session."""

    def __init__(self, memory: ConversationMemory, session_id: str) -> None:
        self._memory = memory
        self.session_id = session_id

    def add(self, role: str, content: str) -> int:
        return self._memory.add(role, content, session_id=self.session_id)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._memory.recent(limit=limit, session_id=self.session_id)

    def clear(self) -> int:
        return self._memory.clear(session_id=self.session_id)

    def summary(self) -> dict[str, Any]:
        return self._memory.summary(session_id=self.session_id)
