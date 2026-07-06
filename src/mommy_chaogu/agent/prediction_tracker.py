"""PredictionTracker：Agent 预测追踪（SQLite 持久化）。

记录 agent 对个股做出的预测，并在到期后验证命中与否。表 predictions
存储预测方向、目标价、止损价、依据等，到期后回填实际价格与命中状态，
用于长期评估 agent 的预测准确度。
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
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    prediction TEXT NOT NULL,
    direction TEXT NOT NULL,
    rationale TEXT,
    target_price REAL,
    entry_price REAL,
    stop_loss REAL,
    change_pct_at_creation REAL,
    timeframe TEXT NOT NULL,
    verify_after TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_at TEXT,
    actual_price REAL,
    actual_change_pct REAL,
    accuracy_score REAL,
    verify_attempts INTEGER DEFAULT 0,
    verify_log TEXT,
    data_coverage_at_creation TEXT,
    data_coverage_at_verify TEXT,
    source_event_id INTEGER,
    insight_event_id INTEGER
);

CREATE INDEX IF NOT EXISTS ix_pred_status ON predictions(status);
CREATE INDEX IF NOT EXISTS ix_pred_code ON predictions(code);
CREATE INDEX IF NOT EXISTS ix_pred_verify_after ON predictions(verify_after);
"""

