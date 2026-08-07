"""结构化的个人研究上下文。

外部 Coding Agent 不应接收一整段动态 system prompt。这个服务把与当前
研究对象相关的个人数据拆成稳定 schema，并在没有 embedding 时仍保证
code/scope 精确召回。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.semantic_memory import SemanticMemory

_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class ResearchContextService:
    """按研究 subject 读取最小化的个人投研上下文。"""

    schema_version = 1

    def __init__(
        self,
        agent_db: Path,
        *,
        portfolio_store: Any | None = None,
        watchlist_store: Any | None = None,
        portfolio_db: Path | None = None,
        embedding_enabled: bool = False,
    ) -> None:
        self._agent_db = agent_db
        self._portfolio_store = portfolio_store
        self._watchlist_store = watchlist_store
        self._portfolio_db = portfolio_db
        self._embedding_enabled = embedding_enabled
        self._episodic = EpisodicMemory(agent_db)
        self._tracker = PredictionTracker(agent_db)
        self._semantic = SemanticMemory(agent_db)

    @classmethod
    def from_context(cls, ctx: Any, *, embedding_enabled: bool = False) -> ResearchContextService:
        db_path = ctx.resolved_agent_db
        if db_path is None:
            raise ValueError("记忆数据库未配置")
        return cls(
            db_path,
            portfolio_store=ctx.portfolio_store,
            watchlist_store=ctx.watchlist_store,
            portfolio_db=ctx.resolved_portfolio_db,
            embedding_enabled=embedding_enabled,
        )

    def get(
        self,
        query: str | None = None,
        *,
        subject_type: str | None = None,
        code: str | None = None,
        keyword: str | None = None,
        event_limit: int = 10,
        prediction_limit: int = 10,
        semantic_limit: int = 10,
    ) -> dict[str, Any]:
        query_text = " ".join(part for part in (query, keyword) if part).strip()
        code = code or self._extract_code(query_text)
        subject = self._subject(subject_type, code, keyword or query_text)
        scope = f"stock:{code}" if code else None

        events = self._events(code=code, scope=scope, query=query_text, limit=event_limit)
        predictions = self._predictions(code=code, query=query_text, limit=prediction_limit)
        knowledge = self._knowledge(code=code, query=query_text, limit=semantic_limit)

        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "subject": subject,
            "position": self._position(code),
            "watchlist": self._watchlist(code),
            "alerts": self._alerts(code),
            "recent_events": events,
            "predictions": predictions,
            "semantic_knowledge": knowledge,
            "retrieval_mode": "exact+keyword" + ("+vector" if self._embedding_enabled else ""),
            "freshness": {
                "retrieved_at": datetime.now(UTC).isoformat(),
                "events_as_of": events[0].get("timestamp") if events else None,
                "predictions_as_of": predictions[0].get("created_at") if predictions else None,
            },
        }
        return result

    @staticmethod
    def _extract_code(query: str) -> str | None:
        match = _CODE_RE.search(query)
        return match.group(1) if match else None

    @staticmethod
    def _subject(subject_type: str | None, code: str | None, query: str) -> dict[str, Any]:
        if code:
            return {"type": "stock", "code": code}
        if subject_type in {"market", "sector", "portfolio", "stock"}:
            return {"type": subject_type, **({"keyword": query} if query else {})}
        return {"type": "market" if not query else "query", **({"query": query} if query else {})}

    def _events(
        self,
        *,
        code: str | None,
        scope: str | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if code:
            rows = self._episodic.query(code=code, limit=limit)
        elif scope:
            rows = self._episodic.query(scope=scope, limit=limit)
        else:
            rows = self._episodic.recent(days=90, limit=max(limit * 3, 20))
        if not code and query:
            tokens = _keywords(query)
            if tokens:
                rows = [row for row in rows if any(_contains_token(row, token) for token in tokens)]
        return [self._event_view(row) for row in rows[:limit]]

    def _predictions(self, *, code: str | None, query: str, limit: int) -> list[dict[str, Any]]:
        rows = (
            self._tracker.by_code(code, limit=limit) if code else self._tracker.all(limit=limit * 3)
        )
        if not code and query:
            tokens = _keywords(query)
            rows = [
                row
                for row in rows
                if any(token in str(row.get("prediction", "")) for token in tokens)
            ]
        return [
            {
                "id": row.get("id"),
                "code": row.get("code"),
                "name": row.get("name"),
                "prediction": row.get("prediction"),
                "direction": row.get("direction"),
                "timeframe": row.get("timeframe"),
                "status": row.get("status"),
                "confidence": row.get("accuracy_score"),
                "created_at": row.get("created_at"),
                "verified_at": row.get("verified_at"),
            }
            for row in rows[:limit]
        ]

    def _knowledge(self, *, code: str | None, query: str, limit: int) -> list[dict[str, Any]]:
        rows = self._semantic.get_active(limit=max(limit * 3, 20))
        exact_scope = f"stock:{code}" if code else None
        tokens = _keywords(query)

        def score(row: dict[str, Any]) -> tuple[int, str]:
            row_scope = str(row.get("scope", ""))
            content = str(row.get("content", ""))
            if exact_scope and row_scope == exact_scope:
                return (100, row_scope)
            hits = sum(1 for token in tokens if token in row_scope or token in content)
            return (hits, row_scope)

        ranked = sorted(rows, key=score, reverse=True)
        if exact_scope or tokens:
            ranked = [row for row in ranked if score(row)[0] > 0]
        return [
            {
                "id": row.get("id"),
                "knowledge_type": row.get("knowledge_type"),
                "scope": row.get("scope"),
                "content": row.get("content"),
                "confidence": row.get("confidence"),
                "status": row.get("status"),
                "updated_at": row.get("updated_at"),
            }
            for row in ranked[:limit]
        ]

    def _position(self, code: str | None) -> dict[str, Any]:
        if not code or self._portfolio_store is None:
            return {}
        for position in self._portfolio_store.list_positions():
            if position.code == code:
                return {
                    "code": position.code,
                    "name": position.name,
                    "shares": int(position.shares),
                    "buy_price": str(position.buy_price),
                }
        return {}

    def _watchlist(self, code: str | None) -> dict[str, Any]:
        if not code or self._watchlist_store is None:
            return {}
        entries = [entry for entry in self._watchlist_store.list_entries() if entry.code == code]
        return (
            {
                "code": code,
                "groups": [entry.group.name for entry in entries],
                "notes": [entry.note for entry in entries if entry.note],
            }
            if entries
            else {}
        )

    def _alerts(self, code: str | None) -> list[dict[str, Any]]:
        if self._portfolio_db is None:
            return []
        from mommy_chaogu.signals.custom_alerts import CustomAlertStore

        alerts = CustomAlertStore(self._portfolio_db).list_for_code(code) if code else []
        return [
            {
                "id": alert.id,
                "code": alert.code,
                "name": alert.name,
                "condition": alert.condition,
                "threshold": str(alert.threshold),
                "enabled": alert.enabled,
            }
            for alert in alerts
        ]

    @staticmethod
    def _event_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "event_type": row.get("event_type"),
            "scope": row.get("scope"),
            "code": row.get("code"),
            "name": row.get("name"),
            "summary": row.get("summary"),
            "timestamp": row.get("timestamp"),
            "source": row.get("source"),
            "confidence": row.get("confidence"),
            "data_coverage": row.get("data_coverage", {}),
            "prediction_id": row.get("prediction_id"),
        }


def _keywords(query: str) -> list[str]:
    """提取稳定关键词；禁止数字滑窗，避免 600519 误命中别的代码。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", query, flags=re.UNICODE)
    result: list[str] = []
    for token in cleaned.split():
        if token.isdigit() and len(token) != 6:
            continue
        if len(token) < 2:
            continue
        if token.isdigit() or not re.search(r"[\u4e00-\u9fff]", token):
            result.append(token)
        else:
            result.extend(token[i : i + 2] for i in range(len(token) - 1))
    return result


def _contains_token(row: dict[str, Any], token: str) -> bool:
    code = str(row.get("code") or "")
    if token.isdigit():
        return code == token
    haystack = " ".join(str(row.get(key) or "") for key in ("scope", "name", "summary"))
    return token in haystack


__all__ = ["ResearchContextService"]
