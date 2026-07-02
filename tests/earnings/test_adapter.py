"""earnings 模块 — Adapter 单元测试。"""

from __future__ import annotations

from datetime import date

from mommy_chaogu.earnings.adapter import (
    EarningsAdapter,
    MockEarningsAdapter,
)


def test_mock_adapter_is_runtime_checkable():
    """Mock 应满足 EarningsAdapter Protocol。"""
    adapter = MockEarningsAdapter()
    assert isinstance(adapter, EarningsAdapter)


def test_mock_adapter_fetch_known_code():
    adapter = MockEarningsAdapter()
    actuals = adapter.fetch_actual("603662", "H1 2026")
    assert len(actuals) == 1
    assert actuals[0].code == "603662"
    assert actuals[0].growth_pct is not None


def test_mock_adapter_fetch_unknown_code():
    adapter = MockEarningsAdapter()
    actuals = adapter.fetch_actual("999999", "H1 2026")
    assert actuals == []


def test_mock_adapter_calendar_known():
    adapter = MockEarningsAdapter()
    cals = adapter.fetch_calendar("603662")
    assert len(cals) == 1
    assert cals[0].code == "603662"


def test_mock_adapter_calendar_unknown():
    adapter = MockEarningsAdapter()
    cals = adapter.fetch_calendar("999999")
    assert cals == []


def test_mock_adapter_returns_correct_period():
    adapter = MockEarningsAdapter()
    actuals = adapter.fetch_actual("603662", "Q3 2026")
    assert actuals[0].period == "Q3 2026"


def test_mock_adapter_since_filter():
    """since 参数应过滤旧数据（虽然 mock 都是未来日期，所以不应过滤）。"""
    adapter = MockEarningsAdapter()
    actuals = adapter.fetch_actual("603662", "H1 2026", since=date(2026, 7, 1))
    # mock 数据披露日是 7/20 > 7/1，所以应该返回
    assert len(actuals) == 1

    actuals_old = adapter.fetch_actual("603662", "H1 2026", since=date(2027, 1, 1))
    # mock 数据 7/20 < 2027/1/1，所以应该被过滤
    assert len(actuals_old) == 0
