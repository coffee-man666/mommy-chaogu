"""组合回测 ``mommy_chaogu.backtest.portfolio`` 的端到端测试。"""

from __future__ import annotations

from mommy_chaogu.backtest.costs import DEFAULT_COSTS, apply_costs
from mommy_chaogu.backtest.portfolio import PortfolioBacktester, PortfolioResult

# ---------- 工具 ----------


def _bull(date: str, change_pct: float) -> dict:
    """构造一条 bullish 预测（已算好到期涨跌幅）。"""
    return {"direction": "bullish", "date": date, "change_pct": change_pct}


def _bear(date: str, change_pct: float) -> dict:
    """构造一条 bearish 预测。"""
    return {"direction": "bearish", "date": date, "change_pct": change_pct}


# ---------- 空列表边界 ----------


def test_empty_predictions_returns_no_trades() -> None:
    bt = PortfolioBacktester()
    res = bt.simulate([])
    assert res.num_trades == 0
    assert res.total_return_pct == 0.0
    assert res.win_rate == 0.0
    assert res.sharpe_ratio == 0.0
    assert res.max_drawdown_pct == 0.0
    # 净值曲线至少包含初始点
    assert len(res.equity_curve) == 1
    assert res.equity_curve[0]["equity"] == 1_000_000.0


def test_all_bearish_means_all_cash() -> None:
    """全部 bearish → 全程空仓回避，不产生交易。"""
    bt = PortfolioBacktester()
    res = bt.simulate([_bear("2026-06-01", -5.0), _bear("2026-06-02", -3.0)])
    assert res.num_trades == 0
    assert res.total_return_pct == 0.0
    # 即便 bearish 判断「正确」（跌了），也不计入交易
    assert res.win_rate == 0.0


# ---------- 全 bullish 上涨市 ----------


def test_all_bullish_in_rising_market_positive_return() -> None:
    """全 bullish 组合在上涨市应正收益。"""
    bt = PortfolioBacktester()
    preds = [
        _bull("2026-06-01", 5.0),
        _bull("2026-06-02", 3.0),
        _bull("2026-06-03", 8.0),
    ]
    res = bt.simulate(preds, initial_capital=1_000_000)

    assert res.num_trades == 3
    assert res.total_return_pct > 0
    assert res.win_rate == 1.0  # 三笔都赚钱
    # 末点净值 = 初始资金 + 总 P&L
    assert res.equity_curve[-1]["equity"] > 1_000_000.0


def test_all_bullish_total_return_matches_formula() -> None:
    """总收益 = 平均净收益（等权）。"""
    bt = PortfolioBacktester()
    changes = [5.0, 3.0, 8.0]
    preds = [_bull(f"2026-06-0{i + 1}", c) for i, c in enumerate(changes)]
    res = bt.simulate(preds, initial_capital=1_000_000)

    expected_nets = [apply_costs(c, "bullish") for c in changes]
    expected_total = sum(expected_nets) / len(expected_nets)
    assert res.total_return_pct == round(expected_total, 4)


# ---------- 混合 bullish / bearish ----------


def test_mixed_portfolio_only_bullish_traded() -> None:
    """混合组合只交易 bullish，bearish 不计入交易笔数。"""
    bt = PortfolioBacktester()
    preds = [
        _bull("2026-06-01", 4.0),
        _bear("2026-06-02", -6.0),  # bearish 回避，即便跌也不做空
        _bull("2026-06-03", -2.0),  # bullish 但实际亏
    ]
    res = bt.simulate(preds)

    assert res.num_trades == 2  # 只有两条 bullish
    # 一赚一亏 → 胜率 0.5
    assert res.win_rate == 0.5


def test_mixed_portfolio_bearish_does_not_dilute_capital() -> None:
    """bearish 不占用资金：两条 bullish 各分到一半初始资金。"""
    bt = PortfolioBacktester()
    # 两条 bullish 各 +10%，bearish 不参与 → 总收益约 +10% - 成本
    preds = [
        _bull("2026-06-01", 10.0),
        _bull("2026-06-02", 10.0),
        _bear("2026-06-03", -50.0),  # 即便暴跌也不影响（不做空）
    ]
    res = bt.simulate(preds, initial_capital=1_000_000)
    expected_net = apply_costs(10.0, "bullish")
    assert res.total_return_pct == round(expected_net, 4)


# ---------- 净值曲线 ----------


