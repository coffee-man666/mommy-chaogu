"""IntradayService 离线单测（阶段六任务 3）：开盘半小时 / VWAP（典型价近似）/ 尾盘段。

Fake 分钟源构造两个交易日的 5m K（aware UTC，北京墙时间 09:30-15:00），
手工计算期望值核对三段口径——与服务的实现公式独立写出。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    MarketType,
    Money,
    Quote,
    QuoteType,
)
from mommy_chaogu.services.intraday_service import IntradayService

CODE = "600519"

# 北京墙时间 → aware UTC（生产链路 K 线时间戳是 aware UTC）
_UTC_OFFSET = timedelta(hours=8)


def _bj_utc(day: str, hh: int, mm: int) -> datetime:
    """北京墙时间 → 对应的 aware UTC datetime（生产链路 K 线时间戳口径）。"""
    d = datetime.strptime(day, "%Y-%m-%d")
    return d.replace(hour=hh, minute=mm).replace(tzinfo=UTC) - _UTC_OFFSET


def _m5(day: str, hh: int, mm: int, high: str, low: str, close: str, vol: int) -> Bar:
    return Bar(
        code=CODE,
        name="测试股",
        interval=BarInterval.M5,
        adjustment=AdjustmentType.NONE,
        timestamp=_bj_utc(day, hh, mm),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=vol,
        turnover=Money(Decimal("0")),
    )


class FakeAdapter:
    """零网络：预设 5m K 与可选实时报价。"""

    name = "fake"

    def __init__(self, bars: list[Bar], quote: Quote | None = None) -> None:
        self._bars = bars
        self._quote = quote

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        return list(self._bars)

    def get_quote(self, code: str) -> Quote | None:
        return self._quote


def _make_quote(prev_close: str) -> Quote:
    return Quote(
        code=CODE,
        name="测试股",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("105"),
        open=Decimal("100"),
        high=Decimal("106"),
        low=Decimal("99"),
        prev_close=Decimal(prev_close),
        change=Decimal("5"),
        change_pct=Decimal("5"),
        volume=700,
        turnover=Money(Decimal("73500")),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=_bj_utc("2026-09-30", 14, 35),
    )


def _two_day_bars() -> list[Bar]:
    """前一日（收盘 100）+ 目标日 8 根 5m（数值见测试内手工推导）。"""
    prev_day = [_m5("2026-09-29", 14, 55, "101", "99", "100", 10)]
    target = [
        # 开盘半小时（09:30-09:55，6 根，量 300）
        _m5("2026-09-30", 9, 30, "102", "100", "101", 100),
        _m5("2026-09-30", 9, 35, "103", "101", "102", 100),
        _m5("2026-09-30", 9, 40, "103", "101", "102", 50),
        _m5("2026-09-30", 9, 45, "104", "102", "103", 50),
        _m5("2026-09-30", 9, 50, "104", "102", "103", 50),
        _m5("2026-09-30", 9, 55, "105", "103", "104", 50),
        # 尾盘段（14:30-14:35，2 根，量 400）
        _m5("2026-09-30", 14, 30, "105", "103", "104", 200),
        _m5("2026-09-30", 14, 35, "106", "104", "105", 200),
    ]
    return prev_day + target


def test_full_day_metrics_hand_computed() -> None:
    """三段口径对手工期望值（公式独立推导，见各断言旁注释）。"""
    service = IntradayService(FakeAdapter(_two_day_bars()))
    result = service.profile(CODE)

    assert result["trade_date"] == "2026-09-30"
    assert result["prev_close"] == Decimal("100")  # 前一日最后一根收盘
    assert result["prev_close_source"] == "prev_day_last_bar"

    oh = result["open_half_hour"]
    assert oh["bars_in_window"] == 6
    assert oh["price_at_1000"] == Decimal("104")  # 09:55 根的收盘 = 10:00 时点价
    assert oh["change_pct_vs_prev_close"] == Decimal("4")  # 104/100-1 = +4%
    assert oh["volume"] == 400  # 100+100+50+50+50+50
    assert oh["volume_share_of_day"] == Decimal(400) / Decimal(800)

    # VWAP = Σ((H+L+C)/3 × V) / ΣV = 82700 / 800（各根典型价均为整数）
    vwap = result["vwap"]
    assert vwap["value"] == Decimal("82700") / Decimal("800")
    assert vwap["last_close"] == Decimal("105")
    assert vwap["position_pct"] == (Decimal("105") / (Decimal("82700") / Decimal("800")) - 1) * 100
    assert "典型价近似" in vwap["note"]

    tail = result["tail"]
    assert tail["bars_in_window"] == 2
    # 段涨跌基准 = 14:30 前最后一根收盘（09:55 根 close=104）
    assert tail["change_pct"] == (Decimal("105") / Decimal("104") - 1) * 100
    assert tail["volume"] == 400
    assert tail["volume_share_of_day"] == Decimal(400) / Decimal(800)

    assert any("典型价近似" in n for n in result["notes"])


def test_prev_close_from_quote_wins() -> None:
    """实时报价的昨收优先于前一日 K 线回退。"""
    service = IntradayService(FakeAdapter(_two_day_bars(), quote=_make_quote("200")))
    result = service.profile(CODE)
    assert result["prev_close"] == Decimal("200")
    assert result["prev_close_source"] == "quote"
    assert (
        result["open_half_hour"]["change_pct_vs_prev_close"]
        == (  # 104/200-1
            Decimal("104") / Decimal("200") - 1
        )
        * 100
    )


def test_prev_close_override_beats_everything() -> None:
    """调用方显式覆盖值最高优先。"""
    service = IntradayService(FakeAdapter(_two_day_bars(), quote=_make_quote("200")))
    result = service.profile(CODE, prev_close=Decimal("50"))
    assert result["prev_close"] == Decimal("50")
    assert result["prev_close_source"] == "override"


def test_partial_day_no_tail_yet() -> None:
    """盘中部分日：尾盘段尚未到来 → 明示而非编数。"""
    bars = [
        _m5("2026-09-29", 14, 55, "101", "99", "100", 10),
        _m5("2026-09-30", 9, 30, "102", "100", "101", 100),
        _m5("2026-09-30", 9, 35, "103", "101", "102", 100),
    ]
    result = IntradayService(FakeAdapter(bars)).profile(CODE)
    assert "盘中部分" in result["session"]
    assert result["tail"]["bars_in_window"] == 0
    assert result["tail"]["change_pct"] is None
    assert result["tail"]["volume_share_of_day"] is None
    # VWAP 仍按已有两根计算：(101+102)/2 加权
    assert result["vwap"]["value"] == (Decimal("101") + Decimal("102")) / Decimal("2")


def test_no_bars_returns_error_not_fake_numbers() -> None:
    """无分钟数据 → error，不产出假指标。"""
    result = IntradayService(FakeAdapter([])).profile(CODE)
    assert "error" in result
    assert "vwap" not in result


def test_single_day_without_prev_close_context() -> None:
    """仅一个交易日且报价不可得 → 昨收标注不可得，开盘半小时涨跌幅为空。"""
    bars = [_m5("2026-09-30", 9, 30, "102", "100", "101", 100)]
    result = IntradayService(FakeAdapter(bars)).profile(CODE)
    assert result["prev_close"] is None
    assert result["prev_close_source"] == "unavailable"
    assert result["open_half_hour"]["change_pct_vs_prev_close"] is None
    assert any("昨收不可得" in n for n in result["notes"])


def test_as_of_is_last_bar_utc_isoformat() -> None:
    result = IntradayService(FakeAdapter(_two_day_bars())).profile(CODE)
    assert result["as_of"] == _bj_utc("2026-09-30", 14, 35).isoformat()


def test_json_serializable_via_floatify() -> None:
    """工具层 _floatify 能把整个 profile 转 JSON-safe（Decimal→float）。"""
    import json

    from mommy_chaogu.agent.tools.base import _floatify

    result: dict[str, Any] = IntradayService(FakeAdapter(_two_day_bars())).profile(CODE)
    json.dumps(_floatify(result))  # 不抛即通过
