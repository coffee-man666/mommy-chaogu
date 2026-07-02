"""earnings 模块 — Store 单元测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.earnings.store import EarningsStore
from mommy_chaogu.earnings.types import (
    EarningsActual,
    EarningsCalendar,
    EarningsScore,
    EarningsSource,
    EarningsVerdict,
)


@pytest.fixture
def store(tmp_path: Path) -> EarningsStore:
    db_path = tmp_path / "test_earnings.db"
    s = EarningsStore(db_path)
    yield s
    s.close()


def test_init_creates_tables(store: EarningsStore):
    """init 后 3 张表都应存在。"""
    rows = store.engine.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [r[0] for r in rows]
    assert "earnings_actual" in table_names
    assert "earnings_score" in table_names
    assert "earnings_calendar" in table_names


def test_upsert_actual_insert(store: EarningsStore):
    a = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("850000000"),
        growth_pct=Decimal("200.0"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    is_new = store.upsert_actual(a)
    assert is_new is True

    got = store.get_actual("603662", "H1 2026")
    assert got is not None
    assert got.actual_value == Decimal("850000000")
    assert got.growth_pct == Decimal("200.0")


def test_upsert_actual_update(store: EarningsStore):
    """同 (code, period, source) 二次写入应更新。"""
    a = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("850000000"),
        growth_pct=Decimal("200.0"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    store.upsert_actual(a)

    a2 = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("900000000"),  # 更新
        growth_pct=Decimal("215.0"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    is_new = store.upsert_actual(a2)
    assert is_new is False  # 不是新增

    got = store.get_actual("603662", "H1 2026")
    assert got.actual_value == Decimal("900000000")


def test_different_source_coexists(store: EarningsStore):
    """同一股同一期，FORECAST 和 REPORT 两个 source 可共存。"""
    a_forecast = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("850000000"),
        growth_pct=Decimal("200.0"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    a_report = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("900000000"),
        growth_pct=Decimal("215.0"),
        disclosure_date=date(2026, 8, 15),
        source=EarningsSource.REPORT,
    )
    store.upsert_actual(a_forecast)
    store.upsert_actual(a_report)

    # get_actual 默认返回 REPORT（更精确）
    got = store.get_actual("603662", "H1 2026")
    assert got is not None
    assert got.source == EarningsSource.REPORT
    assert got.actual_value == Decimal("900000000")

    # list_actuals 返回 2 条
    actuals = store.list_actuals(period="H1 2026")
    assert len(actuals) == 2


def test_upsert_calendar(store: EarningsStore):
    c = EarningsCalendar(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        disclosure_date=date(2026, 7, 20),
        is_estimated=False,
        source="东财",
    )
    store.upsert_calendar(c)

    cals = store.list_calendars(period="H1 2026")
    assert len(cals) == 1
    assert cals[0].disclosure_date == date(2026, 7, 20)


def test_list_calendars_filter(store: EarningsStore):
    """日历可按日期范围过滤。"""
    c1 = EarningsCalendar(
        code="603662", name="柯力", period="H1 2026",
        disclosure_date=date(2026, 7, 20), is_estimated=False, source="x",
    )
    c2 = EarningsCalendar(
        code="603986", name="兆易", period="H1 2026",
        disclosure_date=date(2026, 7, 25), is_estimated=False, source="x",
    )
    c3 = EarningsCalendar(
        code="002745", name="木林森", period="H1 2026",
        disclosure_date=date(2026, 8, 5), is_estimated=False, source="x",
    )
    for c in [c1, c2, c3]:
        store.upsert_calendar(c)

    # 未来 7 天 = 7/2 + 7 = 7/9
    cals = store.list_calendars(days_ahead=7)
    assert len(cals) == 0  # 7/20 都在 7/9 之后

    # 未来 30 天 = 7/2 + 30 = 8/1
    cals = store.list_calendars(days_ahead=30)
    assert len(cals) == 2  # 7/20, 7/25


def test_upsert_score(store: EarningsStore):
    s = EarningsScore(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        predicted_low=Decimal("188"),
        predicted_high=Decimal("217"),
        predicted_mid=Decimal("202.5"),
        actual_value=Decimal("900000000"),
        actual_growth=Decimal("225.0"),
        gap_to_mid=Decimal("22.5"),
        gap_to_high=Decimal("8.0"),
        verdict=EarningsVerdict.SUPER_BEAT,
        confidence=Decimal("0.9"),
    )
    store.upsert_score(s)

    scores = store.list_scores(period="H1 2026")
    assert len(scores) == 1
    assert scores[0].verdict == EarningsVerdict.SUPER_BEAT


def test_list_scores_filter_by_verdict(store: EarningsStore):
    """按 verdict 过滤。"""
    s1 = EarningsScore(
        code="603662", name="柯力", period="H1 2026",
        predicted_low=Decimal("188"), predicted_high=Decimal("217"),
        predicted_mid=Decimal("202.5"),
        actual_value=Decimal("900000000"), actual_growth=Decimal("225.0"),
        gap_to_mid=Decimal("22.5"), gap_to_high=Decimal("8.0"),
        verdict=EarningsVerdict.SUPER_BEAT, confidence=Decimal("0.9"),
    )
    s2 = EarningsScore(
        code="603986", name="兆易", period="H1 2026",
        predicted_low=Decimal("1070"), predicted_high=Decimal("1370"),
        predicted_mid=Decimal("1220"),
        actual_value=Decimal("2.5e9"), actual_growth=Decimal("1200"),
        gap_to_mid=Decimal("-20"), gap_to_high=Decimal("-170"),
        verdict=EarningsVerdict.MEET, confidence=Decimal("0.7"),
    )
    store.upsert_score(s1)
    store.upsert_score(s2)

    beat = store.list_scores(verdict=EarningsVerdict.SUPER_BEAT)
    assert len(beat) == 1
    assert beat[0].code == "603662"

    meet = store.list_scores(verdict=EarningsVerdict.MEET)
    assert len(meet) == 1
    assert meet[0].code == "603986"


def test_decimal_precision_preserved(store: EarningsStore):
    """Decimal 精度不应丢失（TEXT 存储）。"""
    precise = Decimal("123456789.123456789")
    a = EarningsActual(
        code="603662", name="柯力", period="H1 2026",
        actual_value=precise,
        growth_pct=Decimal("200.123"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    store.upsert_actual(a)

    got = store.get_actual("603662", "H1 2026")
    assert got is not None
    assert got.actual_value == precise
    assert got.growth_pct == Decimal("200.123")
