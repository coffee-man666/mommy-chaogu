"""earnings 模块 — SQLite 存储。

设计：与 CacheStore 类似的 dataclass + sqlite3 text-mode 模式（Decimal 精度安全）。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.earnings.schema import SCHEMA_SQL
from mommy_chaogu.earnings.types import (
    EarningsActual,
    EarningsCalendar,
    EarningsScore,
    EarningsVerdict,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EarningsStore:
    """业绩数据 SQLite 存储。

    所有金额用 TEXT 存 Decimal（避免 SQLite 浮点精度问题）。
    所有时间戳用 ISO-8601 字符串。
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: sqlite3.Connection = sqlite3.connect(
            str(db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self.engine.row_factory = sqlite3.Row
        self.engine.executescript(SCHEMA_SQL)
        self.engine.commit()

    def close(self) -> None:
        self.engine.close()

    @contextmanager
    def _tx(self):  # type: ignore[no-untyped-def]
        """事务上下文。"""
        try:
            yield self.engine
            self.engine.commit()
        except Exception:
            self.engine.rollback()
            raise

    # ---------- EarningsActual CRUD ----------

    def upsert_actual(self, actual: EarningsActual) -> bool:
        """插入或更新 actual 记录。返回 True 表示新增，False 表示覆盖。"""
        with self._tx() as conn:
            cursor = conn.execute(
                "SELECT id FROM earnings_actual WHERE code = ? AND period = ? AND source = ?",
                (actual.code, actual.period, actual.source.value),
            )
            existing = cursor.fetchone()

            params = (
                actual.code,
                actual.name,
                actual.period,
                str(actual.actual_value),
                str(actual.growth_pct) if actual.growth_pct is not None else None,
                actual.disclosure_date.isoformat(),
                actual.source.value,
                actual.note,
                actual.fetched_at.isoformat() if actual.fetched_at else None,
            )

            if existing:
                # params 索引: 0=code, 1=name, 2=period, 3=actual_value,
                #              4=growth_pct, 5=disclosure_date, 6=source,
                #              7=note, 8=fetched_at
                conn.execute(
                    """
                    UPDATE earnings_actual SET
                        name = ?, actual_value = ?, growth_pct = ?,
                        disclosure_date = ?, source = ?, note = ?, fetched_at = ?
                    WHERE code = ? AND period = ? AND source = ?
                    """,
                    (
                        params[1],
                        params[3],
                        params[4],
                        params[5],
                        params[6],
                        params[7],
                        params[8],
                        params[0],
                        params[2],
                        params[6],
                    ),
                )
                return False

            conn.execute(
                """
                INSERT INTO earnings_actual (
                    code, name, period, actual_value, growth_pct,
                    disclosure_date, source, note, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            return True

    def list_actuals(
        self,
        period: str | None = None,
        since_date: str | None = None,
    ) -> list[EarningsActual]:
        """列出 actual 记录。"""
        query = "SELECT * FROM earnings_actual"
        clauses: list[str] = []
        params: list[object] = []
        if period:
            clauses.append("period = ?")
            params.append(period)
        if since_date:
            clauses.append("disclosure_date >= ?")
            params.append(since_date)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY disclosure_date DESC, code"

        rows = self.engine.execute(query, params).fetchall()
        return [self._row_to_actual(r) for r in rows]

    def get_actual(self, code: str, period: str) -> EarningsActual | None:
        row = self.engine.execute(
            """
            SELECT * FROM earnings_actual
            WHERE code = ? AND period = ?
            ORDER BY source DESC  -- 优先 REPORT > EXPRESS > FORECAST
            LIMIT 1
            """,
            (code, period),
        ).fetchone()
        return self._row_to_actual(row) if row else None

    @staticmethod
    def _row_to_actual(row: sqlite3.Row) -> EarningsActual:
        from datetime import date as _date

        from mommy_chaogu.earnings.types import EarningsSource

        return EarningsActual(
            code=row["code"],
            name=row["name"],
            period=row["period"],
            actual_value=Decimal(row["actual_value"]),
            growth_pct=Decimal(row["growth_pct"]) if row["growth_pct"] else None,
            disclosure_date=_date.fromisoformat(row["disclosure_date"]),
            source=EarningsSource(row["source"]),
            note=row["note"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else None,
        )

    # ---------- EarningsCalendar CRUD ----------

    def upsert_calendar(self, cal: EarningsCalendar) -> bool:
        with self._tx() as conn:
            cursor = conn.execute(
                "SELECT id FROM earnings_calendar WHERE code = ? AND period = ?",
                (cal.code, cal.period),
            )
            existing = cursor.fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE earnings_calendar SET
                        name = ?, disclosure_date = ?, is_estimated = ?, source = ?
                    WHERE code = ? AND period = ?
                    """,
                    (
                        cal.name,
                        cal.disclosure_date.isoformat(),
                        1 if cal.is_estimated else 0,
                        cal.source,
                        cal.code,
                        cal.period,
                    ),
                )
                return False
            conn.execute(
                """
                INSERT INTO earnings_calendar (
                    code, name, period, disclosure_date, is_estimated, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cal.code,
                    cal.name,
                    cal.period,
                    cal.disclosure_date.isoformat(),
                    1 if cal.is_estimated else 0,
                    cal.source,
                ),
            )
            return True

    def list_calendars(
        self,
        since_date: str | None = None,
        period: str | None = None,
        days_ahead: int | None = None,
    ) -> list[EarningsCalendar]:
        """列出日历，可按日期范围过滤。"""
        query = "SELECT * FROM earnings_calendar"
        clauses: list[str] = []
        params: list[object] = []
        if since_date:
            clauses.append("disclosure_date >= ?")
            params.append(since_date)
        if period:
            clauses.append("period = ?")
            params.append(period)
        if days_ahead is not None:
            clauses.append(f"disclosure_date <= date('now', '+{int(days_ahead)} days')")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY disclosure_date"

        rows = self.engine.execute(query, params).fetchall()
        return [self._row_to_calendar(r) for r in rows]

    @staticmethod
    def _row_to_calendar(row: sqlite3.Row) -> EarningsCalendar:
        from datetime import date as _date

        return EarningsCalendar(
            code=row["code"],
            name=row["name"],
            period=row["period"],
            disclosure_date=_date.fromisoformat(row["disclosure_date"]),
            is_estimated=bool(row["is_estimated"]),
            source=row["source"],
        )

    # ---------- EarningsScore CRUD ----------

    def upsert_score(self, score: EarningsScore) -> bool:
        with self._tx() as conn:
            cursor = conn.execute(
                "SELECT id FROM earnings_score WHERE code = ? AND period = ?",
                (score.code, score.period),
            )
            existing = cursor.fetchone()

            params = (
                score.code,
                score.name,
                score.period,
                str(score.predicted_low),
                str(score.predicted_high),
                str(score.predicted_mid),
                str(score.actual_value),
                str(score.actual_growth) if score.actual_growth is not None else None,
                str(score.gap_to_mid) if score.gap_to_mid is not None else None,
                str(score.gap_to_high) if score.gap_to_high is not None else None,
                score.verdict.value,
                str(score.confidence),
            )

            if existing:
                # params 索引: 0=code, 1=name, 2=period, 3=predicted_low,
                #              4=predicted_high, 5=predicted_mid, 6=actual_value,
                #              7=actual_growth, 8=gap_to_mid, 9=gap_to_high,
                #              10=verdict, 11=confidence
                conn.execute(
                    """
                    UPDATE earnings_score SET
                        name = ?, predicted_low = ?, predicted_high = ?, predicted_mid = ?,
                        actual_value = ?, actual_growth = ?, gap_to_mid = ?, gap_to_high = ?,
                        verdict = ?, confidence = ?, scored_at = CURRENT_TIMESTAMP
                    WHERE code = ? AND period = ?
                    """,
                    (
                        params[1],
                        params[3],
                        params[4],
                        params[5],
                        params[6],
                        params[7],
                        params[8],
                        params[9],
                        params[10],
                        params[11],
                        params[0],
                        params[2],
                    ),
                )
                return False

            conn.execute(
                """
                INSERT INTO earnings_score (
                    code, name, period,
                    predicted_low, predicted_high, predicted_mid,
                    actual_value, actual_growth, gap_to_mid, gap_to_high,
                    verdict, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            return True

    def list_scores(
        self,
        period: str | None = None,
        verdict: EarningsVerdict | None = None,
    ) -> list[EarningsScore]:
        query = "SELECT * FROM earnings_score"
        clauses: list[str] = []
        params: list[object] = []
        if period:
            clauses.append("period = ?")
            params.append(period)
        if verdict:
            clauses.append("verdict = ?")
            params.append(verdict.value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY confidence DESC, gap_to_high DESC"

        rows = self.engine.execute(query, params).fetchall()
        return [self._row_to_score(r) for r in rows]

    @staticmethod
    def _row_to_score(row: sqlite3.Row) -> EarningsScore:
        return EarningsScore(
            code=row["code"],
            name=row["name"],
            period=row["period"],
            predicted_low=Decimal(row["predicted_low"]),
            predicted_high=Decimal(row["predicted_high"]),
            predicted_mid=Decimal(row["predicted_mid"]),
            actual_value=Decimal(row["actual_value"]),
            actual_growth=Decimal(row["actual_growth"]) if row["actual_growth"] else None,
            gap_to_mid=Decimal(row["gap_to_mid"]) if row["gap_to_mid"] else None,
            gap_to_high=Decimal(row["gap_to_high"]) if row["gap_to_high"] else None,
            verdict=EarningsVerdict(row["verdict"]),
            confidence=Decimal(row["confidence"]),
        )