# timeframe → 到期前推天数（日历日）。
#
# 这是权威来源：verify_engine 也复用同一个映射，确保"5d" 预测的 verify_after
# （到期可验证时间）与 _is_expired（过期时间）用的是同一天数。
_TIMEFRAME_DAYS: dict[str, int] = {
    "1d": 1,
    "3d": 3,
    "5d": 5,
    "10d": 10,
    "20d": 20,
    "60d": 60,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _compute_verify_after(timeframe: str) -> str:
    """根据 timeframe 计算到期 ISO 时间字符串。

    使用日历日映射（见 :data:`_TIMEFRAME_DAYS`）：
    ``"1d" → +1 天``，``"5d" → +5 天``，``"20d" → +20 天``，``"60d" → +60 天``。
    未知 timeframe 默认 +5 天（与 verify_engine 一致）。
    """
    days = _TIMEFRAME_DAYS.get(timeframe, 5)
    return (_utcnow() + timedelta(days=days)).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将一行查询结果转为字典。"""
    cols = list(row._mapping.keys())
    return {col: row._mapping[col] for col in cols}


class PredictionTracker:
    """预测追踪：SQLite 持久化的 agent 预测记录与验证状态。

    用法::

        tracker = PredictionTracker(Path("data/watchlist.db"))
        pid = tracker.create(code="600519", name="贵州茅台",
                             prediction="看涨", direction="up",
                             timeframe="5d")
        due = tracker.get_pending(verify_after_now)
        tracker.update_status(pid, status="hit", actual_price=1800.0)
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

    def create(
        self,
        code: str,
        name: str | None,
        prediction: str,
        direction: str,
        timeframe: str,
        rationale: str | None = None,
        target_price: float | None = None,
        entry_price: float | None = None,
        stop_loss: float | None = None,
        change_pct_at_creation: float | None = None,
        data_coverage: dict[str, bool] | None = None,
        source_event_id: int | None = None,
    ) -> int:
        """创建一条预测，返回自增 id。

        *timeframe* 决定到期时间（``verify_after``）。*data_coverage*
        会被序列化为 JSON 写入 ``data_coverage_at_creation``。
        """
        created_at = _utcnow().isoformat()
        verify_after = _compute_verify_after(timeframe)
        coverage_json = json.dumps(data_coverage) if data_coverage else None
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO predictions (
                        created_at, code, name, prediction, direction,
                        rationale, target_price, entry_price, stop_loss,
                        change_pct_at_creation, timeframe, verify_after,
                        status, data_coverage_at_creation, source_event_id
                    )
                    VALUES (
                        :created_at, :code, :name, :prediction, :direction,
                        :rationale, :target_price, :entry_price, :stop_loss,
                        :change_pct_at_creation, :timeframe, :verify_after,
                        'pending', :data_coverage_at_creation, :source_event_id
                    )
                """),
                {
                    "created_at": created_at,
                    "code": code,
                    "name": name,
                    "prediction": prediction,
                    "direction": direction,
                    "rationale": rationale,
                    "target_price": target_price,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "change_pct_at_creation": change_pct_at_creation,
                    "timeframe": timeframe,
                    "verify_after": verify_after,
                    "data_coverage_at_creation": coverage_json,
                    "source_event_id": source_event_id,
                },
            )
            return result.lastrowid or 0

    def get_pending(self, verify_before: str) -> list[dict[str, Any]]:
        """返回已到期且仍未验证（``status = 'pending'``）的预测。

        按 ``verify_after`` 升序排列。
        """
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT * FROM predictions
                    WHERE status = 'pending' AND verify_after <= :verify_before
                    ORDER BY verify_after ASC
                """),
                {"verify_before": verify_before},
            ).all()
            return [_row_to_dict(r) for r in rows]

    def get_by_id(self, pred_id: int) -> dict[str, Any] | None:
        """按 id 取单条预测，不存在返回 None。"""
        with self.session() as s:
            row = s.execute(
                text("SELECT * FROM predictions WHERE id = :id"),
                {"id": pred_id},
            ).first()
            return _row_to_dict(row) if row else None

    def update_status(
        self,
        pred_id: int,
        status: str,
        actual_price: float | None = None,
        actual_change_pct: float | None = None,
        accuracy_score: float | None = None,
        data_coverage: dict[str, bool] | None = None,
    ) -> None:
        """更新预测状态，回填验证结果。

        设置 ``verified_at`` 为当前时间，并填入实际价格、实际涨跌幅、
        命中分。*data_coverage* 序列化为 JSON 写入 ``data_coverage_at_verify``。
        """
        verified_at = _utcnow().isoformat()
        coverage_json = json.dumps(data_coverage) if data_coverage else None
        with self.session() as s:
            s.execute(
                text("""
                    UPDATE predictions
                    SET status = :status,
                        verified_at = :verified_at,
                        actual_price = :actual_price,
                        actual_change_pct = :actual_change_pct,
                        accuracy_score = :accuracy_score,
                        data_coverage_at_verify = :data_coverage_at_verify
                    WHERE id = :id
                """),
                {
                    "id": pred_id,
                    "status": status,
                    "verified_at": verified_at,
                    "actual_price": actual_price,
                    "actual_change_pct": actual_change_pct,
                    "accuracy_score": accuracy_score,
                    "data_coverage_at_verify": coverage_json,
                },
            )

    def increment_attempts(self, pred_id: int, reason: str) -> None:
        """``verify_attempts`` 加 1，并向 ``verify_log`` 追加一条记录。

        ``verify_log`` 是 JSON 数组，每条形如
        ``{"attempt": N, "time": "...", "reason": reason}``。
        """
        with self.session() as s:
            row = s.execute(
                text("SELECT verify_attempts, verify_log FROM predictions WHERE id = :id"),
                {"id": pred_id},
            ).first()
            if row is None:
                return
            attempts = (row._mapping["verify_attempts"] or 0) + 1
            log_raw = row._mapping["verify_log"]
            log: list[dict[str, Any]] = json.loads(log_raw) if log_raw else []
            log.append(
                {
                    "attempt": attempts,
                    "time": _utcnow().isoformat(),
                    "reason": reason,
                }
            )
            s.execute(
                text("""
                    UPDATE predictions
                    SET verify_attempts = :attempts, verify_log = :log
                    WHERE id = :id
                """),
                {
                    "id": pred_id,
                    "attempts": attempts,
                    "log": json.dumps(log),
                },
            )

    def recent_verified(self, limit: int = 5) -> list[dict[str, Any]]:
        """返回最近 *limit* 条已验证（hit/missed）预测，按 verified_at 降序。"""
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT * FROM predictions
                    WHERE status IN ('hit', 'missed')
                    ORDER BY verified_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            ).all()
            return [_row_to_dict(r) for r in rows]

    def all(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        """返回所有预测，按 created_at 降序，可选 status 过滤。"""
        with self.session() as s:
            if status is not None:
                rows = s.execute(
                    text("""
                        SELECT * FROM predictions
                        WHERE status = :status
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"status": status, "limit": limit},
                ).all()
            else:
                rows = s.execute(
                    text("""
                        SELECT * FROM predictions
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"limit": limit},
                ).all()
            return [_row_to_dict(r) for r in rows]

    def cleanup_old(self, days: int = 90) -> int:
        """删除 *days* 天前已验证/过期的预测，返回删除条数。

        只删 ``status IN ('hit', 'missed', 'expired')`` 的；``pending``
        永远不删（未验证的预测可能仍在等待数据）。判定时间用
        ``created_at``（预测创建时间）。
        """
        cutoff = (_utcnow() - timedelta(days=days)).isoformat()
        with self.session() as s:
            result = s.execute(
                text("""
                    DELETE FROM predictions
                    WHERE status IN ('hit', 'missed', 'expired')
                      AND created_at < :cutoff
                """),
                {"cutoff": cutoff},
            )
            return result.rowcount or 0

    def stats(self) -> dict[str, Any]:
        """返回预测统计：总数、各状态计数与命中率。

        ``hit_rate = hit / (hit + missed)``；若 hit+missed==0 则为 0.0。
        """
        with self.session() as s:
            total = s.execute(text("SELECT COUNT(*) FROM predictions")).scalar() or 0
            pending = (
                s.execute(
                    text("SELECT COUNT(*) FROM predictions WHERE status = 'pending'")
                ).scalar()
                or 0
            )
            hit = (
                s.execute(text("SELECT COUNT(*) FROM predictions WHERE status = 'hit'")).scalar()
                or 0
            )
            missed = (
                s.execute(text("SELECT COUNT(*) FROM predictions WHERE status = 'missed'")).scalar()
                or 0
            )
            expired = (
                s.execute(
                    text("SELECT COUNT(*) FROM predictions WHERE status = 'expired'")
                ).scalar()
                or 0
            )
            unverifiable = (
                s.execute(
                    text("SELECT COUNT(*) FROM predictions WHERE status = 'unverifiable'")
                ).scalar()
                or 0
            )
        judged = hit + missed
        hit_rate = hit / judged if judged > 0 else 0.0
        return {
            "total": total,
            "pending": pending,
            "hit": hit,
            "missed": missed,
            "expired": expired,
            "unverifiable": unverifiable,
            "hit_rate": hit_rate,
        }
