"""指标内核单元测试：口径、warm-up 与 look-ahead 防护。

均线类指标（EMA / EMA 云带 / ATR）以 quant/ma-suppression-monitor 为准，
用 pandas 等价实现做交叉校验（pandas 是项目正式依赖，CI 可用）。
"""

from __future__ import annotations

import pandas as pd
import pytest

from mommy_chaogu.experiment import indicators

CLOSES = [100.0 + x for x in (
    0, 1.2, -0.6, 2.1, 0.4, -1.8, 3.0, 1.1, -0.9, 0.7,
    2.4, -1.3, 0.5, 1.6, -2.2, 0.8, 1.9, -0.4, 2.7, -1.0,
)]


def _pd_ema(values: list[float], span: int) -> list[float]:
    return pd.Series(values).ewm(span=span, adjust=False).mean().tolist()


class TestSma:
    def test_basic(self) -> None:
        out = indicators.sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        assert out[:2] == [None, None]
        assert out[2] == pytest.approx(2.0)
        assert out[3] == pytest.approx(3.0)
        assert out[4] == pytest.approx(4.0)

    def test_window_one(self) -> None:
        assert indicators.sma([7.0, 8.0], 1) == [7.0, 8.0]

    def test_window_longer_than_series(self) -> None:
        assert indicators.sma([1.0, 2.0], 5) == [None, None]

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            indicators.sma([1.0], 0)


class TestEma:
    """TradingView 递推口径，与 ma-suppression-monitor 一致。"""

    def test_first_value_is_seed(self) -> None:
        out = indicators.ema(CLOSES, 10)
        assert out[0] == CLOSES[0]
        assert len(out) == len(CLOSES)

    def test_recursion(self) -> None:
        out = indicators.ema([1.0, 2.0, 3.0], 3)
        k = 2.0 / 4.0
        assert out[1] == pytest.approx(2.0 * k + 1.0 * (1 - k))
        assert out[2] == pytest.approx(3.0 * k + out[1] * (1 - k))

    def test_matches_pandas_ewm(self) -> None:
        for span in (3, 21, 55, 89):
            mine = indicators.ema(CLOSES, span)
            ref = _pd_ema(CLOSES, span)
            assert mine == pytest.approx(ref, abs=1e-9)

    def test_constant_series_is_constant(self) -> None:
        out = indicators.ema([5.0] * 50, 10)
        assert out[-1] == pytest.approx(5.0)

    def test_empty(self) -> None:
        assert indicators.ema([], 10) == []


class TestEmaCloud:
    def test_structure(self) -> None:
        cloud = indicators.ema_cloud(CLOSES, 55, 89)
        assert set(cloud) == {"fast", "slow", "cloud_lo", "cloud_hi", "bull"}
        n = len(CLOSES)
        assert all(len(v) == n for v in cloud.values())

    def test_matches_pandas(self) -> None:
        cloud = indicators.ema_cloud(CLOSES, 55, 89)
        f = _pd_ema(CLOSES, 55)
        s = _pd_ema(CLOSES, 89)
        assert cloud["fast"] == pytest.approx(f, abs=1e-9)
        assert cloud["slow"] == pytest.approx(s, abs=1e-9)
        assert cloud["cloud_lo"] == pytest.approx(
            [min(a, b) for a, b in zip(f, s)], abs=1e-9
        )
        assert cloud["cloud_hi"] == pytest.approx(
            [max(a, b) for a, b in zip(f, s)], abs=1e-9
        )
        assert cloud["bull"] == [a > b for a, b in zip(f, s)]

    def test_uptrend_is_bull(self) -> None:
        cloud = indicators.ema_cloud([float(i) for i in range(1, 200)], 55, 89)
        assert cloud["bull"][-1] is True
        assert cloud["cloud_lo"][-1] == pytest.approx(cloud["slow"][-1])


class TestPriceChannel:
    def test_no_lookahead(self) -> None:
        # 第 5 根 bar 创出新高的当日，通道仍应由前 4 根决定
        highs = [10.0, 11.0, 12.0, 13.0, 99.0]
        lows = [8.0, 9.0, 10.0, 11.0, 12.0]
        out = indicators.price_channel(highs, lows, 4)
        assert out[4] == (13.0, 8.0)  # 不含当日的 99.0

    def test_warmup(self) -> None:
        highs = [1.0, 2.0, 3.0]
        lows = [0.5, 1.5, 2.5]
        out = indicators.price_channel(highs, lows, 2)
        assert out[0] is None and out[1] is None
        assert out[2] == (2.0, 0.5)

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            indicators.price_channel([1.0], [1.0, 2.0], 1)


class TestAtr:
    """简单滚动均值口径，与 ma-suppression-monitor 一致。"""

    def test_constant_range(self) -> None:
        n = 30
        closes = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        out = indicators.atr(highs, lows, closes, 14)
        assert out[:13] == [None] * 13
        assert out[13] == pytest.approx(2.0)
        assert out[-1] == pytest.approx(2.0)

    def test_gap_counts(self) -> None:
        closes = [100.0, 110.0]
        highs = [101.0, 111.0]
        lows = [99.0, 109.0]
        out = indicators.atr(highs, lows, closes, 1)
        # 首根 bar TR 退化为 high-low；次根取 max(2, |111-100|, |109-100|) = 11
        assert out[0] == pytest.approx(2.0)
        assert out[1] == pytest.approx(11.0)

    def test_matches_pandas(self) -> None:
        highs = [c + 1.0 for c in CLOSES]
        lows = [c - 1.0 for c in CLOSES]
        h, lo, c = pd.Series(highs), pd.Series(lows), pd.Series(CLOSES)
        tr = pd.concat(
            [h - lo, (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1
        ).max(axis=1)
        for window in (1, 14):
            mine = indicators.atr(highs, lows, CLOSES, window)
            ref = tr.rolling(window).mean().tolist()
            for a, b in zip(mine, ref):
                if b != b:  # NaN
                    assert a is None
                else:
                    assert a == pytest.approx(b, abs=1e-9)


class TestRsi:
    def test_all_gains(self) -> None:
        closes = [float(i) for i in range(1, 20)]
        out = indicators.rsi(closes, 14)
        assert out[14] == pytest.approx(100.0)

    def test_all_losses(self) -> None:
        closes = [float(100 - i) for i in range(20)]
        out = indicators.rsi(closes, 14)
        assert out[14] == pytest.approx(0.0)

    def test_flat_is_50(self) -> None:
        out = indicators.rsi([10.0] * 20, 14)
        assert out[14] == pytest.approx(50.0)

    def test_bounds(self) -> None:
        closes = [10.0, 11.0, 9.5, 12.0, 8.0, 13.0, 7.0, 14.0, 6.0] * 3
        out = indicators.rsi(closes, 5)
        for v in out:
            if v is not None:
                assert 0.0 <= v <= 100.0


class TestRelativeStrength:
    def test_outperformance(self) -> None:
        target = [100.0, 110.0, 121.0]
        bench = [100.0, 101.0, 102.0]
        out = indicators.relative_strength(target, bench, 2)
        assert out[0] is None and out[1] is None
        assert out[2] == pytest.approx(0.21 - 0.02)

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            indicators.relative_strength([1.0], [1.0, 2.0], 1)


class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        a = indicators.ema_cloud(CLOSES, 55, 89)
        b = indicators.ema_cloud(list(CLOSES), 55, 89)
        assert a == b
