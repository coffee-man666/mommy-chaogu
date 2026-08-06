"""SQLite persistence for custom workflow specs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mommy_chaogu.db import EngineOwner, create_sqlite_engine
from mommy_chaogu.workflow.spec import WorkflowSpec


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WorkflowStore(EngineOwner):
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_sqlite_engine(db_path)
        self._manage_engine()
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS custom_workflows (
                        id TEXT PRIMARY KEY,
                        spec_json TEXT NOT NULL,
                        source_text TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        hit_count INTEGER DEFAULT 0,
                        last_used TEXT
                    )
                    """
                )
            )

    def save(self, spec: WorkflowSpec, source_text: str = "") -> None:
        now = _now()
        with self.engine.begin() as connection:
            existing = (
                connection.execute(
                    text(
                        "SELECT created_at, hit_count, last_used FROM custom_workflows WHERE id = :id"
                    ),
                    {"id": spec.id},
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(
                    text(
                        """
                        INSERT INTO custom_workflows
                            (id, spec_json, source_text, created_at, updated_at, hit_count, last_used)
                        VALUES (:id, :spec_json, :source_text, :created_at, :updated_at, 0, NULL)
                        """
                    ),
                    {
                        "id": spec.id,
                        "spec_json": spec.to_json(),
                        "source_text": source_text,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            else:
                connection.execute(
                    text(
                        """
                        UPDATE custom_workflows
                        SET spec_json = :spec_json,
                            source_text = :source_text,
                            updated_at = :updated_at,
                            created_at = :created_at,
                            hit_count = :hit_count,
                            last_used = :last_used
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": spec.id,
                        "spec_json": spec.to_json(),
                        "source_text": source_text,
                        "created_at": str(existing["created_at"]),
                        "updated_at": now,
                        "hit_count": int(existing["hit_count"] or 0),
                        "last_used": existing["last_used"],
                    },
                )

    def load(self, workflow_id: str) -> WorkflowSpec | None:
        with self.engine.connect() as connection:
            raw = connection.execute(
                text("SELECT spec_json FROM custom_workflows WHERE id = :id"),
                {"id": workflow_id},
            ).scalar_one_or_none()
        if raw is None:
            return None
        return WorkflowSpec.from_json(str(raw))

    def load_all(self) -> list[tuple[WorkflowSpec, dict[str, Any]]]:
        return [(spec, meta) for spec, meta in self.load_all_records() if spec is not None]

    def load_all_records(self) -> list[tuple[WorkflowSpec | None, dict[str, Any]]]:
        """Load every row, retaining ``None`` for corrupt specs for stale reporting."""
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT id, spec_json, source_text, created_at, updated_at, hit_count, last_used
                    FROM custom_workflows ORDER BY created_at, id
                    """
                    )
                )
                .mappings()
                .all()
            )
        loaded: list[tuple[WorkflowSpec | None, dict[str, Any]]] = []
        for row in rows:
            spec: WorkflowSpec | None
            try:
                spec = WorkflowSpec.from_json(str(row["spec_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                spec = None
            meta = {
                "id": row["id"],
                "source_text": row["source_text"] or "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "hit_count": int(row["hit_count"] or 0),
                "last_used": row["last_used"],
            }
            loaded.append((spec, meta))
        return loaded

    def metadata(self, workflow_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM custom_workflows WHERE id = :id"),
                    {"id": workflow_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return {key: row[key] for key in row if key != "spec_json"}

    def delete(self, workflow_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM custom_workflows WHERE id = :id"), {"id": workflow_id}
            )
        return result.rowcount > 0

    def increment_hit(self, workflow_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE custom_workflows
                    SET hit_count = hit_count + 1, last_used = :last_used
                    WHERE id = :id
                    """
                ),
                {"id": workflow_id, "last_used": _now()},
            )
