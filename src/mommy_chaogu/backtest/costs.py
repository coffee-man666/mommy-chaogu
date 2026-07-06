"""A 股交易成本模型：给回测净收益扣减真实成本。

A 股与美股不同，有印花税、过户费等独有费用。回测里忽略这些会把噪声当 alpha。
本模块提供一份保守的双边成本参数和一个 :func:`apply_costs` 入口。

参数来源（保守近似，2024-2026 常规水平）:

- 佣金: 0.0255%（万 2.5 + 过户费兜底，双边）
- 印花税: 0.05%（仅卖出）
- 过户费: 0.02%（双边，沪市）
- 滑点: 0.1%（单边，近似）
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_COSTS", "TradingCosts", "apply_costs", "format_cost_breakdown"]


@dataclass(frozen=True, slots=True)
class TradingCosts:
    """A 股交易成本参数（单位：百分比，``0.0255`` 即 0.0255%）。"""

    commission_pct: float = 0.0255  # 佣金，双边
    stamp_duty_pct: float = 0.05  # 印花税，仅卖出
    transfer_fee_pct: float = 0.02  # 过户费，双边（沪市）
    slippage_pct: float = 0.1  # 滑点，单边

    def round_trip_cost_pct(self) -> float:
        """一次开仓+平仓的总成本（%）。

        简化为 ``佣金*2 + 过户费*2 + 印花税 + 滑点*2``，≈ 0.341%。
        """
        return (
            self.commission_pct * 2
            + self.transfer_fee_pct * 2
            + self.stamp_duty_pct
            + self.slippage_pct * 2
        )


DEFAULT_COSTS = TradingCosts()


def apply_costs(
    gross_return_pct: float,
    direction: str,
    costs: TradingCosts | None = None,
) -> float:
    """从毛收益中扣减交易成本，返回净收益（%）。

    Args:
        gross_return_pct: 沿预测方向的 **毛收益**（%）。bullish 时直接用涨跌幅；
            bearish 时调用方应传入 ``-change_pct``（跌=赚）；neutral 传入涨跌幅绝对值。
        direction: ``"bullish"`` / ``"bearish"`` / ``"neutral"``
        costs: 成本参数，默认 :data:`DEFAULT_COSTS`

    Returns:
        扣减双边成本后的净收益（%）。一次完整交易（开仓+平仓）扣一次往返成本。

    .. note::
        当前简化模型对所有方向采用相同的往返成本（≈ 0.341%）。bearish 的做空
        成本（融券利息）暂未单列，保守地按与多头相同处理。
    """
    c = costs if costs is not None else DEFAULT_COSTS
    # direction 当前不改变成本结构，但保留参数位以备未来做空利息分项建模
    _ = direction
    return gross_return_pct - c.round_trip_cost_pct()


def format_cost_breakdown(costs: TradingCosts | None = None) -> str:
    """格式化成本明细为多行字符串（给回测报告用）。"""
    c = costs if costs is not None else DEFAULT_COSTS
    lines = [
        "交易成本模型（每笔往返）:",
        f"  佣金      {c.commission_pct * 2:.4f}%  (双边 {c.commission_pct:.4f}% × 2)",
        f"  印花税    {c.stamp_duty_pct:.4f}%  (仅卖出)",
        f"  过户费    {c.transfer_fee_pct * 2:.4f}%  (双边 {c.transfer_fee_pct:.4f}% × 2)",
        f"  滑点      {c.slippage_pct * 2:.4f}%  (单边 {c.slippage_pct:.4f}% × 2)",
        f"  合计      {c.round_trip_cost_pct():.4f}%",
    ]
    return "\n".join(lines)
