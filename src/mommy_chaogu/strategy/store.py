"""Small SQLite store for approved Strategy Cards and their monitor links."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mommy_chaogu.db import EngineOwner, create_sqlite_engine
from mommy_chaogu.strategy.models import StrategyCard


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _card_json(card: StrategyCard) -> str:
    return json.dumps(
        card.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(card: StrategyCard) -> str:
    return hashlib.sha256(_card_json(card).encode("utf-8")).hexdigest()


class StrategyStoreError(Exception):
    """Base error with a message safe to show to the user."""


class StrategyNotFoundError(StrategyStoreError):
    pass


class StrategyConflictError(StrategyStoreError):
    pass


class StrategyStore(EngineOwner):
    """Persist only cards the user explicitly approved.

    Drafts remain in the host Agent's conversation.  Each approved change gets
    a revision row so a later session can explain what changed and when.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_sqlite_engine(db_path)
        self._manage_engine()
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS strategy_cards (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
                        version INTEGER NOT NULL,
                        fingerprint TEXT NOT NULL,
                        source_hash TEXT,
                        card_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        approved_at TEXT NOT NULL,
                        archived_at TEXT
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_cards_fingerprint
                    ON strategy_cards(fingerprint)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS strategy_card_revisions (
                        strategy_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        card_json TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        revision_note TEXT NOT NULL,
                        confirmation_note TEXT NOT NULL,
                        confirmed_at TEXT NOT NULL,
                        PRIMARY KEY (strategy_id, version),
                        FOREIGN KEY (strategy_id) REFERENCES strategy_cards(id) ON DELETE CASCADE
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS strategy_monitor_links (
                        strategy_id TEXT NOT NULL,
                        strategy_version INTEGER NOT NULL,
                        condition_id TEXT NOT NULL,
                        code TEXT NOT NULL,
                        alert_id INTEGER NOT NULL,
                        alert_name TEXT NOT NULL,
                        rule_condition TEXT NOT NULL,
                        threshold TEXT NOT NULL,
                        confirmation_note TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (
                            strategy_id, strategy_version, condition_id, code,
                            rule_condition, threshold
                        ),
                        FOREIGN KEY (strategy_id) REFERENCES strategy_cards(id) ON DELETE CASCADE
                    )
                    """
                )
            )

    def save(
        self,
        card: StrategyCard,
        *,
        confirmation_note: str,
        strategy_id: str | None = None,
        expected_version: int | None = None,
        revision_note: str | None = None,
    ) -> dict[str, Any]:
        confirmation = confirmation_note.strip()
        if not confirmation:
            raise ValueError("保存策略卡需要记录用户的明确确认")
        if len(confirmation) > 500:
            raise ValueError("confirmation_note 不能超过 500 个字符")
        fingerprint = _fingerprint(card)
        raw = _card_json(card)
        now = _now()

        with self.engine.begin() as connection:
            duplicate = (
                connection.execute(
                    text(
                        """
                        SELECT id, status, version, title, updated_at
                        FROM strategy_cards WHERE fingerprint = :fingerprint
                        """
                    ),
                    {"fingerprint": fingerprint},
                )
                .mappings()
                .one_or_none()
            )
            if duplicate is not None:
                return {
                    "saved": True,
                    "reused": True,
                    "strategy_id": str(duplicate["id"]),
                    "status": str(duplicate["status"]),
                    "version": int(duplicate["version"]),
                    "title": str(duplicate["title"]),
                    "updated_at": str(duplicate["updated_at"]),
                    "message": "这张策略卡已保存，没有创建重复副本。",
                }

            if strategy_id is None:
                if expected_version is not None or revision_note is not None:
                    raise ValueError("新策略卡不需要 expected_version 或 revision_note")
                item_id = f"strategy_{uuid.uuid4().hex[:12]}"
                version = 1
                note = "首次确认保存"
                connection.execute(
                    text(
                        """
                        INSERT INTO strategy_cards (
                            id, title, status, version, fingerprint, source_hash, card_json,
                            created_at, updated_at, approved_at, archived_at
                        ) VALUES (
                            :id, :title, 'active', 1, :fingerprint, :source_hash, :card_json,
                            :created_at, :updated_at, :approved_at, NULL
                        )
                        """
                    ),
                    {
                        "id": item_id,
                        "title": card.title,
                        "fingerprint": fingerprint,
                        "source_hash": card.source.content_hash,
                        "card_json": raw,
                        "created_at": now,
                        "updated_at": now,
                        "approved_at": now,
                    },
                )
            else:
                existing = (
                    connection.execute(
                        text(
                            """
                            SELECT id, status, version, created_at
                            FROM strategy_cards WHERE id = :id
                            """
                        ),
                        {"id": strategy_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None:
                    raise StrategyNotFoundError(f"没有找到策略卡 {strategy_id}")
                if str(existing["status"]) != "active":
                    raise StrategyConflictError("已归档的策略卡不能直接修改")
                current_version = int(existing["version"])
                if expected_version is None:
                    raise ValueError("修改策略卡需要 expected_version，避免覆盖其他修改")
                if expected_version != current_version:
                    raise StrategyConflictError(
                        f"策略卡已更新到 v{current_version}；请重新打开后再确认修改"
                    )
                note = (revision_note or "").strip()
                if not note:
                    raise ValueError("修改策略卡需要 revision_note，说明用户改了什么")
                if len(note) > 500:
                    raise ValueError("revision_note 不能超过 500 个字符")
                item_id = strategy_id
                version = current_version + 1
                connection.execute(
                    text(
                        """
                        UPDATE strategy_cards
                        SET title = :title, version = :version, fingerprint = :fingerprint,
                            source_hash = :source_hash, card_json = :card_json,
                            updated_at = :updated_at, approved_at = :approved_at
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": item_id,
                        "title": card.title,
                        "version": version,
                        "fingerprint": fingerprint,
                        "source_hash": card.source.content_hash,
                        "card_json": raw,
                        "updated_at": now,
                        "approved_at": now,
                    },
                )

            connection.execute(
                text(
                    """
                    INSERT INTO strategy_card_revisions (
                        strategy_id, version, card_json, fingerprint, revision_note,
                        confirmation_note, confirmed_at
                    ) VALUES (
                        :strategy_id, :version, :card_json, :fingerprint, :revision_note,
                        :confirmation_note, :confirmed_at
                    )
                    """
                ),
                {
                    "strategy_id": item_id,
                    "version": version,
                    "card_json": raw,
                    "fingerprint": fingerprint,
                    "revision_note": note,
                    "confirmation_note": confirmation,
                    "confirmed_at": now,
                },
            )

        return {
            "saved": True,
            "reused": False,
            "strategy_id": item_id,
            "status": "active",
            "version": version,
            "title": card.title,
            "approved_at": now,
            "message": f"已在本机保存《{card.title}》v{version}。",
        }

    def get(self, strategy_id: str, *, include_history: bool = False) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM strategy_cards WHERE id = :id"), {"id": strategy_id}
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise StrategyNotFoundError(f"没有找到策略卡 {strategy_id}")
            revisions = (
                connection.execute(
                    text(
                        """
                        SELECT version, card_json, revision_note, confirmed_at
                        FROM strategy_card_revisions
                        WHERE strategy_id = :id ORDER BY version DESC LIMIT 5
                        """
                    ),
                    {"id": strategy_id},
                )
                .mappings()
                .all()
            )
            revision_count = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM strategy_card_revisions WHERE strategy_id = :id"),
                    {"id": strategy_id},
                ).scalar_one()
            )
            monitors = (
                connection.execute(
                    text(
                        """
                        SELECT strategy_version, condition_id, code, alert_id, alert_name,
                               rule_condition, threshold, created_at
                        FROM strategy_monitor_links
                        WHERE strategy_id = :id ORDER BY created_at DESC, alert_id DESC LIMIT 5
                        """
                    ),
                    {"id": strategy_id},
                )
                .mappings()
                .all()
            )
            monitor_count = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM strategy_monitor_links WHERE strategy_id = :id"),
                    {"id": strategy_id},
                ).scalar_one()
            )

        history: list[dict[str, Any]] = []
        for item in reversed(revisions):
            revision: dict[str, Any] = {
                "version": int(item["version"]),
                "revision_note": str(item["revision_note"]),
                # Keep the exact consent note in the local audit row, but do
                # not echo potentially personal conversation text through an
                # Agent read tool.  The timestamp is sufficient to show that
                # this revision was explicitly confirmed.
                "user_confirmed": True,
                "confirmed_at": str(item["confirmed_at"]),
            }
            if include_history:
                revision["card"] = json.loads(str(item["card_json"]))
            history.append(revision)

        return {
            "strategy_id": str(row["id"]),
            "status": str(row["status"]),
            "version": int(row["version"]),
            "card": json.loads(str(row["card_json"])),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "approved_at": str(row["approved_at"]),
            "archived_at": str(row["archived_at"]) if row["archived_at"] else None,
            "revisions": history,
            "revision_count": revision_count,
            "revision_history_truncated": revision_count > len(history),
            "monitors": [dict(item) for item in reversed(monitors)],
            "monitor_count": monitor_count,
            "monitor_history_truncated": monitor_count > len(monitors),
        }

    def list(
        self,
        *,
        status: str = "active",
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if status not in {"active", "archived", "all"}:
            raise ValueError("status 必须是 active、archived 或 all")
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 5))}
        if status != "all":
            clauses.append("status = :status")
            params["status"] = status
        cleaned_query = (query or "").strip()
        if cleaned_query:
            clauses.append(r"(title LIKE :query ESCAPE '\' OR card_json LIKE :query ESCAPE '\')")
            # % 和 _ 是 LIKE 通配符：用户搜索字面量时必须转义，否则
            # 搜索"100%"会匹配任何包含"100"后跟任意字符的标题
            escaped = cleaned_query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            params["query"] = f"%{escaped}%"
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        statement = text(
            "SELECT id, status, version, card_json, created_at, updated_at "
            f"FROM strategy_cards{where} ORDER BY updated_at DESC LIMIT :limit"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement, params).mappings().all()

        result: list[dict[str, Any]] = []
        for row in rows:
            card = json.loads(str(row["card_json"]))
            result.append(
                {
                    "strategy_id": str(row["id"]),
                    "title": str(card["title"])[:80],
                    "status": str(row["status"]),
                    "version": int(row["version"]),
                    "summary": str(card["summary"])[:100],
                    "source": {
                        "type": card["source"]["type"],
                        "title": str(card["source"]["title"])[:60],
                        "reference": str(card["source"]["reference"])[:80],
                    },
                    "updated_at": str(row["updated_at"]),
                    "created_at": str(row["created_at"]),
                }
            )
        return result

    def archive(self, strategy_id: str) -> dict[str, Any]:
        now = _now()
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("SELECT title, status FROM strategy_cards WHERE id = :id"),
                    {"id": strategy_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise StrategyNotFoundError(f"没有找到策略卡 {strategy_id}")
            if str(row["status"]) == "archived":
                return {
                    "archived": True,
                    "reused": True,
                    "strategy_id": strategy_id,
                    "message": "这张策略卡已经归档。",
                }
            connection.execute(
                text(
                    """
                    UPDATE strategy_cards
                    SET status = 'archived', archived_at = :archived_at, updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {"id": strategy_id, "archived_at": now, "updated_at": now},
            )
        return {
            "archived": True,
            "reused": False,
            "strategy_id": strategy_id,
            "title": str(row["title"]),
            "archived_at": now,
            "message": "策略卡已归档；已有监控不会被静默删除。",
        }

    def monitor_link(
        self,
        *,
        strategy_id: str,
        strategy_version: int,
        condition_id: str,
        code: str,
        rule_condition: str,
        threshold: Decimal,
    ) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM strategy_monitor_links
                        WHERE strategy_id = :strategy_id
                          AND condition_id = :condition_id
                          AND code = :code
                          AND rule_condition = :rule_condition
                          AND threshold = :threshold
                        ORDER BY
                          CASE WHEN strategy_version = :strategy_version THEN 0 ELSE 1 END,
                          strategy_version DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "strategy_id": strategy_id,
                        "strategy_version": strategy_version,
                        "condition_id": condition_id,
                        "code": code,
                        "rule_condition": rule_condition,
                        "threshold": str(threshold),
                    },
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    def record_monitor(
        self,
        *,
        strategy_id: str,
        strategy_version: int,
        condition_id: str,
        code: str,
        alert_id: int,
        alert_name: str,
        rule_condition: str,
        threshold: Decimal,
        confirmation_note: str,
    ) -> None:
        confirmation = confirmation_note.strip()
        if not confirmation:
            raise ValueError("启用监控需要记录用户的明确确认")
        if len(confirmation) > 500:
            raise ValueError("confirmation_note 不能超过 500 个字符")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO strategy_monitor_links (
                        strategy_id, strategy_version, condition_id, code, alert_id,
                        alert_name, rule_condition, threshold, confirmation_note, created_at
                    ) VALUES (
                        :strategy_id, :strategy_version, :condition_id, :code, :alert_id,
                        :alert_name, :rule_condition, :threshold, :confirmation_note, :created_at
                    )
                    ON CONFLICT (
                        strategy_id, strategy_version, condition_id, code,
                        rule_condition, threshold
                    ) DO UPDATE SET
                        alert_id = excluded.alert_id,
                        alert_name = excluded.alert_name,
                        confirmation_note = excluded.confirmation_note,
                        created_at = excluded.created_at
                    """
                ),
                {
                    "strategy_id": strategy_id,
                    "strategy_version": strategy_version,
                    "condition_id": condition_id,
                    "code": code,
                    "alert_id": alert_id,
                    "alert_name": alert_name,
                    "rule_condition": rule_condition,
                    "threshold": str(threshold),
                    "confirmation_note": confirmation,
                    "created_at": _now(),
                },
            )
