"""超短期（日内）层服务：今天资金怎么交易这只股票。

三段口径（docs/plans/trading-method-landing.md 阶段六任务 3，公式与
量级均经腾讯 m5 真实数据实算验证）：

- **开盘半小时**：10:00 价相对昨收的涨跌幅 + 该半小时成交量占全日比例
  （回答「开盘强弱」）；
- **VWAP 相对位置**：Σ(典型价 × 成交量) / Σ(成交量)，典型价 = (H+L+C)/3，
  最新价相对 VWAP 的位置（回答「日内成本线上方还是下方」）。分钟源无每根
  成交额（腾讯 mkline），**只能以成交量加权的典型价近似精确 VWAP**——
  输出必须标注「典型价近似」；
- **尾盘段行为**：14:30-15:00 段涨跌 + 量占比（回答「尾盘抢筹/砸盘/观望」）。

诚实边界（计划阶段六「边界」与 §4.4）：
- 日内指标只承诺「当日 + 近期」——分钟存档深度有限（腾讯 m1 仅 3-4 交易
  日、m5 存档约 2026-07 起；efinance 分钟深度未知），不做长期日内统计；
- 盘口无历史留存，不能回看；
- 输出是「当期状态观察」，不构成交易建议。

数据入口：5 分钟 K（BarInterval.M5，A 股一天 48 根）。时间窗按北京交易
时段界定；K 线时间戳统一 aware（周期初口径，见 tencent_adapter._mkline_ts）。
"""

from __future__ import annotations

import logging
from datetime import time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import Bar, BarInterval

_log = logging.getLogger(__name__)

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")

# 5 分钟 K：A 股一天 48 根（09:30-11:30 + 13:00-15:00）
BARS_PER_DAY = 48

# 回看深度：当前交易日 + 前一交易日（昨收回退来源）+ 余量
LOOKBACK_DAYS = 3

# 时间窗（北京墙时间，分钟 K 周期初口径）
_OPEN_HALF_END = time(10, 0)  # 开盘半小时：09:30 ≤ bar start < 10:00
_TAIL_START = time(14, 30)  # 尾盘段：14:30 ≤ bar start < 15:00

VWAP_NOTE = "VWAP 为典型价近似：分钟源无每根成交额，以典型价 (H+L+C)/3 按成交量加权"

_COVERAGE_NOTE = "日内指标仅覆盖当日与近期（分钟存档深度有限），不做长期日内统计"


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    """(num/den - 1) × 100；分母为零返回 Decimal(0)。"""
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator - Decimal("1")) * Decimal("100")


