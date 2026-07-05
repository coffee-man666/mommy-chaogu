"""回测引擎：回放 flow_in_spike 信号规则在历史数据上的表现。"""

from __future__ import annotations

from mommy_chaogu.backtest.costs import (
    DEFAULT_COSTS,
    TradingCosts,
    apply_costs,
    format_cost_breakdown,
)
from mommy_chaogu.backtest.engine import BacktestEngine, BacktestResult
from mommy_chaogu.backtest.portfolio import PortfolioBacktester, PortfolioResult
from mommy_chaogu.backtest.regime_analysis import (
    analyze_by_regime,
    classify_market_regime,
    compare_strategies_across_regimes,
    format_regime_report,
)
from mommy_chaogu.backtest.scoring import VerifyResult, score_direction, verify_prediction
from mommy_chaogu.backtest.walk_forward import WalkForwardResult, walk_forward_test

__all__ = [
    "DEFAULT_COSTS",
    "BacktestEngine",
    "BacktestResult",
    "PortfolioBacktester",
    "PortfolioResult",
    "TradingCosts",
    "VerifyResult",
    "WalkForwardResult",
    "analyze_by_regime",
    "apply_costs",
    "classify_market_regime",
    "compare_strategies_across_regimes",
    "format_cost_breakdown",
    "format_regime_report",
    "score_direction",
    "verify_prediction",
    "walk_forward_test",
]
