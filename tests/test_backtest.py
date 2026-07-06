"""BacktestEngine 单测 — 使用 CacheStore + tmp_path 模拟历史数据。

不依赖网络，所有数据通过 CacheStore 写入临时 SQLite。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.backtest.engine import BacktestEngine, BacktestResult
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data import MarketType, Money, Quote, QuoteType

# ---------- 辅助函数 ----------

FLOAT_MCAP = 10_000_000_000  # 100 亿流通市值
DATES = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]


def _make_bar(code: str, date: str, close: str | float, name: str = "测试股") -> dict:
    """构造一根日 K 线 dict（和 CacheStore.set_bar 格式一致）。"""
    close_s = str(close)
    return {
        "code": code,
        "name": name,
        "timestamp": f"{date}T15:00:00+08:00",
        "interval": "1d",
        "adjustment": "forward",
        "open": close_s,
        "high": close_s,
        "low": close_s,
        "close": close_s,
        "volume": 1_000_000,
        "turnover": "10000000.00",
        "change_pct": "1.0",
        "turnover_rate": "1.0",
        "amplitude": "2.0",
    }


def _make_flows(code: str, date: str, main_net: int, name: str = "测试股") -> list[dict]:
    """构造一天的资金流 list[dict]（和 CacheStore.set_money_flow_history 格式一致）。"""
    return [
        {
            "code": code,
            "name": name,
            "timestamp": f"{date}T15:00:00+08:00",
            "main_net": {"amount": str(main_net), "currency": "CNY"},
            "small_net": {"amount": "0", "currency": "CNY"},
            "medium_net": {"amount": "0", "currency": "CNY"},
            "large_net": {"amount": "0", "currency": "CNY"},
            "super_large_net": {"amount": "0", "currency": "CNY"},
            "main_net_ratio": "10.0",
        }
    ]


def _make_quote(code: str, float_mcap: int = FLOAT_MCAP, name: str = "测试股") -> Quote:
    """构造带流通市值的 Quote。"""
    return Quote(
        code=code,
        name=name,
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("10"),
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        prev_close=Decimal("10"),
        change=Decimal("0"),
        change_pct=Decimal("0"),
        volume=0,
        turnover=Money.from_yuan(0),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=Money.from_yuan(float_mcap),
        circulating_market_cap=Money.from_yuan(float_mcap),
        timestamp=datetime.now(UTC),
    )


def _seed_bars(
    store: CacheStore, code: str, closes: list[str | float], name: str = "测试股"
) -> None:
    """写入 DATES 对应的日 K 线。"""
    for date, close in zip(DATES, closes, strict=False):
        store.set_bar(code, "1d", "forward", date, _make_bar(code, date, close, name))


def _seed_flows(
    store: CacheStore, code: str, date: str, main_net: int, name: str = "测试股"
) -> None:
    """写入一天的资金流数据。"""
    store.set_money_flow_history(code, date, _make_flows(code, date, main_net, name))


@pytest.fixture
def engine(tmp_path: Path) -> BacktestEngine:
    return BacktestEngine(tmp_path / "backtest.db")


@pytest.fixture
def store(tmp_path: Path) -> CacheStore:
    return CacheStore(tmp_path / "backtest.db")


# -----------------------------------------------------------------------
# 测试
# -----------------------------------------------------------------------


def test_empty_when_no_data(engine: BacktestEngine):
    """无任何缓存数据时返回空结果 + 提示消息。"""
    result = engine.run(["600519"], "2026-06-01", "2026-06-05", hold_days=3)
    assert result.total_signals == 0
    assert result.winning_signals == 0
    assert result.losing_signals == 0
    assert result.win_rate == 0.0
    assert result.signals_detail == []
    assert "无缓存数据" in result.message


def test_single_signal_winning(engine: BacktestEngine, store: CacheStore):
    """主力净流入触发信号，持有 3 天后上涨 → 获胜。"""
    code = "600519"
    store.set_quote(code, _make_quote(code))
    # 收盘价：信号日 10 → 3 天后 11（+10%）
    _seed_bars(store, code, ["10", "10", "10", "11", "11"])
    # 5 亿主力净流入 → ratio = 5e8 / 1e10 = 5% = 500bp > 5bp → 触发
    _seed_flows(store, code, "2026-06-01", 500_000_000)

    result = engine.run([code], "2026-06-01", "2026-06-05", hold_days=3)
    assert result.total_signals == 1
    assert result.winning_signals == 1
    assert result.losing_signals == 0
    assert result.win_rate == 1.0
    sig = result.signals_detail[0]
    assert sig["code"] == code
    assert sig["date"] == "2026-06-01"
    assert sig["return_after_3d"] == pytest.approx(10.0, abs=0.01)
    assert sig["return_after_hold_pct"] == pytest.approx(10.0, abs=0.01)


def test_single_signal_losing(engine: BacktestEngine, store: CacheStore):
    """主力净流入触发信号，持有 3 天后下跌 → 亏损。"""
    code = "000001"
    store.set_quote(code, _make_quote(code))
    # 收盘价：信号日 10 → 3 天后 9（-10%）
    _seed_bars(store, code, ["10", "10", "10", "9", "9"])
    _seed_flows(store, code, "2026-06-01", 500_000_000)

    result = engine.run([code], "2026-06-01", "2026-06-05", hold_days=3)
    assert result.total_signals == 1
    assert result.winning_signals == 0
    assert result.losing_signals == 1
    assert result.win_rate == 0.0
    sig = result.signals_detail[0]
    assert sig["return_after_hold_pct"] == pytest.approx(-10.0, abs=0.01)


def test_win_rate_calculation(engine: BacktestEngine, store: CacheStore):
    """3 个信号：2 赢 1 输 → 胜率 2/3。"""
    # Code A: 赢 (+10%)
    store.set_quote("A001", _make_quote("A001"))
    _seed_bars(store, "A001", ["10", "10", "10", "11", "11"])
    _seed_flows(store, "A001", "2026-06-01", 500_000_000)

    # Code B: 赢 (+5%)
    store.set_quote("B002", _make_quote("B002"))
    _seed_bars(store, "B002", ["10", "10", "10", "10.5", "10.5"])
    _seed_flows(store, "B002", "2026-06-01", 500_000_000)

    # Code C: 输 (-8%)
    store.set_quote("C003", _make_quote("C003"))
    _seed_bars(store, "C003", ["10", "10", "10", "9.2", "9.2"])
    _seed_flows(store, "C003", "2026-06-01", 500_000_000)

    result = engine.run(["A001", "B002", "C003"], "2026-06-01", "2026-06-05", hold_days=3)
    assert result.total_signals == 3
    assert result.winning_signals == 2
    assert result.losing_signals == 1
    assert result.win_rate == pytest.approx(2 / 3, abs=0.01)
    # 平均收益 ≈ (10 + 5 - 8) / 3 = 2.33%
    assert result.avg_return_pct == pytest.approx(2.3333, abs=0.1)


def test_no_signal_when_ratio_below_threshold(engine: BacktestEngine, store: CacheStore):
    """主力净流入占比 < 5bp 时不触发信号。"""
    code = "600519"
    store.set_quote(code, _make_quote(code))
    _seed_bars(store, code, ["10", "11", "11", "11", "11"])
    # 100 万 → ratio = 1e6 / 1e10 = 0.01% = 1bp < 5bp → 不触发
    _seed_flows(store, code, "2026-06-01", 1_000_000)

    result = engine.run([code], "2026-06-01", "2026-06-05", hold_days=3)
    assert result.total_signals == 0
    assert result.winning_signals == 0
    assert result.win_rate == 0.0
    assert result.signals_detail == []


def test_result_fields_present(engine: BacktestEngine, store: CacheStore):
    """验证 BacktestResult 所有字段存在且类型正确。"""
    code = "600519"
    store.set_quote(code, _make_quote(code))
    # 6 根 K 线保证 return_after_5d 有值
    dates6 = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06"]
    closes6 = ["10", "10.5", "10.5", "11", "11", "11"]
    for d, c in zip(dates6, closes6, strict=False):
        store.set_bar(code, "1d", "forward", d, _make_bar(code, d, c))
    _seed_flows(store, code, "2026-06-01", 500_000_000)

    result = engine.run([code], "2026-06-01", "2026-06-06", hold_days=3)

    # BacktestResult 基本字段
    assert isinstance(result, BacktestResult)
    assert isinstance(result.total_signals, int)
    assert isinstance(result.winning_signals, int)
    assert isinstance(result.losing_signals, int)
    assert isinstance(result.win_rate, float)
    assert isinstance(result.avg_return_pct, float)
    assert isinstance(result.max_drawdown_pct, float)
    assert isinstance(result.sharpe_ratio, float)
    assert isinstance(result.signals_detail, list)
    assert result.message == ""  # 有数据时 message 为空

    # signals_detail 每条的字段
    assert len(result.signals_detail) == 1
    sig = result.signals_detail[0]
    for key in (
        "code",
        "name",
        "date",
        "ratio_bp",
        "return_after_1d",
        "return_after_3d",
        "return_after_5d",
        "return_after_hold_pct",
    ):
        assert key in sig, f"missing key: {key}"

    assert isinstance(sig["code"], str)
    assert isinstance(sig["date"], str)
    assert isinstance(sig["ratio_bp"], float)
    assert sig["ratio_bp"] == pytest.approx(500.0, abs=0.1)  # 500bp
    assert isinstance(sig["return_after_1d"], float)
    assert isinstance(sig["return_after_5d"], float)


def test_return_at_multiple_horizons(engine: BacktestEngine, store: CacheStore):
    """信号触发后 1d/3d/5d 各档收益正确计算。"""
    code = "600519"
    store.set_quote(code, _make_quote(code))
    # 06-01: 10 → 06-02: 10.5 (+5%) → 06-04: 11 (+10%) → 06-05 不足以 5d
    # 需要 6 根 K 线才能算 return_after_5d
    dates = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06"]
    closes = ["10", "10.5", "10.5", "11", "11", "12"]
    for d, c in zip(dates, closes, strict=False):
        store.set_bar(code, "1d", "forward", d, _make_bar(code, d, c))
    _seed_flows(store, code, "2026-06-01", 500_000_000)

    result = engine.run([code], "2026-06-01", "2026-06-06", hold_days=3)
    assert result.total_signals == 1
    sig = result.signals_detail[0]
    # return_after_1d: (10.5 - 10) / 10 = 5%
    assert sig["return_after_1d"] == pytest.approx(5.0, abs=0.01)
    # return_after_3d: (11 - 10) / 10 = 10%
    assert sig["return_after_3d"] == pytest.approx(10.0, abs=0.01)
    # return_after_5d: (12 - 10) / 10 = 20%
    assert sig["return_after_5d"] == pytest.approx(20.0, abs=0.01)
