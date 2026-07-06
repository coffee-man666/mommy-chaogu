"""组合层面回测：把一组已验证的预测当作一个组合来模拟，输出整体赚不赚钱。

之前的 :mod:`backtest.engine` / :mod:`backtest.scoring` 只看「单条预测准不准」，
本模块再上一层，回答「按这批信号操作，组合净值为多少」。

交易规则（A 股约束）:

- **bullish** → 等额资金开多，持有到期平仓，计算净收益
- **bearish** → A 股不能做空，按「空仓回避」处理，不产生交易
- **neutral** → 方向不明，不产生交易

资金分配（``position_size="equal"``）: 每个实际开仓信号分到
``initial_capital / 实际交易笔数`` 的等额资金。

净值曲线按信号 ``date`` 排序后顺序累加每笔 P&L 得到，用于计算最大回撤；
夏普比率复用 :mod:`backtest.engine` 的年化口径（无风险利率 2%，年化系数
``sqrt(252 / hold_days)``）。交易成本走 :func:`backtest.costs.apply_costs`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from mommy_chaogu.backtest.costs import apply_costs
from mommy_chaogu.backtest.scoring import score_direction

__all__ = ["PortfolioBacktester", "PortfolioResult"]

# 无风险年化利率 2%（与 backtest.engine 保持一致）
RISK_FREE_ANNUAL = 0.02
_TRADING_DAYS = 252


@dataclass
class PortfolioResult:
    """组合回测汇总结果。"""

    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    num_trades: int
    equity_curve: list[dict[str, Any]] = field(default_factory=list)


class PortfolioBacktester:
    """对一组已验证预测模拟组合操作，给出组合层面的净值 / 回撤 / 夏普。"""

    def __init__(self, default_horizon: int = 5) -> None:
        """单笔交易的默认持有天数，仅用于夏普年化系数。

        Args:
            default_horizon: 默认持有天数（默认 5，与 ``scripts/backtest_llm.py`` 对齐）
        """
        self.default_horizon = default_horizon

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def simulate(
        self,
        predictions: list[dict[str, Any]],
        initial_capital: float = 1_000_000,
        position_size: str = "equal",
    ) -> PortfolioResult:
        """对一组已验证的预测模拟组合操作。

        Args:
            predictions: 预测字典列表。每条至少需能推出方向和到期涨跌幅：

                - ``direction``: ``"bullish"`` / ``"bearish"`` / ``"neutral"``
                - 到期涨跌幅（任一）: ``change_pct``（%，已算好），
                  或 ``entry`` + ``actual`` / ``exit_price``（价格）
                - ``date``: 开仓日期（可选，用于净值曲线排序）
            initial_capital: 初始资金（元）
            position_size: 资金分配策略，目前仅支持 ``"equal"``（等权）

        Returns:
            :class:`PortfolioResult`
        """
        if position_size != "equal":
            raise ValueError(f"不支持的 position_size: {position_size!r}（目前仅支持 'equal'）")

        # 空输入边界：净值曲线只含初始点
        if not predictions:
            return PortfolioResult(
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                num_trades=0,
                equity_curve=[{"date": "", "equity": round(initial_capital, 2)}],
            )

        # 1. 只对 bullish 开多；bearish / neutral = 空仓回避
        trades = self._build_trades(predictions)

        # 没有可平仓的信号 → 全程空仓
        if not trades:
            return PortfolioResult(
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                num_trades=0,
                equity_curve=[{"date": "", "equity": round(initial_capital, 2)}],
            )

        # 2. 等权分配：每个实际交易分到等额资金
        allocated = initial_capital / len(trades)

        # 3. 按日期排序，顺序累加 P&L 构建净值曲线
        trades.sort(key=lambda t: t["date"])
        equity = initial_capital
        equity_curve: list[dict[str, Any]] = [{"date": "", "equity": round(equity, 2)}]
        net_returns: list[float] = []
        for t in trades:
            pnl = allocated * t["net_return_pct"] / 100
            equity += pnl
            equity_curve.append({"date": t["date"], "equity": round(equity, 2)})
            net_returns.append(t["net_return_pct"])

        # 4. 组合统计
        total_return_pct = (equity - initial_capital) / initial_capital * 100
        max_dd = _max_drawdown_from_curve(equity_curve)
        sharpe = _sharpe_ratio(net_returns, self.default_horizon)
        wins = sum(1 for r in net_returns if r > 0)
        win_rate = wins / len(net_returns) if net_returns else 0.0

        return PortfolioResult(
            total_return_pct=round(total_return_pct, 4),
            max_drawdown_pct=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 4),
            win_rate=round(win_rate, 4),
            num_trades=len(trades),
            equity_curve=equity_curve,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _build_trades(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """从预测列表提取实际开仓的交易记录。

        跳过：

        - 非 bullish 方向（bearish / neutral = 空仓回避）
        - 无法推出到期涨跌幅的预测（无 ``change_pct`` 且无 ``entry``/``actual``）

        每条交易记录::

            {"date": str, "gross_return_pct": float,
             "net_return_pct": float, "status": "hit"|"missed"}
        """
        trades: list[dict[str, Any]] = []
        for pred in predictions:
            direction = str(pred.get("direction", "")).strip().lower()
            if direction != "bullish":
                continue

            change_pct = _extract_change_pct(pred)
            if change_pct is None:
                continue

            net = apply_costs(change_pct, "bullish")
            # 用 score_direction 判定方向命中（与单条评分口径一致）
            status, _score = score_direction(direction, change_pct)
            trades.append(
                {
                    "date": str(pred.get("date", "")),
                    "gross_return_pct": change_pct,
                    "net_return_pct": net,
                    "status": status,
                }
            )
        return trades


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------


def _extract_change_pct(pred: dict[str, Any]) -> float | None:
    """从预测字典提取到期涨跌幅（%）。

    优先 ``change_pct``；否则用 ``entry`` 和 ``actual`` / ``exit_price`` 反推。
    """
    raw = pred.get("change_pct")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    entry = pred.get("entry")
    exit_price = pred.get("actual")
    if exit_price is None:
        exit_price = pred.get("exit_price")
    if entry and exit_price is not None and entry > 0:
        return (float(exit_price) - float(entry)) / float(entry) * 100
    return None


def _max_drawdown_from_curve(curve: list[dict[str, Any]]) -> float:
    """从净值曲线计算最大回撤（%，返回正数）。"""
    if not curve:
        return 0.0
    peak = float(curve[0]["equity"])
    max_dd = 0.0
    for point in curve:
        eq = float(point["equity"])
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return abs(max_dd) * 100


def _sharpe_ratio(returns_pct: list[float], hold_days: int) -> float:
    """年化夏普比率（与 :mod:`backtest.engine` 同口径）。"""
    n = len(returns_pct)
    if n < 2:
        return 0.0

    daily_returns = [r / 100 for r in returns_pct]
    mean_r = sum(daily_returns) / n
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (n - 1)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0

    rf_per_trade = RISK_FREE_ANNUAL * hold_days / _TRADING_DAYS
    excess = mean_r - rf_per_trade
    annualization = math.sqrt(_TRADING_DAYS / hold_days)
    return (excess / std_r) * annualization
