"""时间戳时区语义测试：两个 adapter 对外时间戳统一 aware UTC。

- 北京墙时间语义的字符串（efinance 的 naive 时间列、tencent 的 YYYYMMDDHHMMSS）
  必须换算成 aware UTC 的绝对时刻（北京时间 - 8h）。
- 解析失败的兜底必须是 datetime.now(UTC)，不得产出 naive。
- tencent 盘口时间字段与行情一致（索引 30），不得误读 29。

全部用 mock 响应，不依赖外部网络。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from mommy_chaogu.market_data import BarInterval, EfinanceAdapter, TencentAdapter
from mommy_chaogu.market_data.tencent_adapter import _ts_from_str

# 2026-06-26 16:14:08 北京时间 → 2026-06-26T08:14:08Z
_EXPECTED_UTC = datetime(2026, 6, 26, 8, 14, 8, tzinfo=UTC)

_EF_MODULE = "mommy_chaogu.market_data.efinance_adapter.ef.stock"


def _assert_aware_utc(ts: datetime, expected: datetime) -> None:
    assert ts.tzinfo is not None
    assert ts == expected


# ---------- efinance：行情（_row_to_quote） ----------


def test_efinance_quote_timestamp_is_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """全市场快照路径：更新时间（北京墙时间）→ aware UTC。"""
    snapshot = pd.DataFrame(
        [
            {
                "股票代码": "600519",
                "股票名称": "贵州茅台",
                "最新价": "1680.00",
                "更新时间": "2026-06-26 16:14:08",
            }
        ]
    )
    monkeypatch.setattr(f"{_EF_MODULE}.get_realtime_quotes", MagicMock(return_value=snapshot))

    quotes = EfinanceAdapter().get_quotes(["600519"])
    assert len(quotes) == 1
    _assert_aware_utc(quotes[0].timestamp, _EXPECTED_UTC)


def test_efinance_quote_bad_timestamp_falls_back_to_aware_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """更新时间缺失/NaT → 兜底 datetime.now(UTC)（aware，不抛异常）。"""
    snapshot = pd.DataFrame(
        [{"股票代码": "600519", "股票名称": "贵州茅台", "最新价": "1680.00", "更新时间": ""}]
    )
    monkeypatch.setattr(f"{_EF_MODULE}.get_realtime_quotes", MagicMock(return_value=snapshot))

    quotes = EfinanceAdapter().get_quotes(["600519"])
    assert len(quotes) == 1
    ts = quotes[0].timestamp
    assert ts.tzinfo is not None
    assert ts.tzinfo.utcoffset(ts) == UTC.utcoffset(None)
    assert abs((ts - datetime.now(UTC)).total_seconds()) < 60


# ---------- efinance：盘口（get_order_book） ----------


def test_efinance_order_book_timestamp_is_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    ser = _fake_snapshot_series()
    monkeypatch.setattr(f"{_EF_MODULE}.get_quote_snapshot", MagicMock(return_value=ser))

    ob = EfinanceAdapter().get_order_book("600519")
    assert ob is not None
    assert len(ob.bids) == 1
    assert len(ob.asks) == 1
    _assert_aware_utc(ob.timestamp, _EXPECTED_UTC)


def _fake_snapshot_series() -> pd.Series:
    data: dict[str, Any] = {
        "代码": "600519",
        "名称": "贵州茅台",
        "时间": "2026-06-26 16:14:08",
        "最新价": "1680.00",
        "成交量": "5000",
    }
    for i in range(1, 6):
        data[f"买{i}价"] = "1679.00" if i == 1 else ""
        data[f"买{i}数量"] = "2" if i == 1 else ""
        data[f"卖{i}价"] = "1681.00" if i == 1 else ""
        data[f"卖{i}数量"] = "3" if i == 1 else ""
    return pd.Series(data)


# ---------- efinance：K 线（get_bars） ----------


def test_efinance_bars_timestamp_is_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """日线日期 2026-06-26（北京）→ 2026-06-25T16:00:00Z。"""
    df = pd.DataFrame(
        [
            {
                "日期": "2026-06-26",
                "股票名称": "贵州茅台",
                "开盘": "1670.00",
                "最高": "1690.00",
                "最低": "1665.00",
                "收盘": "1680.00",
                "成交量": "50000",
                "成交额": "8400000000",
                "涨跌幅": "0.60",
                "换手率": "0.40",
                "振幅": "1.50",
            }
        ]
    )
    monkeypatch.setattr(f"{_EF_MODULE}.get_quote_history", MagicMock(return_value=df))

    bars = EfinanceAdapter().get_bars("600519", interval=BarInterval.D1, limit=10)
    assert len(bars) == 1
    _assert_aware_utc(bars[0].timestamp, datetime(2026, 6, 25, 16, 0, 0, tzinfo=UTC))


# ---------- efinance：Tick（get_ticks） ----------


def test_efinance_ticks_timestamp_is_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame(
        [
            {
                "时间": "2026-06-26 09:30:05",
                "股票名称": "贵州茅台",
                "成交价": "1670.00",
                "成交量": "100",
                "昨收": "1668.00",
                "单数": "20",
            }
        ]
    )
    monkeypatch.setattr(f"{_EF_MODULE}.get_deal_detail", MagicMock(return_value=df))

    ticks = EfinanceAdapter().get_ticks("600519", limit=10)
    assert len(ticks) == 1
    _assert_aware_utc(ticks[0].timestamp, datetime(2026, 6, 26, 1, 30, 5, tzinfo=UTC))


# ---------- efinance：资金流 ----------


def _fake_bill_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "时间": "2026-06-26 16:14:08",
                "股票名称": "贵州茅台",
                "主力净流入": "-1234567.89",
                "小单净流入": "100000.00",
                "中单净流入": "200000.00",
                "大单净流入": "-300000.00",
                "超大单净流入": "-934567.89",
                "主力净流入占比": "-2.50",
            }
        ]
    )


def test_efinance_today_money_flow_timestamp_is_aware_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(f"{_EF_MODULE}.get_today_bill", MagicMock(return_value=_fake_bill_df()))

    flows = EfinanceAdapter().get_today_money_flow("600519")
    assert len(flows) == 1
    _assert_aware_utc(flows[0].timestamp, _EXPECTED_UTC)


def test_efinance_history_money_flow_aware_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """cutoff 与 aware 时间戳比较不得抛 TypeError，且正常过滤。"""
    monkeypatch.setattr(f"{_EF_MODULE}.get_history_bill", MagicMock(return_value=_fake_bill_df()))

    flows = EfinanceAdapter().get_history_money_flow("600519", days=365)
    assert len(flows) == 1
    _assert_aware_utc(flows[0].timestamp, _EXPECTED_UTC)


# ---------- tencent：_ts_from_str 单元 ----------


def test_tencent_ts_from_str_beijing_to_utc() -> None:
    _assert_aware_utc(_ts_from_str("20260626161408"), _EXPECTED_UTC)  # type: ignore[arg-type]


def test_tencent_ts_from_str_invalid_returns_none() -> None:
    assert _ts_from_str("") is None
    assert _ts_from_str("2026062616") is None  # 长度不足
    assert _ts_from_str("20261332161408") is None  # 非法月份


# ---------- tencent：行情 ----------

# 腾讯接口真实 88 字段响应（贵州茅台），fields[30] = "20260626161408"
_MOCK_TENCENT_RAW = (
    'v_sh600519="1~XD贵州茅~600519~1168.63~1184.08~1199.00~50066~20841~29226~'
    "1168.63~2~1168.60~2~1168.52~1~1168.51~1~1168.50~4~1168.78~1~1168.80~7~"
    "1168.81~5~1168.82~142~1168.98~1~~20260626161408~-15.45~-1.30~1199.00~1168.10~"
    "1168.63/50066/5922014054~50066~592201~0.40~17.66~~1199.00~1168.10~2.61~"
    "14608.83~14608.83~6.27~1302.49~1065.67~0.94~-146~1182.83~13.41~17.75~~~"
    "0.34~592201.4054~0.0000~0~ ~GP-A~-13.38~-1.55~4.45~30.53~26.78~1539.98~"
    '1168.10~-6.58~-6.36~-15.80~1250081601~1250081601~-87.95~-16.61~12500...";'
)


def _patch_session(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """把 TencentAdapter._session 替换成返回指定文本的 mock。"""
    resp = MagicMock()
    resp.status_code = 200
    resp.encoding = "gbk"
    resp.text = text
    resp.raise_for_status = MagicMock()
    sess = MagicMock()
    sess.get.return_value = resp

    def patched_init(self: TencentAdapter, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._session = sess

    monkeypatch.setattr(TencentAdapter, "__init__", patched_init)


def test_tencent_quote_timestamp_is_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_session(monkeypatch, _MOCK_TENCENT_RAW)
    q = TencentAdapter().get_quote("600519")
    assert q is not None
    _assert_aware_utc(q.timestamp, _EXPECTED_UTC)


# ---------- tencent：盘口（off-by-one 回归） ----------


def test_tencent_order_book_timestamp_is_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """盘口时间字段必须读索引 30（与行情一致），不得误读 29 后落到 naive now。"""
    _patch_session(monkeypatch, _MOCK_TENCENT_RAW)
    ob = TencentAdapter().get_order_book("600519")
    assert ob is not None
    assert len(ob.bids) == 5
    assert len(ob.asks) == 5
    _assert_aware_utc(ob.timestamp, _EXPECTED_UTC)
