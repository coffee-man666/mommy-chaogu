"""回测引擎：在历史缓存数据上回放 flow_in_spike 信号规则。

流程：
1. 遍历 codes，从 money_flow_cache 读每日主力净流入
2. 从 quote_cache 取流通市值（近似，市值变动缓慢；见 :attr:`BacktestResult.mcap_as_of`）
3. 计算 ratio = main_net / float_market_cap
4. ratio > 5bp (spike 阈值) → 记录买入信号
5. 从 bar_cache 读日 K 线收盘价，计算持有 hold_days 后的收益
6. 每笔信号扣减一次往返交易成本（:func:`backtest.costs.apply_costs`），
   胜率 / 平均收益 / 回撤 / 夏普全部按 **净收益** 口径统计，毛收益保留在
   ``avg_gross_return_pct`` 与每条信号的 ``gross_return_after_hold_pct``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.backtest.costs import (
    DEFAULT_COSTS,
    TradingCosts,
    apply_costs,
    format_cost_breakdown,
)
from mommy_chaogu.backtest.metrics import max_drawdown_pct, sharpe_ratio
from mommy_chaogu.cache.store import CacheStore

# flow_in_spike 阈值 5bp = 0.0005
SPIKE_THRESHOLD = Decimal("0.0005")

NO_COSTS_LABEL = "未扣减交易成本"


@dataclass
class BacktestResult:
    """回测汇总结果。

    Attributes:
        avg_return_pct: 持有期 **净** 平均收益（扣往返成本后）。
        avg_gross_return_pct: 持有期毛平均收益（不扣成本），用于对照。
        cost_model: 成本模型明细（或未扣成本说明），给报告 / API 展示。
    """

    total_signals: int
    winning_signals: int
    losing_signals: int
    win_rate: float
    avg_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    signals_detail: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    avg_gross_return_pct: float = 0.0
    cost_model: str = ""
    #: 市值取自哪一天的报价缓存（多 code 取最旧，保守）
    mcap_as_of: str = ""
    #: 口径警示（市值前视近似等），调用方应展示给用户
    caveats: list[str] = field(default_factory=list)


class BacktestEngine:
    """在缓存的历史数据上回放信号规则。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.cache = CacheStore(db_path)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_code_data(self, code: str, start_date: str, end_date: str) -> dict[str, Any] | None:
        """加载单只 code 的历史数据，返回 None 表示数据不足。"""
        # ---- 流通市值（从 quote_cache 取当前值做近似）----
        quote_entry = self.cache.get_quote(code)
        float_mcap: Decimal | None = None
        mcap_as_of: Any = None
        if quote_entry and quote_entry.quote.circulating_market_cap:
            float_mcap = quote_entry.quote.circulating_market_cap.amount
            mcap_as_of = quote_entry.fetched_at
        if float_mcap is None or float_mcap <= 0:
            return None

        # ---- 日 K 线 ----
        bars = self.cache.get_bars(code, "1d", "forward", start_date, end_date)
        if not bars:
            return None
        bar_by_date: dict[str, dict[str, Any]] = {}
        for b in bars:
            ts = b["timestamp"]
            date = ts[:10]  # "2026-06-01T..." → "2026-06-01"
            if start_date <= date <= end_date:
                bar_by_date[date] = b

        # ---- 历史资金流 ----
        flows = self.cache.get_money_flow_history(code, start_date=start_date)
        if not flows:
            return None
        flow_by_date: dict[str, Decimal] = {}
        for entry in flows:
            date = entry["__trade_date__"]
            if date < start_date or date > end_date:
                continue
            flow_list = entry.get("flows") or []
            if not flow_list:
                continue
            main_net_raw = flow_list[0].get("main_net", {})
            if isinstance(main_net_raw, dict):
                amount = main_net_raw.get("amount", "0")
            else:
                amount = str(main_net_raw)
            flow_by_date[date] = Decimal(str(amount))

        return {
            "code": code,
            "name": bars[0].get("name", code),
            "float_mcap": float_mcap,
            "mcap_as_of": mcap_as_of,
            "bar_by_date": bar_by_date,
            "flow_by_date": flow_by_date,
        }

    # ------------------------------------------------------------------
    # 信号回放
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_returns(
        bar_by_date: dict[str, dict[str, Any]],
        sorted_dates: list[str],
        signal_date: str,
        entry_close: Decimal,
        horizons: list[int],
    ) -> dict[str, float | None]:
        """计算不同持有天数的收益（%）。"""
        try:
            idx = sorted_dates.index(signal_date)
        except ValueError:
            return {f"return_after_{h}d": None for h in horizons}

        result: dict[str, float | None] = {}
        for h in horizons:
            exit_idx = idx + h
            if exit_idx < len(sorted_dates):
                exit_bar = bar_by_date[sorted_dates[exit_idx]]
                exit_close = Decimal(str(exit_bar["close"]))
                if entry_close > 0:
                    ret = float((exit_close - entry_close) / entry_close * 100)
                else:
                    ret = None
            else:
                ret = None
            result[f"return_after_{h}d"] = ret
        return result

    def run(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        hold_days: int = 3,
        costs: TradingCosts | None = DEFAULT_COSTS,
    ) -> BacktestResult:
        """回放 flow_in_spike 信号规则。

        Args:
            codes: 要回测的股票代码列表
            start_date: 起始日期 "YYYY-MM-DD"
            end_date: 结束日期 "YYYY-MM-DD"
            hold_days: 持有天数（默认 3）
            costs: 交易成本参数；默认 :data:`backtest.costs.DEFAULT_COSTS`，
                传 ``None`` 完全不扣成本（毛收益口径）

        Returns:
            BacktestResult 汇总结果（胜率 / 平均收益按扣成本后的净收益统计）
        """
        cost_model = format_cost_breakdown(costs) if costs is not None else NO_COSTS_LABEL

        # 1. 加载所有 code 的数据
        all_data: dict[str, dict[str, Any]] = {}
        for code in codes:
            data = self._load_code_data(code, start_date, end_date)
            if data is not None:
                all_data[code] = data

        if not all_data:
            return BacktestResult(
                total_signals=0,
                winning_signals=0,
                losing_signals=0,
                win_rate=0.0,
                avg_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                signals_detail=[],
                message="无缓存数据，请先 mommy-flows pull 拉取历史数据",
                cost_model=cost_model,
            )

        # 2. 收集所有交易日（取并集），并确定市值时点与口径警示
        all_dates: set[str] = set()
        for data in all_data.values():
            all_dates.update(data["flow_by_date"].keys())
        mcap_dates = [
            data["mcap_as_of"]
            for data in all_data.values()
            if data.get("mcap_as_of") is not None
        ]
        mcap_as_of = min(mcap_dates).strftime("%Y-%m-%d") if mcap_dates else ""
        caveats: list[str] = []
        if mcap_as_of:
            caveats.append(
                f"流通市值取自 {mcap_as_of} 的报价缓存：ratio=当日主力净流入÷当前市值，"
                "历史区间内市值变动会使 ratio 存在前视近似（无历史市值数据）"
            )
        trading_days = sorted(all_dates)

        # 3. 回放
        horizons = [1, 3, 5]
        signals_detail: list[dict[str, Any]] = []

        for date in trading_days:
            for code, data in all_data.items():
                if date not in data["flow_by_date"]:
                    continue
                main_net = data["flow_by_date"][date]
                ratio = main_net / data["float_mcap"]
                if ratio <= SPIKE_THRESHOLD:
                    continue

                # 信号触发 — 需要当天有 K 线
                entry_bar = data["bar_by_date"].get(date)
                if entry_bar is None:
                    continue
                entry_close = Decimal(str(entry_bar["close"]))

                sorted_dates = sorted(data["bar_by_date"].keys())
                returns = self._compute_returns(
                    data["bar_by_date"], sorted_dates, date, entry_close, horizons
                )

                hold_key = f"return_after_{hold_days}d"
                hold_return = returns.get(hold_key)
                if hold_return is None and hold_days in horizons:
                    hold_return = returns.get(f"return_after_{hold_days}d")
                if hold_return is None and hold_days not in horizons:
                    # 动态计算 hold_days 收益
                    try:
                        idx = sorted_dates.index(date)
                        exit_idx = idx + hold_days
                        if exit_idx < len(sorted_dates):
                            exit_close = Decimal(
                                str(data["bar_by_date"][sorted_dates[exit_idx]]["close"])
                            )
                            hold_return = float((exit_close - entry_close) / entry_close * 100)
                    except (ValueError, KeyError):
                        pass

                ratio_bp = float(ratio) * 10_000
                # 扣减一次往返成本得到净收益；毛收益保留供对照
                net_hold = (
                    apply_costs(hold_return, "bullish", costs)
                    if hold_return is not None and costs is not None
                    else hold_return
                )
                signals_detail.append(
                    {
                        "code": code,
                        "name": data["name"],
                        "date": date,
                        "ratio_bp": round(ratio_bp, 2),
                        "main_net_yi": float(main_net) / 100_000_000,
                        **returns,
                        "gross_return_after_hold_pct": hold_return,
                        "return_after_hold_pct": net_hold,
                    }
                )

        # 4. 统计（净收益口径；毛收益单列）
        completed = [s for s in signals_detail if s.get("return_after_hold_pct") is not None]
        winning = [s for s in completed if s["return_after_hold_pct"] > 0]
        losing = [s for s in completed if s["return_after_hold_pct"] <= 0]

        returns_pct = [s["return_after_hold_pct"] for s in completed]
        gross_returns_pct = [
            s["gross_return_after_hold_pct"]
            for s in completed
            if s.get("gross_return_after_hold_pct") is not None
        ]
        total = len(signals_detail)

        if returns_pct:
            avg_return = sum(returns_pct) / len(returns_pct)
            avg_gross_return = sum(gross_returns_pct) / len(gross_returns_pct)
            max_dd = max_drawdown_pct(returns_pct)
            sharpe = sharpe_ratio(returns_pct, hold_days)
        else:
            avg_return = 0.0
            avg_gross_return = 0.0
            max_dd = 0.0
            sharpe = 0.0

        return BacktestResult(
            total_signals=total,
            winning_signals=len(winning),
            losing_signals=len(losing),
            win_rate=len(winning) / total if total > 0 else 0.0,
            avg_return_pct=round(avg_return, 4),
            max_drawdown_pct=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 4),
            signals_detail=signals_detail,
            avg_gross_return_pct=round(avg_gross_return, 4),
            cost_model=cost_model,
            mcap_as_of=mcap_as_of,
            caveats=caveats,
        )


# ----------------------------------------------------------------------
# 辅助统计：见 backtest.metrics（单一真相源）
# ----------------------------------------------------------------------