class IntradayService:
    """5 分钟 K → 开盘半小时强弱 / VWAP（典型价近似）/ 尾盘段行为。

    用法（agent 工具层接线见 agent/tools/bars.py）::

        service = IntradayService(adapter)
        result = service.profile("600519")  # dict，JSON 可序列化
    """

    def __init__(self, adapter: MarketDataAdapter) -> None:
        self._adapter = adapter

    # ---------- 数据入口 ----------

    def _load_day_bars(self, code: str) -> dict[str, list[Bar]]:
        """拉 5 分钟 K → {北京交易日: 当日 bars（按时间升序）}。"""
        try:
            bars = self._adapter.get_bars(
                code, interval=BarInterval.M5, limit=BARS_PER_DAY * LOOKBACK_DAYS
            )
        except Exception as e:
            _log.warning("intraday fetch m5 bars(%s) failed: %s", code, e)
            return {}
        by_day: dict[str, list[Bar]] = {}
        for bar in bars:
            ts = bar.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_TZ_BEIJING)
            day = ts.astimezone(_TZ_BEIJING).strftime("%Y-%m-%d")
            by_day.setdefault(day, []).append(bar)
        for day_bars in by_day.values():
            day_bars.sort(key=lambda b: b.timestamp)
        return by_day

    def _prev_close(self, code: str, prev_day_bars: list[Bar] | None) -> tuple[Decimal | None, str]:
        """昨收：优先实时报价的 prev_close，回退前一交易日最后一根收盘。

        返回 (昨收, 来源标注)。
        """
        try:
            quote = self._adapter.get_quote(code)
        except Exception as e:
            _log.warning("intraday fetch quote(%s) failed: %s", code, e)
            quote = None
        if quote is not None and quote.prev_close > 0:
            return quote.prev_close, "quote"
        if prev_day_bars:
            last_close = prev_day_bars[-1].close
            if last_close > 0:
                return last_close, "prev_day_last_bar"
        return None, "unavailable"

    # ---------- 三段口径 ----------

    @staticmethod
    def _open_half_hour(day_bars: list[Bar], prev_close: Decimal | None) -> dict[str, Any]:
        window = [b for b in day_bars if _bar_time(b) < _OPEN_HALF_END]
        day_volume = sum((b.volume for b in day_bars), 0)
        window_volume = sum((b.volume for b in window), 0)
        price_at_end = window[-1].close if window else None
        return {
            "window": "09:30-10:00",
            "bars_in_window": len(window),
            "price_at_1000": price_at_end,
            "change_pct_vs_prev_close": (
                _pct(price_at_end, prev_close)
                if price_at_end is not None and prev_close is not None and prev_close > 0
                else None
            ),
            "volume": window_volume,
            "volume_share_of_day": (
                Decimal(window_volume) / Decimal(day_volume) if day_volume > 0 else None
            ),
        }

    @staticmethod
    def _vwap_section(day_bars: list[Bar]) -> dict[str, Any]:
        vol_sum = sum((Decimal(b.volume) for b in day_bars), Decimal("0"))
        if vol_sum > 0:
            weighted = sum(
                (((b.high + b.low + b.close) / Decimal("3")) * Decimal(b.volume) for b in day_bars),
                Decimal("0"),
            )
            vwap = weighted / vol_sum
            last = day_bars[-1].close
            return {
                "value": vwap,
                "last_close": last,
                "position_pct": _pct(last, vwap),
                "note": VWAP_NOTE,
            }
        return {"value": None, "last_close": None, "position_pct": None, "note": VWAP_NOTE}

    @staticmethod
    def _tail_section(day_bars: list[Bar]) -> dict[str, Any]:
        window = [b for b in day_bars if _bar_time(b) >= _TAIL_START]
        day_volume = sum((b.volume for b in day_bars), 0)
        window_volume = sum((b.volume for b in window), 0)
        if not window:
            return {
                "window": "14:30-15:00",
                "bars_in_window": 0,
                "change_pct": None,
                "volume": 0,
                "volume_share_of_day": None,
                "note": "尚未到尾盘时段（或当日数据截止于 14:30 前）",
            }
        # 段涨跌基准：14:30 前最后一根的收盘（即 14:30 时点价）；当日数据
        # 本就从 14:30 后开始时退化为窗口首根开盘。
        before = [b for b in day_bars if _bar_time(b) < _TAIL_START]
        reference = before[-1].close if before else window[0].open
        last_close = window[-1].close
        return {
            "window": "14:30-15:00",
            "bars_in_window": len(window),
            "change_pct": _pct(last_close, reference) if reference > 0 else None,
            "volume": window_volume,
            "volume_share_of_day": (
                Decimal(window_volume) / Decimal(day_volume) if day_volume > 0 else None
            ),
        }

    # ---------- 主入口 ----------

    def profile(self, code: str, prev_close: Decimal | None = None) -> dict[str, Any]:
        """生成一段「今天资金怎么交易它」的日内画像。

        Args:
            code: A 股 6 位代码。
            prev_close: 昨收覆盖值（调用方已知时直接传入）；缺省依次取
                实时报价 prev_close → 前一交易日最后一根 5m 收盘。

        Returns:
            dict（JSON 可序列化）。无分钟数据时返回 ``{"error": ...}``，
            不产出假指标。
        """
        by_day = self._load_day_bars(code)
        if not by_day:
            return {
                "error": f"{code} 5 分钟 K 线不可得（上游无数据或网络不可达），无法给出日内画像",
                "code": code,
            }

        days = sorted(by_day)
        trade_date = days[-1]
        day_bars = by_day[trade_date]
        prev_day_bars = by_day[days[-2]] if len(days) >= 2 else None

        prev_close_used: Decimal | None
        prev_close_source: str
        if prev_close is not None and prev_close > 0:
            prev_close_used, prev_close_source = prev_close, "override"
        else:
            prev_close_used, prev_close_source = self._prev_close(code, prev_day_bars)

        last_bar = day_bars[-1]
        name = next((b.name for b in day_bars if b.name), "")
        session_note = (
            "完整交易日（48 根）"
            if len(day_bars) >= BARS_PER_DAY
            else f"盘中部分（{len(day_bars)} 根，截至 {last_bar.timestamp.astimezone(_TZ_BEIJING):%H:%M}）"
        )

        result: dict[str, Any] = {
            "code": code,
            "name": name,
            "trade_date": trade_date,
            "as_of": last_bar.timestamp.isoformat(),
            "session": session_note,
            "interval": BarInterval.M5.value,
            "prev_close": prev_close_used,
            "prev_close_source": prev_close_source,
            "open_half_hour": self._open_half_hour(day_bars, prev_close_used),
            "vwap": self._vwap_section(day_bars),
            "tail": self._tail_section(day_bars),
            "notes": [
                VWAP_NOTE,
                _COVERAGE_NOTE,
                "当期状态观察，不构成交易建议",
            ],
        }
        if prev_close_used is None:
            result["notes"].append("昨收不可得：开盘半小时相对昨收的涨跌幅无法计算")
        return result


def _bar_time(bar: Bar) -> time:
    """bar 时间戳 → 北京墙时间 time（naive 视为北京墙时间）。"""
    ts = bar.timestamp
    if ts.tzinfo is None:
        return ts.time()
    return ts.astimezone(_TZ_BEIJING).time()