def test_equity_curve_length_and_monotonicity_in_rising_market() -> None:
    """上涨市净值曲线应严格递增，长度 = 1 + 交易笔数。"""
    bt = PortfolioBacktester()
    preds = [_bull("2026-06-01", 2.0), _bull("2026-06-02", 3.0)]
    res = bt.simulate(preds)

    assert len(res.equity_curve) == 1 + 2  # 初始点 + 2 笔
    equities = [p["equity"] for p in res.equity_curve]
    assert equities[0] == 1_000_000.0
    # 上涨市 → 递增
    assert equities[0] < equities[1] < equities[2]


def test_equity_curve_sorted_by_date() -> None:
    """净值曲线按日期排序（输入乱序也应排好）。"""
    bt = PortfolioBacktester()
    preds = [
        _bull("2026-06-03", 1.0),
        _bull("2026-06-01", 5.0),
        _bull("2026-06-02", 3.0),
    ]
    res = bt.simulate(preds)
    dates = [p["date"] for p in res.equity_curve[1:]]  # 去掉初始空日期点
    assert dates == ["2026-06-01", "2026-06-02", "2026-06-03"]


def test_max_drawdown_when_losing_trade_in_middle() -> None:
    """中间一笔亏损造成回撤。"""
    bt = PortfolioBacktester()
    # +5%, -10%, +5% → 中间净值最低，产生回撤
    preds = [
        _bull("2026-06-01", 5.0),
        _bull("2026-06-02", -10.0),
        _bull("2026-06-03", 5.0),
    ]
    res = bt.simulate(preds, initial_capital=1_000_000)
    assert res.max_drawdown_pct > 0


# ---------- 成本扣减 ----------


def test_cost_deduction_makes_zero_return_negative() -> None:
    """0% 毛收益扣成本后净值应为负。"""
    bt = PortfolioBacktester()
    preds = [_bull("2026-06-01", 0.0), _bull("2026-06-02", 0.0)]
    res = bt.simulate(preds, initial_capital=1_000_000)

    assert res.total_return_pct < 0
    expected = -DEFAULT_COSTS.round_trip_cost_pct()
    assert res.total_return_pct == round(expected, 4)
    assert res.equity_curve[-1]["equity"] < 1_000_000.0


def test_net_return_lower_than_gross() -> None:
    """扣成本后总收益严格低于毛收益等权基准。"""
    bt = PortfolioBacktester()
    preds = [_bull("2026-06-01", 4.0), _bull("2026-06-02", 6.0)]
    res = bt.simulate(preds)

    gross_avg = (4.0 + 6.0) / 2
    assert res.total_return_pct < gross_avg


# ---------- 从价格反推 change_pct ----------


def test_change_pct_inferred_from_entry_and_actual() -> None:
    """没有 change_pct 时，用 entry/actual 反推。"""
    bt = PortfolioBacktester()
    # 10 → 11 = +10%
    preds = [{"direction": "bullish", "date": "2026-06-01", "entry": 10.0, "actual": 11.0}]
    res = bt.simulate(preds, initial_capital=1_000_000)
    expected = apply_costs(10.0, "bullish")
    assert res.num_trades == 1
    assert res.total_return_pct == round(expected, 4)


def test_missing_change_pct_skipped() -> None:
    """无法推出 change_pct 的 bullish 预测被跳过。"""
    bt = PortfolioBacktester()
    preds = [
        {"direction": "bullish", "date": "2026-06-01"},  # 无价格信息
        _bull("2026-06-02", 4.0),
    ]
    res = bt.simulate(preds)
    assert res.num_trades == 1


# ---------- 自定义初始资金 ----------


def test_custom_initial_capital() -> None:
    """自定义初始资金不影响收益率（只影响净值规模）。"""
    bt = PortfolioBacktester()
    preds = [_bull("2026-06-01", 5.0), _bull("2026-06-02", 5.0)]
    res_a = bt.simulate(preds, initial_capital=1_000_000)
    res_b = bt.simulate(preds, initial_capital=500_000)

    assert res_a.total_return_pct == res_b.total_return_pct
    assert res_a.equity_curve[-1]["equity"] == 2 * res_b.equity_curve[-1]["equity"]


def test_return_type_is_portfolio_result() -> None:
    bt = PortfolioBacktester()
    res = bt.simulate([_bull("2026-06-01", 1.0)])
    assert isinstance(res, PortfolioResult)


def test_invalid_position_size_raises() -> None:
    import pytest

    bt = PortfolioBacktester()
    with pytest.raises(ValueError):
        bt.simulate([_bull("2026-06-01", 1.0)], position_size="momentum")
