"""ConversationMemory：Agent 对话记忆（SQLite 持久化）。

在多次对话之间保持上下文。表 agent_memory 存储所有 user/assistant 消息，
带时间戳，支持按 limit 取最近 N 条、清空、统计。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
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
    timestamp TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_memory_id
    ON agent_memory(id);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConversationMemory:
    """对话记忆：SQLite 持久化的聊天历史。

    用法::

        mem = ConversationMemory(Path("data/watchlist.db"))
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

    def add(self, role: str, content: str) -> int:
        """添加一条消息，返回自增 id。"""
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO agent_memory (role, content, timestamp)
                    VALUES (:role, :content, :ts)
                """),
                {"role": role, "content": content, "ts": _utcnow()},
            )
            return result.lastrowid or 0

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """返回最近 *limit* 条消息（按时间正序排列，最旧在前）。

        正序排列方便直接作为 LLM 的 history 使用。
        """
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT id, role, content, timestamp
                    FROM agent_memory
                    ORDER BY id DESC LIMIT :limit
                """),
                {"limit": limit},
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

    def clear(self) -> int:
        """清空所有记忆，返回删除条数。"""
        with self.session() as s:
            result = s.execute(text("DELETE FROM agent_memory"))
            return result.rowcount or 0

    def summary(self) -> dict[str, Any]:
        """返回统计摘要：总条数 + 按 role 分组的计数。"""
        with self.session() as s:
            total = s.execute(text("SELECT COUNT(*) FROM agent_memory")).scalar() or 0
            n_user = s.execute(
                text("SELECT COUNT(*) FROM agent_memory WHERE role = 'user'")
            ).scalar() or 0
            n_assistant = s.execute(
                text("SELECT COUNT(*) FROM agent_memory WHERE role = 'assistant'")
            ).scalar() or 0
        return {
            "total": total,
            "user": n_user,
            "assistant": n_assistant,
        }
