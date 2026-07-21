"""SignalStore：结构化信号历史存储（PLAN 三档 #10）。

把 Alerter 触发的信号持久化到 market.db 的 signal_events 表，
替代脆弱的文本日志解析（data/signals.log 的 format_log 与正则不匹配，
导致 /api/signals/history 在生产环境永远返回空）。

设计：
- 镜像 CacheStore 的 EngineOwner + sessionmaker 模式
- signal_events 表建在 MARKET_DB（信号属于行情事件）
- Decimal 存 TEXT（与项目惯例一致）
- 幂等建表（CREATE TABLE IF NOT EXISTS）
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from mommy_chaogu.db import EngineOwner, create_sqlite_engine
from mommy_chaogu.signals.types import Signal, SignalSeverity

SIGNAL_EVENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    trigger_value TEXT,
    threshold_value TEXT,
    metrics_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_signal_events_timestamp
    ON signal_events(timestamp DESC);

CREATE INDEX IF NOT EXISTS ix_signal_events_code
    ON signal_events(code);

CREATE INDEX IF NOT EXISTS ix_signal_events_rule_id
    ON signal_events(rule_id);
"""


def _decimal_to_text(val: Decimal | None) -> str | None:
    return str(val) if val is not None else None


def _text_to_decimal(val: str | None) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(val)
    except Exception:
        return None


class SignalStore(EngineOwner):
    """结构化信号历史存储（market.db / signal_events 表）。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_sqlite_engine(db_path)
        self._manage_engine()
        with self.engine.begin() as conn:
            for stmt in SIGNAL_EVENTS_SCHEMA_SQL.strip().split(";"):
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

    def insert(self, signals: list[Signal]) -> int:
        """批量插入信号记录，返回插入条数。"""
        if not signals:
            return 0
        with self.session() as s:
            for sig in signals:
                s.execute(
                    text(
                        """INSERT INTO signal_events
                           (timestamp, code, name, rule_id, severity, title, detail,
                            trigger_value, threshold_value, metrics_json)
                           VALUES (:ts, :code, :name, :rule_id, :severity, :title, :detail,
                                   :trigger, :threshold, :metrics)"""
                    ),
                    {
                        "ts": sig.timestamp,
                        "code": sig.code,
                        "name": sig.name,
                        "rule_id": sig.rule_id,
                        "severity": sig.severity.value,
                        "title": sig.title,
                        "detail": sig.detail,
                        "trigger": _decimal_to_text(sig.trigger_value),
                        "threshold": _decimal_to_text(sig.threshold_value),
                        "metrics": (
                            json.dumps(sig.metrics, ensure_ascii=False, default=str)
                            if sig.metrics
                            else None
                        ),
                    },
                )
        return len(signals)

    def list(
        self, limit: int = 50, rule_id: str | None = None, code: str | None = None
    ) -> list[dict[str, Any]]:
        """查询信号历史（按 timestamp 降序），返回 dict 列表。

        dict 字段与 SignalOut 对齐（timestamp/code/name/rule_id/severity/title/detail/
        trigger_value/threshold_value），供 web mapper 直接用。
        """
        query = (
            "SELECT timestamp, code, name, rule_id, severity, title, detail, "
            "trigger_value, threshold_value, metrics_json "
            "FROM signal_events"
        )
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if rule_id is not None:
            conditions.append("rule_id = :rule_id")
            params["rule_id"] = rule_id
        if code is not None:
            conditions.append("code = :code")
            params["code"] = code
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT :limit"

        with self.session() as s:
            rows = s.execute(text(query), params).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "timestamp": row[0],
                    "code": row[1],
                    "name": row[2],
                    "rule_id": row[3],
                    "severity": row[4],
                    "title": row[5],
                    "detail": row[6],
                    "trigger_value": _text_to_decimal(row[7]),
                    "threshold_value": _text_to_decimal(row[8]),
                }
            )
        return results

    def count(self) -> int:
        """总记录数（供迁移脚本 --check 用）。"""
        with self.session() as s:
            row = s.execute(text("SELECT COUNT(*) FROM signal_events")).first()
            return int(row[0]) if row else 0

    @staticmethod
    def row_to_signal(row: dict[str, Any]) -> Signal:
        """dict → Signal dataclass（供 web mapper 或测试用）。"""
        sev = row["severity"]
        if isinstance(sev, str):
            sev = SignalSeverity(sev)
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return Signal(
            timestamp=ts,
            code=row["code"],
            name=row["name"],
            rule_id=row["rule_id"],
            severity=sev,
            title=row["title"],
            detail=row["detail"],
            trigger_value=row.get("trigger_value"),
            threshold_value=row.get("threshold_value"),
        )
