"""earnings 模块 — Service 单元测试。"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.earnings.adapter import MockEarningsAdapter
from mommy_chaogu.earnings.service import EarningsService
from mommy_chaogu.earnings.store import EarningsStore
from mommy_chaogu.earnings.types import EarningsVerdict


@pytest.fixture
def preview_db(tmp_path: Path) -> Path:
    """建一个迷你 earnings_preview.db 给 service 用。"""
    db_path = tmp_path / "preview.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE earnings_preview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            sector TEXT,
            subsector TEXT,
            growth_low REAL NOT NULL,
            growth_high REAL NOT NULL,
            growth_mid REAL NOT NULL,
            growth_text TEXT,
            core_driver TEXT,
            highlight TEXT,
            report_period TEXT NOT NULL,
            report_source TEXT NOT NULL,
            report_date TEXT NOT NULL,
            watchlist_flag INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO earnings_preview
            (code, name, sector, subsector, growth_low, growth_high, growth_mid,
             growth_text, core_driver, highlight,
             report_period, report_source, report_date)
        VALUES
            ('603662', '柯力传感', '传感器', '六维力',
             188.0, 217.0, 202.5, '+188%~+217%', '机器人/工业', '⭐',
             'H1 2026', '中信证券', '2026-07-02'),
            ('603986', '兆易创新', '半导体', '存储',
             1070.0, 1370.0, 1220.0, '+1070%~+1370%', 'AI/涨价', '...',
             'H1 2026', '中信证券', '2026-07-02');
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def earnings_store(tmp_path: Path) -> EarningsStore:
    db_path = tmp_path / "actual.db"
    s = EarningsStore(db_path)
    yield s
    s.close()


@pytest.fixture
def service(preview_db: Path, earnings_store: EarningsStore) -> EarningsService:
    return EarningsService(
        adapter=MockEarningsAdapter(),
        store=earnings_store,
        preview_db_path=preview_db,
    )


def test_pull_actual_from_mock(service: EarningsService):
    """Mock adapter 应该返回数据并写入 store。"""
    result = service.pull_actual(["603662", "603986"], "H1 2026")
    assert result.ok == 2
    assert result.failed == 0
    assert result.failed_codes == []

    actuals = service.store.list_actuals(period="H1 2026")
    assert len(actuals) == 2


def test_pull_actual_unknown_code(service: EarningsService):
    """Mock 没有的 code 应计入 failed。"""
    result = service.pull_actual(["999999"], "H1 2026")
    assert result.ok == 0
    assert result.failed == 1
    assert "999999" in result.failed_codes


def test_score_one_super_beat(service: EarningsService):
    """Mock 返回的是 mid（中位），score 应为 MEET。"""
    service.pull_actual(["603662"], "H1 2026")
    score = service.score_one("603662", "H1 2026")
    assert score is not None
    # Mock 用了 mid = 202.5%，所以应在 [188, 202.5] → MEET
    assert score.verdict == EarningsVerdict.MEET


def test_score_one_no_actual(service: EarningsService):
    """如果 actual 未入库，score 应返回 None。"""
    score = service.score_one("603662", "H1 2026")
    assert score is None


def test_score_one_no_predicted(service: EarningsService, earnings_store: EarningsStore):
    """如果 preview 库没有这只股，score 应返回 None。"""
    from mommy_chaogu.earnings.types import EarningsActual, EarningsSource

    a = EarningsActual(
        code="999999",
        name="未知",
        period="H1 2026",
        actual_value=Decimal("100"),
        growth_pct=Decimal("100"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    earnings_store.upsert_actual(a)

    score = service.score_one("999999", "H1 2026")
    assert score is None


def test_score_all_batch(service: EarningsService):
    """score_all 应批量计算并写入。"""
    service.pull_actual(["603662", "603986"], "H1 2026")
    result = service.score_all("H1 2026")
    assert result.ok == 2

    scores = service.store.list_scores(period="H1 2026")
    assert len(scores) == 2


def test_score_verdict_logic_at_low(service: EarningsService):
    """如果实际 = low，应为 MEET（边界）。"""
    from mommy_chaogu.earnings.types import EarningsActual, EarningsSource

    # 手动写入 actual = low = 188
    a = EarningsActual(
        code="603662",
        name="柯力",
        period="H1 2026",
        actual_value=Decimal("850000000"),
        growth_pct=Decimal("188.0"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    service.store.upsert_actual(a)

    score = service.score_one("603662", "H1 2026")
    assert score is not None
    assert score.verdict == EarningsVerdict.MEET  # g == low 时是 MEET


def test_score_verdict_above_high(service: EarningsService):
    """actual > high 应为 SUPER_BEAT。"""
    from mommy_chaogu.earnings.types import EarningsActual, EarningsSource

    a = EarningsActual(
        code="603662",
        name="柯力",
        period="H1 2026",
        actual_value=Decimal("900000000"),
        growth_pct=Decimal("225.0"),  # > 217
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    service.store.upsert_actual(a)

    score = service.score_one("603662", "H1 2026")
    assert score is not None
    assert score.verdict == EarningsVerdict.SUPER_BEAT


def test_score_verdict_deep_miss(service: EarningsService):
    """actual < (low + (mid-low)*0.5) 应为 DEEP_MISS。

    For 603662: low=188, mid=202.5, half_loss=195.25
    So actual < 195.25 → DEEP_MISS
    """
    from mommy_chaogu.earnings.types import EarningsActual, EarningsSource

    a = EarningsActual(
        code="603662",
        name="柯力",
        period="H1 2026",
        actual_value=Decimal("600000000"),
        growth_pct=Decimal("150.0"),  # < 195.25
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    service.store.upsert_actual(a)

    score = service.score_one("603662", "H1 2026")
    assert score is not None
    assert score.verdict == EarningsVerdict.DEEP_MISS


def test_summary_returns_counts(service: EarningsService):
    """summary 应返回 verdict 分布。"""
    from mommy_chaogu.earnings.types import EarningsActual, EarningsSource

    # 1 个 SUPER_BEAT
    a1 = EarningsActual(
        code="603662",
        name="柯力",
        period="H1 2026",
        actual_value=Decimal("1"),
        growth_pct=Decimal("225"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    # 1 个 DEEP_MISS
    a2 = EarningsActual(
        code="603986",
        name="兆易",
        period="H1 2026",
        actual_value=Decimal("1"),
        growth_pct=Decimal("900"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    service.store.upsert_actual(a1)
    service.store.upsert_actual(a2)
    service.score_all("H1 2026")

    summary = service.summary("H1 2026")
    assert summary.get(EarningsVerdict.SUPER_BEAT) == 1
    assert summary.get(EarningsVerdict.DEEP_MISS) == 1


def test_watch_calendar_empty(service: EarningsService):
    """没有任何日历时应返回空。"""
    upcoming = service.watch_calendar(days_ahead=30)
    assert upcoming == []


def test_watch_calendar_with_data(service: EarningsService):
    """有数据时按日期排序。"""
    from mommy_chaogu.earnings.types import EarningsCalendar

    c1 = EarningsCalendar(
        code="603662",
        name="柯力",
        period="H1 2026",
        disclosure_date=date.today(),
        is_estimated=False,
        source="x",
    )
    c2 = EarningsCalendar(
        code="603986",
        name="兆易",
        period="H1 2026",
        disclosure_date=date.today(),
        is_estimated=False,
        source="x",
    )
    service.store.upsert_calendar(c1)
    service.store.upsert_calendar(c2)

    upcoming = service.watch_calendar(days_ahead=7)
    assert len(upcoming) == 2
