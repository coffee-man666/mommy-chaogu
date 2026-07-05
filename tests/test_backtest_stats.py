"""tests/test_backtest_stats - scripts/backtest_stats.py 单测。

注意：``backtest_stats`` 是 ``scripts/`` 下的独立脚本（非包模块），这里
显式把 ``scripts/`` 加入 ``sys.path`` 再导入，便于直接测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ 不在默认 import 路径里，手动加进来
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from backtest_stats import (  # noqa: E402
    binomial_test,
    compute_buyhold_baseline,
    format_hit_rate,
    wilson_ci,
)

# ---------- Wilson CI ----------


class TestWilsonCI:
    def test_known_value_7_of_10(self) -> None:
        # 已知：7/10 的 Wilson 95% CI ≈ [0.3968, 0.8922]
        low, high = wilson_ci(7, 10)
        assert low == pytest.approx(0.3968, abs=0.005)
        assert high == pytest.approx(0.8922, abs=0.005)

    def test_known_value_53_of_100(self) -> None:
        # 53/100 的 Wilson 95% CI ≈ [0.4329, 0.6249]
        low, high = wilson_ci(53, 100)
        assert low == pytest.approx(0.4329, abs=0.005)
        assert high == pytest.approx(0.6249, abs=0.005)

    def test_center_at_phat(self) -> None:
        # 区间必须包住点估计 hits/total
        for hits, total in [(0, 10), (5, 10), (10, 10), (3, 8)]:
            low, high = wilson_ci(hits, total)
            phat = hits / total
            assert low <= phat <= high

    def test_zero_total_returns_widest(self) -> None:
        assert wilson_ci(0, 0) == (0.0, 1.0)

    def test_bounds_within_unit_interval(self) -> None:
        for hits, total in [(0, 5), (5, 5), (1, 1), (99, 100)]:
            low, high = wilson_ci(hits, total)
            assert 0.0 <= low <= high <= 1.0


# ---------- Binomial test ----------


class TestBinomialTest:
    def test_known_value_7_of_10(self) -> None:
        # R: binom.test(7, 10, 0.5)$p.value == 0.34375
        assert binomial_test(7, 10, 0.5) == pytest.approx(0.34375, abs=1e-9)

    def test_known_value_0_of_10(self) -> None:
        # R: binom.test(0, 10, 0.5)$p.value == 0.001953125
        assert binomial_test(0, 10, 0.5) == pytest.approx(0.001953125, abs=1e-12)

    def test_most_likely_not_significant(self) -> None:
        # 5/10 是 p=0.5 下最可能的结果，p 值应为 1.0
        assert binomial_test(5, 10, 0.5) == pytest.approx(1.0, abs=1e-9)

    def test_extreme_10_of_10(self) -> None:
        # R: binom.test(10, 10, 0.5)$p.value == 0.001953125
        assert binomial_test(10, 10, 0.5) == pytest.approx(0.001953125, abs=1e-12)

    def test_zero_total(self) -> None:
        assert binomial_test(0, 0) == 1.0

    def test_invalid_p_raises(self) -> None:
        with pytest.raises(ValueError):
            binomial_test(3, 10, 1.5)


# ---------- format_hit_rate ----------


class TestFormatHitRate:
    def test_normal_output_format(self) -> None:
        out = format_hit_rate(7, 10)
        # 70.0% 起头，含 Wilson CI 与 p 值
        assert out.startswith("70.0%")
        assert "Wilson 95% CI: [" in out
        assert "p=0.34" in out

    def test_includes_ci_brackets_and_pvalue(self) -> None:
        out = format_hit_rate(53, 100)
        assert out.startswith("53.0%")
        assert "Wilson 95% CI: [" in out
        assert "], p=" in out or "], p<" in out
        # p 值段以 p= 开头
        assert ", p=" in out or ", p<" in out

    def test_zero_total(self) -> None:
        assert format_hit_rate(0, 0) == "N/A (无样本)"

    def test_all_hits(self) -> None:
        out = format_hit_rate(10, 10)
        assert out.startswith("100.0%")
        assert "Wilson 95% CI: [" in out
        # 10/10 在 p=0.5 下 p 值很小（< 0.01）
        assert "p=0.002" in out or "p<0.001" in out

    def test_no_hits(self) -> None:
        out = format_hit_rate(0, 10)
        assert out.startswith("0.0%")
        assert "Wilson 95% CI: [" in out


# ---------- compute_buyhold_baseline ----------


class TestBuyHoldBaseline:
    def test_all_up(self) -> None:
        preds = [
            {"entry_price": 10.0, "actual_price": 11.0},
            {"entry_price": 20.0, "actual_price": 22.0},
        ]
        r = compute_buyhold_baseline(preds)
        assert r == {"hits": 2, "total": 2, "rate": 1.0}

    def test_all_down(self) -> None:
        preds = [
            {"entry_price": 10.0, "actual_price": 9.0},
            {"entry_price": 20.0, "actual_price": 18.0},
        ]
        r = compute_buyhold_baseline(preds)
        assert r == {"hits": 0, "total": 2, "rate": 0.0}

    def test_mixed(self) -> None:
        preds = [
            {"entry_price": 10.0, "actual_price": 11.0},  # up
            {"entry_price": 10.0, "actual_price": 9.0},  # down
            {"entry_price": 10.0, "actual_price": 10.0},  # flat → 不算命中
        ]
        r = compute_buyhold_baseline(preds)
        assert r == {"hits": 1, "total": 3, "rate": pytest.approx(1 / 3)}

    def test_skips_missing_actual(self) -> None:
        # 过期未验证（actual_price=None）应被剔除
        preds = [
            {"entry_price": 10.0, "actual_price": 11.0},
            {"entry_price": 10.0, "actual_price": None},
            {"entry_price": 10.0},  # 无 actual 字段
        ]
        r = compute_buyhold_baseline(preds)
        assert r == {"hits": 1, "total": 1, "rate": 1.0}

    def test_accepts_entry_actual_keys(self) -> None:
        # backtest_llm.py 用 entry/actual 命名
        preds = [{"entry": 10.0, "actual": 12.0}]
        r = compute_buyhold_baseline(preds)
        assert r == {"hits": 1, "total": 1, "rate": 1.0}

    def test_empty(self) -> None:
        assert compute_buyhold_baseline([]) == {"hits": 0, "total": 0, "rate": 0.0}

    def test_optional_adapter_cache_store_ignored(self) -> None:
        # 传任意 adapter/cache_store 不应影响结果
        preds = [{"entry_price": 10.0, "actual_price": 9.0}]
        r = compute_buyhold_baseline(preds, adapter=object(), cache_store=object())
        assert r == {"hits": 0, "total": 1, "rate": 0.0}
