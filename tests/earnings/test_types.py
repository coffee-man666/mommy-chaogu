"""earnings 模块 — 类型单元测试。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from mommy_chaogu.earnings.types import (
    VERDICT_LABEL,
    EarningsActual,
    EarningsCalendar,
    EarningsScore,
    EarningsSource,
    EarningsVerdict,
)


def test_earnings_actual_creation():
    a = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("850000000"),
        growth_pct=Decimal("200.0"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
        note="测试",
        fetched_at=datetime(2026, 7, 21, 9, 0, 0),
    )
    assert a.code == "603662"
    assert a.actual_value == Decimal("850000000")
    assert a.growth_pct == Decimal("200.0")
    assert a.source == EarningsSource.FORECAST


def test_earnings_actual_immutable():
    a = EarningsActual(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        actual_value=Decimal("100"),
        growth_pct=Decimal("100"),
        disclosure_date=date(2026, 7, 20),
        source=EarningsSource.FORECAST,
    )
    try:
        a.code = "999999"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass  # expected: FrozenInstanceError


def test_earnings_calendar_creation():
    c = EarningsCalendar(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        disclosure_date=date(2026, 7, 20),
        is_estimated=False,
        source="东财",
    )
    assert c.is_estimated is False
    assert c.source == "东财"


def test_earnings_score_properties():
    s = EarningsScore(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        predicted_low=Decimal("188"),
        predicted_high=Decimal("217"),
        predicted_mid=Decimal("202.5"),
        actual_value=Decimal("850000000"),
        actual_growth=Decimal("225.0"),
        gap_to_mid=Decimal("22.5"),
        gap_to_high=Decimal("8.0"),
        verdict=EarningsVerdict.SUPER_BEAT,
        confidence=Decimal("0.9"),
    )
    assert s.is_above_predicted_high is True
    assert s.is_below_predicted_low is False


def test_verdict_label_coverage():
    """所有 verdict 都应有 label。"""
    for v in EarningsVerdict:
        assert v in VERDICT_LABEL
        # 接受任何 emoji（绿/黄/橙/红/白）
        for emoji in ("🟢", "🟡", "🟠", "🔴", "⚪"):
            if emoji in VERDICT_LABEL[v]:
                break
        else:
            raise AssertionError(f"verdict {v} label '{VERDICT_LABEL[v]}' 没有可识别的 emoji")


def test_earnings_verdict_string_values():
    """Enum 值用 snake_case 字符串（数据库存储用）。"""
    assert EarningsVerdict.SUPER_BEAT.value == "super_beat"
    assert EarningsVerdict.DEEP_MISS.value == "deep_miss"
