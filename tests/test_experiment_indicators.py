"""指标内核单元测试：口径、warm-up 与 look-ahead 防护。"""

from __future__ import annotations

import pytest

from mommy_chaogu.experiment import indicators


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
    def test_seed_is_sma(self) -> None:
        values = [float(i) for i in range(1, 11)]
        out = indicators.ema(values, 3)
        assert out[0] is None and out[1] is None
        assert out[2] == pytest.approx(sum([1.0, 2.0, 3.0]) / 3)

    def test_recursion(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0]
        out = indicators.ema(values, 3)
        k = 2.0 / 4.0
        expected3 = 4.0 * k + 2.0 * (1 - k)
        assert out[3] == pytest.approx(expected3)

    def test_constant_series_converges(self) -> None:
        out = indicators.ema([5.0] * 50, 10)
        assert out[-1] == pytest.approx(5.0)


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
    def test_constant_range(self) -> None:
        # 每根 bar 高低差恒为 2，且无跳空 → ATR 收敛到 2
        n = 30
        closes = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        out = indicators.atr(highs, lows, closes, 14)
        assert out[14] == pytest.approx(2.0)
        assert out[-1] == pytest.approx(2.0)

    def test_gap_counts(self) -> None:
        # 跳空高开：TR 应取 |high - prev_close|
        closes = [100.0, 110.0]
        highs = [101.0, 111.0]
        lows = [99.0, 109.0]
        out = indicators.atr(highs, lows, closes, 1)
        # window=1 → ATR 即 TR 本身：max(111-109, |111-100|, |109-100|) = 11
        assert out[1] == pytest.approx(11.0)


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
        closes = [float((i * 37) % 23 + 90) for i in range(100)]
        a = indicators.rsi(closes, 14)
        b = indicators.rsi(list(closes), 14)
        assert a == b
