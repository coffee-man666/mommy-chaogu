"""
冒烟测试: 用合成 OHLC 数据跑通 ma_suppression_monitor 的全部模块。

不需要真实行情数据, 不访问网络。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ma_suppression_monitor import (
    DualEngine,
    atr,
    baseline,
    ema_cloud,
    fit_channel,
    forward_returns,
    load_csv,
    portfolio_sim,
    resample_bars,
    score_events,
    signal_pairs,
    trend_regime,
    validate,
)


def make_bars(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """合成一段 "上涨 → 下跌 → 底部企稳 → 反弹" 的 30min bars。"""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-01-05 09:30", periods=n, freq="30min", tz="America/New_York")
    seg = np.concatenate(
        [
            np.linspace(0, 30, n // 4),  # 上涨
            np.linspace(30, -15, n // 2),  # 下跌
            np.linspace(-15, -12, n // 8),  # 企稳
            np.linspace(-12, 0, n - n // 4 - n // 2 - n // 8),  # 反弹
        ]
    )
    noise = rng.normal(0, 1.2, n).cumsum() * 0.15 + rng.normal(0, 0.8, n)
    close = 100 + seg + noise
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.uniform(0.1, 0.9, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 0.9, n)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1e4, 1e6, n).astype(float),
        },
        index=t,
    )


@pytest.fixture()
def bars() -> pd.DataFrame:
    return validate(make_bars())


def test_validate_and_resample(bars):
    out = resample_bars(bars, "2h")
    assert 0 < len(out) < len(bars)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]


def test_load_csv_roundtrip(bars, tmp_path):
    p = tmp_path / "bars.csv"
    df = bars.reset_index(names="time")
    df.to_csv(p, index=False)
    loaded = load_csv(str(p))
    assert len(loaded) == len(bars)
    assert loaded["close"].iloc[-1] == pytest.approx(bars["close"].iloc[-1])


def test_dual_engine_frame(bars):
    eng = DualEngine()
    frame = eng.run(bars)
    expected = {
        "regime",
        "cross_age",
        "cloud_dist",
        "cloud_width",
        "slope_slow",
        "chan_pos",
        "chan_slope",
        "score",
        "s_slope",
        "s_hl",
        "s_dist",
        "s_gap",
        "crash_blocked",
        "suppression_state",
        "tests_26",
        "engine",
        "alert",
    }
    assert expected.issubset(frame.columns)
    assert len(frame) == len(bars)
    assert frame["score"].between(0, 100).all()
    assert frame["regime"].isin(["BULL", "BEAR"]).all()
    assert (
        frame["engine"].isin(["SHORT_ACTIVE", "SHORT_REDUCED", "BOTTOM_WATCH", "LONG_SIDE"]).all()
    )


def test_readout(bars):
    eng = DualEngine()
    eng.run(bars)
    out = eng.readout(bars)
    for key in ["time", "close", "regime", "bottom_score", "engine", "alert"]:
        assert key in out
    assert 0 <= out["bottom_score"] <= 100


def test_suppression_events_structure(bars):
    eng = DualEngine()
    eng.run(bars)
    for e in eng.suppression_events_:
        assert e.t_armed <= e.t_engaged <= e.t_confirmed
        assert e.count >= 1
        assert e.depth_atr >= 0
        assert e.dwell_bars >= 1


def test_backtest_utils(bars):
    eng = DualEngine()
    frame = eng.run(bars)
    ev_idx = score_events(frame["score"], on=65, off=35)
    fr = forward_returns(bars, ev_idx, [13, 26])
    bl = baseline(bars, [13, 26])
    assert set(bl) == {13, 26}
    assert {"r13", "r26"}.issubset(fr.columns) or fr.empty

    flags = pd.Series(False, index=bars.index)
    flags.iloc[::50] = True
    trades = signal_pairs(bars, flags, flags.shift(25, fill_value=False))
    assert {"entry_t", "exit_t", "ret", "bars_held"}.issubset(trades.columns) or trades.empty

    pos = pd.Series(0, index=bars.index)
    pos.iloc[100:400] = 1
    rets = portfolio_sim(bars, pos)
    assert len(rets) == len(bars)


def test_pivot_channel_and_indicators(bars):
    ch = fit_channel(bars, direction="down")
    assert ch.touches >= 0
    cloud = ema_cloud(bars["close"])
    regime = trend_regime(cloud)
    assert (regime["cross_age"] >= 0).all()
    a = atr(bars)
    assert a.dropna().gt(0).all()


def test_macro_channel(bars):
    import macro_channel as mc

    down = bars.iloc[len(bars) // 4 : 3 * len(bars) // 4]  # 下跌段
    ch = mc.fit_macro_channel(down)
    assert ch.ok
    assert ch.slope < 0
    report = mc.channel_report(ch, down, label="test")
    assert "Macro Channel" in report
