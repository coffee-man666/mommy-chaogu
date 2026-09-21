"""四星提升的 Python 侧测试：均线参数化 / get_bars MA / run_backtest 工具。

全部离线（fake adapter / 临时缓存库），不触网。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.agent.tools.analysis import _handle_check_kline_signal
from mommy_chaogu.agent.tools.backtest import _handle_run_backtest
from mommy_chaogu.agent.tools.bars import _handle_get_bars
from mommy_chaogu.agent.tools.base import ToolContext


@dataclass
class _FakeMoney:
    amount: Decimal


@dataclass
class _FakeBar:
    code: str
    name: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: _FakeMoney
    change_pct: Decimal | None = None


class _FakeAdapter:
    """只实现 get_bars 的假适配器（旧→新输入；limit 取最近的 N 根，与真实源一致）。"""

    def __init__(self, bars: dict[str, list[Any]]) -> None:
        self._bars = bars

    def get_bars(self, code: str, interval: Any = None, limit: int = 30) -> list[Any]:
        series = self._bars.get(code, [])
        return series[-limit:]

    def get_quotes(self, codes: list[str]) -> list[Any]:
        return []


def _ctx(bars: dict[str, list[Any]] | None = None, market_db: Path | None = None) -> ToolContext:
    return ToolContext(adapter=_FakeAdapter(bars or {}), market_db=market_db)


def _series(code: str, closes: list[float]) -> list[Any]:
    """按收盘序列构造旧→新日 K。"""
    start = date(2026, 6, 1)
    return [
        _FakeBar(
            code=code,
            name="测试股",
            timestamp=datetime.combine(start + timedelta(days=i), datetime.min.time()),
            open=Decimal(str(c)),
            high=Decimal(str(c)),
            low=Decimal(str(c)),
            close=Decimal(str(c)),
            volume=1_000_000,
            turnover=_FakeMoney(Decimal(str(c * 1_000_000))),
        )
        for i, c in enumerate(closes)
    ]


def _cross_series(n: int = 40, cross: bool = True) -> list[float]:
    """前段缓跌（short 压在 slow 下），cross=True 时最后两根急拉制造金叉。

    拉抬幅度要足够让 5 日线越过 20 日线（MA5 只有 5 根权重，缓跌序列需要
    两根大阳才能把均值拉过 MA20）。
    """
    closes = [10.0 - i * 0.05 for i in range(n - 2)]
    if cross:
        closes += [closes[-1] + 3.0, closes[-1] + 6.0]
    else:
        closes += [closes[-1] - 0.05, closes[-1] - 0.05]
    return [round(c, 4) for c in closes]


class TestKlineSignalParametrized:
    def test_default_windows_hit_and_fields(self) -> None:
        ctx = _ctx({"600519": _series("600519", _cross_series())})
        result = json.loads(
            _handle_check_kline_signal(ctx, {"codes": ["600519"], "signal": "ma_golden_cross"})
        )
        hits = result["results"]
        assert len(hits) == 1
        assert hits[0]["fast"] == 5 and hits[0]["slow"] == 20
        assert hits[0]["signal"] == "ma_golden_cross"
        assert hits[0]["code"] == "600519"

    def test_custom_windows_echoed(self) -> None:
        # 最后两根急拉同样让 10 日线上穿 30 日线（30 根缓跌后两根 +1.6）
        ctx = _ctx({"600519": _series("600519", _cross_series(n=45))})
        result = json.loads(
            _handle_check_kline_signal(
                ctx,
                {"codes": ["600519"], "signal": "ma_golden_cross", "fast": 10, "slow": 30},
            )
        )
        assert result["results"], "10/30 应在急拉序列上命中"
        assert result["results"][0]["fast"] == 10 and result["results"][0]["slow"] == 30

    def test_invalid_windows_rejected(self) -> None:
        ctx = _ctx()
        result = json.loads(
            _handle_check_kline_signal(
                ctx, {"codes": ["600519"], "signal": "ma_golden_cross", "fast": 30, "slow": 10}
            )
        )
        assert "error" in result and "fast" in result["error"]

    def test_no_cross_no_hit(self) -> None:
        ctx = _ctx({"600519": _series("600519", _cross_series(cross=False))})
        result = json.loads(
            _handle_check_kline_signal(ctx, {"codes": ["600519"], "signal": "ma_golden_cross"})
        )
        assert result["results"] == []

    def test_wide_window_beyond_120_bars_hits(self) -> None:
        # 回归背景：内部取数曾被钳到 120 根，而金叉判定需要 slow+2 根——
        # slow ≥ 119（schema 放行到 250）永远凑不齐，静默空结果。
        n = 252
        closes = [10.0 - i * 0.05 for i in range(n - 2)] + [12.0, 15.0]
        ctx = _ctx({"600519": _series("600519", [round(c, 4) for c in closes])})
        result = json.loads(
            _handle_check_kline_signal(
                ctx, {"codes": ["600519"], "signal": "ma_golden_cross", "fast": 5, "slow": 250}
            )
        )
        assert len(result["results"]) == 1, "slow=250 的金叉不应落进死区"
        assert result["results"][0]["slow"] == 250

    def test_insufficient_history_reported_not_silent(self) -> None:
        # 历史不足 slow+2 根：既不能确认也不能否认金叉——显式标出，
        # 不与「无信号」混为一谈。
        ctx = _ctx({"600519": _series("600519", [10.0] * 50)})
        result = json.loads(
            _handle_check_kline_signal(
                ctx, {"codes": ["600519"], "signal": "ma_golden_cross", "fast": 5, "slow": 250}
            )
        )
        assert result["results"] == []
        assert result["skipped"] == [
            {"code": "600519", "reason": "insufficient_history", "bars": 50}
        ]

    def test_normal_output_shape_has_no_skipped_key(self) -> None:
        ctx = _ctx({"600519": _series("600519", _cross_series())})
        result = json.loads(
            _handle_check_kline_signal(ctx, {"codes": ["600519"], "signal": "ma_golden_cross"})
        )
        assert result["results"]
        assert "skipped" not in result


class TestBarsIncludeMa:
    def test_include_ma_appends_window_fields(self) -> None:
        ctx = _ctx({"600519": _series("600519", [10 + i * 0.1 for i in range(10)])})
        rows = json.loads(
            _handle_get_bars(ctx, {"code": "600519", "limit": 10, "include_ma": True})
        )
        assert len(rows) == 10
        # 前 4 根不足 5 日窗口 → ma5 null；第 5 根起有值且等于前 5 收盘均值
        assert rows[0]["ma_5"] is None
        assert rows[4]["ma_5"] == round(sum(10 + i * 0.1 for i in range(5)) / 5, 4)
        assert "ma_20" in rows[0]  # 20 日窗口全 null 但字段在

    def test_default_no_ma(self) -> None:
        ctx = _ctx({"600519": _series("600519", [10.0] * 5)})
        rows = json.loads(_handle_get_bars(ctx, {"code": "600519", "limit": 5}))
        assert "ma_5" not in rows[0]

    def test_custom_windows(self) -> None:
        ctx = _ctx({"600519": _series("600519", [10 + i for i in range(12)])})
        rows = json.loads(
            _handle_get_bars(
                ctx, {"code": "600519", "limit": 12, "include_ma": True, "ma_windows": [3, 12]}
            )
        )
        assert rows[2]["ma_3"] is not None
        assert rows[11]["ma_12"] == round(sum(10 + i for i in range(12)) / 12, 4)
        assert rows[10]["ma_12"] is None


class TestRunBacktestTool:
    def test_market_db_missing_error(self) -> None:
        ctx = _ctx(market_db=None)
        result = json.loads(
            _handle_run_backtest(
                ctx,
                {"codes": ["600519"], "start_date": "2026-01-01", "end_date": "2026-06-01"},
            )
        )
        assert "error" in result

    def test_empty_cache_returns_message_not_crash(self, tmp_path: Path) -> None:
        ctx = _ctx(market_db=tmp_path / "market.db")
        result = json.loads(
            _handle_run_backtest(
                ctx,
                {"codes": ["600519"], "start_date": "2026-01-01", "end_date": "2026-06-01"},
            )
        )
        # 空缓存：total_signals 0 + message 提示（引擎的诚实降级路径）
        assert result["total_signals"] == 0
        assert result["message"] != ""

    def test_invalid_args_structured_error(self, tmp_path: Path) -> None:
        ctx = _ctx(market_db=tmp_path / "market.db")
        bad = json.loads(
            _handle_run_backtest(ctx, {"codes": [], "start_date": "x", "end_date": "y"})
        )
        assert "error" in bad

    def test_registry_and_market_only_publish(self) -> None:
        from mommy_chaogu.agent.research_tools import allowed_base_tool_names
        from mommy_chaogu.agent.tools.registry import _TOOL_DEFINITIONS

        assert "run_backtest" in {d.name for d in _TOOL_DEFINITIONS}
        assert "run_backtest" in allowed_base_tool_names("market-only")
