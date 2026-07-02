"""earnings 模块 — 高层 Service API。

封装：
- pull_actual()：从 adapter 拉 actual 写入 store
- score_one()：拿 actual + predicted 计算 EarningsScore
- score_all()：批量计算某 period 的所有 actual 对应的 score
- watch_calendar()：列出未来 N 天的披露日历
- summary()：汇总某 period 的比对结果
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.earnings.adapter import EarningsAdapter
from mommy_chaogu.earnings.store import EarningsStore
from mommy_chaogu.earnings.types import EarningsScore, EarningsVerdict


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """Service 操作的批量结果。"""

    ok: int
    failed: int
    failed_codes: list[str]
    elapsed_seconds: float


class EarningsService:
    """业绩高层 Service。

        依赖：
    - EarningsAdapter：数据源（mock / efinance / tencent）
    - EarningsStore：本地存储（data/earnings_actual.db）
    - 外部：业绩前瞻 DB（data/earnings_preview.db，用于 score 比对）
    """

    def __init__(
        self,
        adapter: EarningsAdapter,
        store: EarningsStore,
        preview_db_path: Path,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.preview_db_path = preview_db_path

    # ---------- 拉取 actual ----------

    def pull_actual(
        self,
        codes: list[str],
        period: str,
    ) -> ServiceResult:
        """批量拉取 actual 写入 store。"""
        import time

        start = time.time()
        ok = 0
        failed: list[str] = []

        for code in codes:
            try:
                actuals = self.adapter.fetch_actual(code, period)
                for actual in actuals:
                    self.store.upsert_actual(actual)
                if actuals:
                    ok += 1
                else:
                    failed.append(code)
            except Exception:
                failed.append(code)

        return ServiceResult(
            ok=ok,
            failed=len(failed),
            failed_codes=failed,
            elapsed_seconds=time.time() - start,
        )

    # ---------- 比对 ----------

    def _load_predicted(self, code: str, period: str) -> tuple[str, Decimal, Decimal] | None:
        """从 earnings_preview.db 读取某 code+period 的预测区间。

        Returns: (name, predicted_low, predicted_high) or None。
        """
        if not self.preview_db_path.exists():
            return None

        conn = sqlite3.connect(str(self.preview_db_path))
        try:
            row = conn.execute(
                """
                SELECT name, growth_low, growth_high
                FROM earnings_preview
                WHERE code = ? AND report_period = ?
                LIMIT 1
                """,
                (code, period),
            ).fetchone()
            if row is None:
                return None
            return row[0], Decimal(str(row[1])), Decimal(str(row[2]))
        finally:
            conn.close()

    def score_one(self, code: str, period: str) -> EarningsScore | None:
        """计算一只股的 EarningsScore（actual vs predicted）。

        如果 actual 还没入库，返回 None。
        """
        actual = self.store.get_actual(code, period)
        if actual is None:
            return None
        predicted = self._load_predicted(code, period)
        if predicted is None:
            return None

        name, low, high = predicted
        mid = (low + high) / 2

        if actual.growth_pct is None:
            return EarningsScore(
                code=code,
                name=name,
                period=period,
                predicted_low=low,
                predicted_high=high,
                predicted_mid=mid,
                actual_value=actual.actual_value,
                actual_growth=None,
                gap_to_mid=None,
                gap_to_high=None,
                verdict=EarningsVerdict.UNKNOWN,
                confidence=Decimal("0.0"),
            )

        g = actual.growth_pct
        gap_to_mid = g - mid
        gap_to_high = g - high

        # 判定 verdict
        if g > high:
            verdict = EarningsVerdict.SUPER_BEAT
        elif g > mid:
            verdict = EarningsVerdict.BEAT
        elif g >= low:
            verdict = EarningsVerdict.MEET
        elif g >= (low + (mid - low) * Decimal("0.5")):
            verdict = EarningsVerdict.MISS
        else:
            verdict = EarningsVerdict.DEEP_MISS

        # 置信度：区间越窄，置信度越高
        span = high - low
        if span > 200:
            confidence = Decimal("0.6")
        elif span > 100:
            confidence = Decimal("0.75")
        elif span > 50:
            confidence = Decimal("0.85")
        else:
            confidence = Decimal("0.95")

        return EarningsScore(
            code=code,
            name=name,
            period=period,
            predicted_low=low,
            predicted_high=high,
            predicted_mid=mid,
            actual_value=actual.actual_value,
            actual_growth=g,
            gap_to_mid=gap_to_mid,
            gap_to_high=gap_to_high,
            verdict=verdict,
            confidence=confidence,
        )

    def score_all(self, period: str) -> ServiceResult:
        """批量计算 period 内所有 actual 的 score。"""
        import time

        start = time.time()
        actuals = self.store.list_actuals(period=period)
        ok = 0
        failed: list[str] = []

        for actual in actuals:
            try:
                score = self.score_one(actual.code, period)
                if score is None:
                    failed.append(actual.code)
                    continue
                self.store.upsert_score(score)
                ok += 1
            except Exception:
                failed.append(actual.code)

        return ServiceResult(
            ok=ok,
            failed=len(failed),
            failed_codes=failed,
            elapsed_seconds=time.time() - start,
        )

    # ---------- 日历 ----------

    def fetch_calendar(
        self,
        codes: list[str],
        period: str | None = None,
    ) -> ServiceResult:
        """拉取并写入公告日历。"""
        import time

        start = time.time()
        ok = 0
        failed: list[str] = []

        for code in codes:
            try:
                cals = self.adapter.fetch_calendar(code)
                for cal in cals:
                    if period and cal.period != period:
                        continue
                    self.store.upsert_calendar(cal)
                    ok += 1
            except Exception:
                failed.append(code)

        return ServiceResult(
            ok=ok,
            failed=len(failed),
            failed_codes=failed,
            elapsed_seconds=time.time() - start,
        )

    def watch_calendar(
        self,
        days_ahead: int = 7,
        period: str | None = None,
    ) -> list[tuple[str, str, date]]:
        """列出未来 N 天的披露日历。

        Returns: [(code, period, date), ...] 按日期排序。
        """
        rows = self.store.list_calendars(days_ahead=days_ahead, period=period)
        return [(r.code, r.period, r.disclosure_date) for r in rows]

    # ---------- 摘要 ----------

    def summary(self, period: str) -> dict[EarningsVerdict, int]:
        """汇总某 period 的 verdict 分布。"""
        from collections import Counter

        scores = self.store.list_scores(period=period)
        counts: Counter[EarningsVerdict] = Counter(s.verdict for s in scores)
        return dict(counts)
