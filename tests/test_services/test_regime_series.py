"""市场环境路径式状态服务单测（全离线：fake adapter，合成 K 线）。

覆盖 services/regime_series.py：
- 逐日三态序列生成（复用 backtest/regime_analysis._regime_at 的判定）
- 状态持续天数 / 切换点 / 分段摘要的机械正确性
- 判定标的标注与「探索性状态评估」标注
- 指数通路防错源：裸 '000001'（平安银行）拒绝且不打 adapter；
  名称 / secid / 代码三形式白名单解析
- K 线不可得不产出假序列；K 线历史不足如实标注 history_short
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money
from mommy_chaogu.services.regime_series import (
    MAX_DAYS,
    MIN_DAYS,
    NOTE,
    RegimeSeriesService,
)


def _bull_closes(n: int) -> list[float]:
    """稳步上涨、低波动：每日 +0.4%（同 tests/test_backtest_regime.py 口径）。"""
    return [100.0 * (1.004**i) for i in range(n)]


def _bear_closes(n: int) -> list[float]:
    """下跌 + 高波动：基线每日 -0.5%，叠加 ±2% 交替震荡。"""
    closes: list[float] = [100.0]
    for i in range(1, n):
        base = closes[-1] * 0.995
        shock = 1.02 if i % 2 == 0 else 0.98
        closes.append(base * shock)
    return closes


def _bars_from_closes(code: str, closes: list[float], start: str = "2026-01-01") -> list[Bar]:
    base = datetime.fromisoformat(start)
    return [
        Bar(
            code=code,
            name="上证指数",
            interval=BarInterval.D1,
            adjustment=AdjustmentType.FORWARD,
            timestamp=base + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(c)),
            low=Decimal(str(c)),
            close=Decimal(str(c)),
            volume=1000,
            turnover=Money.from_yuan("1000"),
        )
        for i, c in enumerate(closes)
    ]


class FakeAdapter:
    """按代码返回预设日 K；记录调用以验证防错源（不该透传的代码没被透传）。"""

    name = "fake"

    def __init__(self, bars_by_code: dict[str, list[Bar]]) -> None:
        self._bars = bars_by_code
        self.calls: list[tuple[str, int | None]] = []

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: Any = None,
        end: Any = None,
        limit: int | None = None,
    ) -> list[Bar]:
        self.calls.append((code, limit))
        bars = self._bars.get(code, [])
        return list(bars[-limit:]) if limit is not None else list(bars)


class TestRegimeSeriesBull:
    def test_all_bull_window(self) -> None:
        bars = _bars_from_closes("sh000001", _bull_closes(120))
        result = RegimeSeriesService(FakeAdapter({"sh000001": bars})).compute("sh000001", days=20)

        assert result["subject"] == "上证指数 sh000001"
        assert result["index_code"] == "sh000001"
        assert result["secid"] == "1.000001"
        assert result["days"] == 20
        assert len(result["series"]) == 20
        assert all(row["regime"] == "bull" for row in result["series"])
        assert result["counts"] == {"bull": 20, "bear": 0, "sideways": 0}
        assert result["current_regime"] == "bull"
        # 持续天数在整个已判定序列上数：取到的 80 根里前 MA_SHORT(20) 根
        # 按样本不足退化判 sideways，不计入 bull 段——持续天数是下界，
        # 受 bars_fetched 披露的实际历史深度约束（不虚增）。
        assert result["bars_fetched"] == 80
        assert result["current_run_days"] == 60
        assert result["segments"] == [
            {
                "regime": "bull",
                "start": result["series"][0]["date"],
                "end": result["series"][-1]["date"],
                "days": 20,
            }
        ]
        assert result["switches"] == []
        assert "bull×20" in result["summary"]
        assert "上证指数" in result["summary"]

    def test_annotation_labels(self) -> None:
        bars = _bars_from_closes("sh000001", _bull_closes(120))
        result = RegimeSeriesService(FakeAdapter({"sh000001": bars})).compute()

        # 判定标的标注 + 探索性状态评估标注（阈值未校准）
        assert result["subject"] == "上证指数 sh000001"
        assert result["note"] == NOTE
        assert "探索性状态评估" in result["note"]
        assert "未在真实指数数据上校准" in result["note"]

    def test_days_clamped_to_bounds(self) -> None:
        bars = _bars_from_closes("sh000001", _bull_closes(200))
        service = RegimeSeriesService(FakeAdapter({"sh000001": bars}))

        assert len(service.compute("sh000001", days=1)["series"]) == MIN_DAYS
        assert len(service.compute("sh000001", days=500)["series"]) == MAX_DAYS


class TestRegimeSeriesTransition:
    def test_bull_to_bear_switch_inside_window(self) -> None:
        # 60 根 bull + 40 根 bear：窗口 50 天，切换发生在窗口内
        closes = _bull_closes(60) + _bear_closes(40)
        bars = _bars_from_closes("sh000001", closes)
        result = RegimeSeriesService(FakeAdapter({"sh000001": bars})).compute("sh000001", days=50)

        regimes = [row["regime"] for row in result["series"]]
        assert len(regimes) == 50
        assert set(regimes) >= {"bull", "bear"}  # 窗口内至少两种状态
        assert result["current_regime"] == "bear"
        assert result["current_regime"] == regimes[-1]
        # 计数与序列一致；分段总天数覆盖整个窗口
        assert sum(result["counts"].values()) == 50
        assert sum(seg["days"] for seg in result["segments"]) == 50
        # 切换点：from != to，日期升序，最后一个切换的目标态即其后序列的状态
        assert result["switches"], "窗口内应至少有一个切换点"
        for i, switch in enumerate(result["switches"]):
            assert switch["from"] != switch["to"]
            if i > 0:
                assert switch["date"] > result["switches"][i - 1]["date"]
        assert result["summary"]
        assert "bear" in result["summary"]

    def test_segments_are_contiguous_runs(self) -> None:
        closes = _bull_closes(60) + _bear_closes(40)
        bars = _bars_from_closes("sh000001", closes)
        result = RegimeSeriesService(FakeAdapter({"sh000001": bars})).compute("sh000001", days=50)

        series = result["series"]
        segments = result["segments"]
        # 分段首尾相接、与序列逐段对齐
        cursor = 0
        for seg in segments:
            chunk = [row["regime"] for row in series[cursor : cursor + seg["days"]]]
            assert set(chunk) == {seg["regime"]}
            assert series[cursor]["date"] == seg["start"]
            assert series[cursor + seg["days"] - 1]["date"] == seg["end"]
            cursor += seg["days"]
        assert cursor == len(series)


class TestIndexSymbolGuard:
    """防错源（R10）：裸 6 位个股码绝不透传 adapter。"""

    def test_bare_stock_code_rejected_without_adapter_call(self) -> None:
        adapter = FakeAdapter({"000001": _bars_from_closes("000001", _bull_closes(120))})
        result = RegimeSeriesService(adapter).compute("000001")

        assert "error" in result
        assert "平安银行" in result["hint"]
        assert adapter.calls == []  # 没有静默拉个股日 K

    def test_unknown_code_rejected(self) -> None:
        adapter = FakeAdapter({})
        result = RegimeSeriesService(adapter).compute("sh999999")
        assert "error" in result
        assert adapter.calls == []

    def test_resolves_by_name_and_secid(self) -> None:
        bars = _bars_from_closes("sh000300", _bull_closes(120))
        adapter = FakeAdapter({"sh000300": bars})
        service = RegimeSeriesService(adapter)

        by_name = service.compute("沪深300", days=20)
        by_secid = service.compute("1.000300", days=20)
        assert by_name["subject"] == "沪深300 sh000300"
        assert by_secid["index_code"] == "sh000300"
        # 三种形式最终都打到同一指数代码
        assert {call[0] for call in adapter.calls} == {"sh000300"}


class TestDataAvailability:
    def test_no_bars_returns_error_with_subject(self) -> None:
        result = RegimeSeriesService(FakeAdapter({})).compute("sz399006", days=20)
        assert "error" in result
        assert result["subject"] == "创业板指 sz399006"
        assert "series" not in result

    def test_short_history_flagged(self) -> None:
        # 只有 30 根 K 线（不足 window + MA_LONG）：序列前段按样本不足退化，
        # 输出如实标注而不是冒充完整历史
        bars = _bars_from_closes("sh000001", _bull_closes(30))
        result = RegimeSeriesService(FakeAdapter({"sh000001": bars})).compute("sh000001", days=20)

        assert result["bars_fetched"] == 30
        assert result["history_short"] is True
        assert "history_short_note" in result
        assert len(result["series"]) == 20
