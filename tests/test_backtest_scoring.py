"""统一评分模块 ``mommy_chaogu.backtest.scoring`` 的测试。"""

from __future__ import annotations

from mommy_chaogu.backtest.scoring import (
    score_direction,
    verify_prediction,
)

# ---------- bullish ----------


def test_bullish_strong_hit() -> None:
    assert score_direction("bullish", 2.01) == ("hit", 1.0)
    assert score_direction("bullish", 5.0) == ("hit", 1.0)
    assert score_direction("bullish", 100.0) == ("hit", 1.0)


def test_bullish_weak_hit() -> None:
    assert score_direction("bullish", 0.01) == ("hit", 0.7)
    assert score_direction("bullish", 1.99) == ("hit", 0.7)


def test_bullish_weak_miss() -> None:
    assert score_direction("bullish", -1.99) == ("missed", 0.3)
    assert score_direction("bullish", -0.01) == ("missed", 0.3)


def test_bullish_strong_miss() -> None:
    assert score_direction("bullish", -2.01) == ("missed", 0.0)
    assert score_direction("bullish", -10.0) == ("missed", 0.0)


# ---------- bearish ----------


def test_bearish_strong_hit() -> None:
    assert score_direction("bearish", -2.01) == ("hit", 1.0)
    assert score_direction("bearish", -5.0) == ("hit", 1.0)
    assert score_direction("bearish", -100.0) == ("hit", 1.0)


def test_bearish_weak_hit() -> None:
    assert score_direction("bearish", -0.01) == ("hit", 0.7)
    assert score_direction("bearish", -1.99) == ("hit", 0.7)


def test_bearish_weak_miss() -> None:
    assert score_direction("bearish", 0.01) == ("missed", 0.3)
    assert score_direction("bearish", 1.99) == ("missed", 0.3)


def test_bearish_strong_miss() -> None:
    assert score_direction("bearish", 2.01) == ("missed", 0.0)
    assert score_direction("bearish", 10.0) == ("missed", 0.0)


# ---------- neutral（±2% 死区，修复固定 hit 虚增） ----------


def test_neutral_inside_dead_zone_is_hit() -> None:
    assert score_direction("neutral", 0.0) == ("hit", 0.5)
    assert score_direction("neutral", 1.0) == ("hit", 0.5)
    assert score_direction("neutral", -1.5) == ("hit", 0.5)


def test_neutral_outside_dead_zone_is_missed() -> None:
    assert score_direction("neutral", 2.01) == ("missed", 0.3)
    assert score_direction("neutral", -2.01) == ("missed", 0.3)
    assert score_direction("neutral", 10.0) == ("missed", 0.3)


# ---------- 边界值（正好 ±2%） ----------


def test_bullish_boundary_at_dead_zone() -> None:
    # 正好 +2：不满足 >2，落入 >0 分支 → (hit, 0.7)
    assert score_direction("bullish", 2.0) == ("hit", 0.7)
    # 正好 -2：不满足 >-2，落入 else → (missed, 0.0)
    assert score_direction("bullish", -2.0) == ("missed", 0.0)


def test_bearish_boundary_at_dead_zone() -> None:
    # 正好 -2：不满足 <-2，落入 <0 分支 → (hit, 0.7)
    assert score_direction("bearish", -2.0) == ("hit", 0.7)
    # 正好 +2：不满足 <2，落入 else → (missed, 0.0)
    assert score_direction("bearish", 2.0) == ("missed", 0.0)


def test_neutral_boundary_at_dead_zone() -> None:
    # neutral 用 <=，所以正好 ±2 算 hit
    assert score_direction("neutral", 2.0) == ("hit", 0.5)
    assert score_direction("neutral", -2.0) == ("hit", 0.5)


def test_score_direction_status_in_expected_set() -> None:
    for d in ("bullish", "bearish", "neutral"):
        for chg in (-10.0, -2.0, -0.5, 0.0, 0.5, 2.0, 10.0):
            status, score = score_direction(d, chg)
            assert status in ("hit", "missed")
            assert 0.0 <= score <= 1.0


# ---------- verify_prediction 入口 ----------


def test_verify_prediction_bullish_hit() -> None:
    pred = {"direction": "bullish"}
    res = verify_prediction(pred, actual_price=10.5, actual_change_pct=5.0)
    assert res.status == "hit"
    assert res.score == 1.0
    assert res.price == 10.5
    assert res.change_pct == 5.0


def test_verify_prediction_bearish_missed() -> None:
    pred = {"direction": "bearish"}
    res = verify_prediction(pred, actual_price=11.0, actual_change_pct=10.0)
    assert res.status == "missed"
    assert res.score == 0.0


def test_verify_prediction_neutral_dead_zone() -> None:
    pred = {"direction": "neutral"}
    res = verify_prediction(pred, actual_price=10.0, actual_change_pct=1.0)
    assert res.status == "hit"
    assert res.score == 0.5


def test_verify_prediction_neutral_outside_dead_zone() -> None:
    pred = {"direction": "neutral"}
    res = verify_prediction(pred, actual_price=10.0, actual_change_pct=5.0)
    assert res.status == "missed"
    assert res.score == 0.3
