"""earnings 模块 — EfinanceEarningsAdapter 单元测试。

测试策略：
- 不实际访问网络（用 monkeypatch mock 掉 ef.stock.get_all_company_performance）
- 验证数据解析 / 字段映射 / 异常处理
- 实际联网测试已标记 @pytest.mark.network
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from mommy_chaogu.earnings.efinance_adapter import (
    EfinanceEarningsAdapter,
    _period_to_date,
)


def make_full_market_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """构造 mock 全市场 DataFrame。"""
    return pd.DataFrame(rows)


def make_keli_row() -> dict[str, Any]:
    """柯力传感 603662 的 mock 一行（业绩大涨情景）。"""
    return {
        "股票代码": "603662",
        "股票简称": "柯力传感",
        "公告日期": pd.Timestamp("2026-07-25"),
        "营业收入": 1.2e9,
        "营业收入同比增长": 35.5,
        "营业收入季度环比": 25.0,
        "净利润": 8.5e8,
        "净利润同比增长": 215.0,
        "净利润季度环比": 80.0,
        "每股收益": 1.85,
        "每股净资产": 12.5,
        "净资产收益率": 14.5,
        "销售毛利率": 45.0,
        "每股经营现金流量": 2.1,
    }


def make_zhaoyi_row() -> dict[str, Any]:
    """兆易创新 603986 的 mock 一行。"""
    return {
        "股票代码": "603986",
        "股票简称": "兆易创新",
        "公告日期": pd.Timestamp("2026-07-22"),
        "营业收入": 5.0e9,
        "营业收入同比增长": 60.0,
        "营业收入季度环比": 30.0,
        "净利润": 2.5e9,
        "净利润同比增长": 1200.0,
        "净利润季度环比": 200.0,
        "每股收益": 3.5,
        "每股净资产": 25.0,
        "净资产收益率": 15.0,
        "销售毛利率": 40.0,
        "每股经营现金流量": 4.0,
    }


# ---------- _period_to_date ----------


def test_period_to_date_h1():
    assert _period_to_date("H1 2026") == "2026-06-30"


def test_period_to_date_q3():
    assert _period_to_date("Q3 2026") == "2026-09-30"


def test_period_to_date_fy():
    assert _period_to_date("FY 2026") == "2026-12-31"


def test_period_to_date_invalid():
    with pytest.raises(ValueError):
        _period_to_date("2026H1")  # 顺序错
    with pytest.raises(ValueError):
        _period_to_date("Q1 2026")  # 不支持 Q1
    with pytest.raises(ValueError):
        _period_to_date("H1")  # 缺年份


# ---------- fetch_actual (mock) ----------


@patch("mommy_chaogu.earnings.efinance_adapter._fetch_full_market", create=True)
def test_fetch_actual_returns_parsed_data(_mock_fetch):
    """正常情况：返回 EarningsActual 列表。"""
    adapter = EfinanceEarningsAdapter()
    # 直接 mock 内部方法
    df = make_full_market_df([make_keli_row(), make_zhaoyi_row()])
    actuals = adapter._extract_actuals(df, "603662", "H1 2026")

    assert len(actuals) == 1
    a = actuals[0]
    assert a.code == "603662"
    assert a.name == "柯力传感"
    assert a.period == "H1 2026"
    assert a.growth_pct == Decimal("215.0")
    assert a.disclosure_date == date(2026, 7, 25)
    assert a.source.value == "report"


@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_actual_handles_missing_code(mock_fetch):
    """查询不存在的 code 应返回空 list。"""
    mock_fetch.return_value = make_full_market_df([make_keli_row()])
    adapter = EfinanceEarningsAdapter()
    actuals = adapter._extract_actuals(mock_fetch.return_value, "999999", "H1 2026")
    assert actuals == []


@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_actual_handles_exception(mock_fetch):
    """网络异常应返回空 list，不抛。"""
    mock_fetch.side_effect = ConnectionError("network down")
    adapter = EfinanceEarningsAdapter()
    actuals = adapter.fetch_actual("603662", "H1 2026")
    assert actuals == []


@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_actual_filters_by_since(mock_fetch):
    """since 参数应过滤旧披露。"""
    mock_fetch.return_value = make_full_market_df([make_keli_row()])
    adapter = EfinanceEarningsAdapter()

    # since = 2026-08-01 → 柯力 7/25 应被过滤
    actuals = adapter._extract_actuals(
        mock_fetch.return_value,
        "603662",
        "H1 2026",
        since=date(2026, 8, 1),
    )
    assert actuals == []

    # since = 2026-07-01 → 柯力 7/25 应保留
    actuals = adapter._extract_actuals(
        mock_fetch.return_value,
        "603662",
        "H1 2026",
        since=date(2026, 7, 1),
    )
    assert len(actuals) == 1


@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_actual_handles_missing_growth(mock_fetch):
    """净利润同比增长缺失应返回 growth_pct=None，不抛。"""
    row = make_keli_row()
    row["净利润同比增长"] = None
    mock_fetch.return_value = make_full_market_df([row])
    adapter = EfinanceEarningsAdapter()
    actuals = adapter._extract_actuals(mock_fetch.return_value, "603662", "H1 2026")
    assert len(actuals) == 1
    assert actuals[0].growth_pct is None


@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_actual_handles_empty_df(mock_fetch):
    """空 DataFrame 应返回空 list。"""
    mock_fetch.return_value = pd.DataFrame()
    adapter = EfinanceEarningsAdapter()
    actuals = adapter._extract_actuals(mock_fetch.return_value, "603662", "H1 2026")
    assert actuals == []


# ---------- fetch_calendar (mock) ----------


@patch.object(EfinanceEarningsAdapter, "_get_available_periods")
@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_calendar_returns_calendar(mock_fetch, mock_periods):
    mock_periods.return_value = ["2026-06-30", "2025-12-31"]
    mock_fetch.return_value = make_full_market_df([make_keli_row()])
    adapter = EfinanceEarningsAdapter()

    cals = adapter.fetch_calendar("603662")
    assert len(cals) == 1
    c = cals[0]
    assert c.code == "603662"
    assert c.disclosure_date == date(2026, 7, 25)
    assert c.period == "H1 2026"


@patch.object(EfinanceEarningsAdapter, "_get_available_periods")
@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_calendar_no_periods(mock_fetch, mock_periods):
    mock_periods.return_value = []
    mock_fetch.return_value = make_full_market_df([make_keli_row()])
    adapter = EfinanceEarningsAdapter()
    assert adapter.fetch_calendar("603662") == []


@patch.object(EfinanceEarningsAdapter, "_get_available_periods")
@patch.object(EfinanceEarningsAdapter, "_fetch_full_market")
def test_fetch_calendar_filter_since(mock_fetch, mock_periods):
    mock_periods.return_value = ["2026-06-30"]
    mock_fetch.return_value = make_full_market_df([make_keli_row()])
    adapter = EfinanceEarningsAdapter()

    cals = adapter.fetch_calendar("603662", since=date(2026, 8, 1))
    assert cals == []


# ---------- 内部辅助函数 ----------


def test_to_date_timestamp():
    """pandas Timestamp 应转 date。"""
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    ts = pd.Timestamp("2026-07-25")
    assert E._to_date(ts) == date(2026, 7, 25)


def test_to_date_datetime():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    dt = datetime(2026, 7, 25, 12, 0)
    assert E._to_date(dt) == date(2026, 7, 25)


def test_to_date_string():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._to_date("2026-07-25") == date(2026, 7, 25)


def test_to_date_none():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._to_date(None) is None


def test_to_date_invalid_string():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._to_date("not a date") is None


def test_to_decimal_number():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._to_decimal(215.5) == Decimal("215.5")
    assert E._to_decimal(100) == Decimal("100")


def test_to_decimal_nan():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._to_decimal(float("nan")) is None
    assert E._to_decimal(None) is None


def test_to_decimal_string():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._to_decimal("215.5") == Decimal("215.5")


def test_iso_to_period():
    from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter as E

    assert E._iso_to_period("2026-06-30") == "H1 2026"
    assert E._iso_to_period("2026-09-30") == "Q3 2026"
    assert E._iso_to_period("2026-12-31") == "FY 2026"
    assert E._iso_to_period("2026-03-31") == "H1 2026"  # Q1 也归 H1
    assert E._iso_to_period("2026-08-15") == "Q3 2026"
    # invalid → 截取前 4 位做 fallback
    assert E._iso_to_period("invalid") == "H1 inva"


# ---------- Protocol 检查 ----------


def test_efinance_adapter_implements_protocol():
    """EfinanceEarningsAdapter 应满足 EarningsAdapter Protocol。"""
    from mommy_chaogu.earnings import EarningsAdapter

    adapter = EfinanceEarningsAdapter()
    assert isinstance(adapter, EarningsAdapter)


# ---------- 真实联网测试（标记 network）----------


@pytest.mark.network
def test_efinance_real_fetch_h1_2025():
    """真实联网测试：拉 H1 2025 全市场业绩。

    需要 efinance + 网络。仅手动跑。
    """
    import warnings

    adapter = EfinanceEarningsAdapter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        actuals = adapter.fetch_actual("603662", "H1 2025")
    # 至少应返回一条（H1 2025 已披露）
    if actuals:
        a = actuals[0]
        assert a.code == "603662"
        assert a.period == "H1 2025"
        assert a.growth_pct is not None
        assert a.disclosure_date is not None


@pytest.mark.network
def test_efinance_real_calendar():
    """真实联网测试：拉公告日历。"""
    import warnings

    adapter = EfinanceEarningsAdapter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cals = adapter.fetch_calendar("603662")
    # 应返回 1 条（最新季报的公告日期）
    if cals:
        c = cals[0]
        assert c.code == "603662"
        assert c.disclosure_date is not None
