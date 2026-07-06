"""A 股交易成本模型 ``mommy_chaogu.backtest.costs`` 的测试。"""

from __future__ import annotations

from mommy_chaogu.backtest.costs import (
    DEFAULT_COSTS,
    TradingCosts,
    apply_costs,
    format_cost_breakdown,
)

# ---------- 成本参数 ----------


def test_default_cost_params() -> None:
    assert DEFAULT_COSTS.commission_pct == 0.0255
    assert DEFAULT_COSTS.stamp_duty_pct == 0.05
    assert DEFAULT_COSTS.transfer_fee_pct == 0.02
    assert DEFAULT_COSTS.slippage_pct == 0.1


def test_round_trip_cost_matches_formula() -> None:
    # 佣金*2 + 过户费*2 + 印花税 + 滑点*2
    expected = 0.0255 * 2 + 0.02 * 2 + 0.05 + 0.1 * 2
    assert DEFAULT_COSTS.round_trip_cost_pct() == expected


def test_round_trip_cost_about_034pct() -> None:
    """往返成本 ≈ 0.34%（在合理区间内）。"""
    c = DEFAULT_COSTS.round_trip_cost_pct()
    assert 0.33 <= c <= 0.35


def test_trading_costs_is_frozen() -> None:
    tc = TradingCosts()
    # frozen dataclass 不可变
    try:
        tc.commission_pct = 1.0  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("TradingCosts 应为 frozen")


# ---------- apply_costs ----------


def test_apply_costs_bullish() -> None:
    # 大涨 5%，扣往返成本后约 4.66%
    net = apply_costs(5.0, "bullish")
    assert net == 5.0 - DEFAULT_COSTS.round_trip_cost_pct()
    assert net > 0


def test_apply_costs_bearish() -> None:
    # bearish 毛收益（跌=赚）4%，扣成本后约 3.66%
    net = apply_costs(4.0, "bearish")
    assert net == 4.0 - DEFAULT_COSTS.round_trip_cost_pct()
    assert net > 0


def test_apply_costs_zero_return_is_negative() -> None:
    """0% 毛收益扣成本后为负。"""
    for d in ("bullish", "bearish", "neutral"):
        net = apply_costs(0.0, d)
        assert net < 0, f"{d} 方向 0% 收益扣成本后应 < 0，得到 {net}"


def test_apply_costs_large_gain_still_positive() -> None:
    """大涨时仍然正收益。"""
    net = apply_costs(20.0, "bullish")
    assert net > 0
    assert net == 20.0 - DEFAULT_COSTS.round_trip_cost_pct()


def test_apply_costs_directions_equal_under_simplified_model() -> None:
    """简化模型下三个方向扣相同往返成本。"""
    cost = DEFAULT_COSTS.round_trip_cost_pct()
    for d in ("bullish", "bearish", "neutral"):
        assert apply_costs(3.0, d) == 3.0 - cost


def test_apply_costs_custom_costs() -> None:
    custom = TradingCosts(
        commission_pct=0.01,
        stamp_duty_pct=0.05,
        transfer_fee_pct=0.0,
        slippage_pct=0.0,
    )
    expected_total = 0.01 * 2 + 0.0 * 2 + 0.05 + 0.0 * 2
    assert apply_costs(2.0, "bullish", costs=custom) == 2.0 - expected_total


# ---------- format_cost_breakdown ----------


def test_format_cost_breakdown_contains_lines() -> None:
    s = format_cost_breakdown()
    assert "佣金" in s
    assert "印花税" in s
    assert "过户费" in s
    assert "滑点" in s
    assert "合计" in s
    # 合计行应展示往返总成本
    total = DEFAULT_COSTS.round_trip_cost_pct()
    assert f"{total:.4f}%" in s
