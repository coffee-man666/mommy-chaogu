"""回测引擎：在历史缓存数据上回放 flow_in_spike 信号规则。

流程：
1. 遍历 codes，从 money_flow_cache 读每日主力净流入
2. 从 quote_cache 取流通市值（近似，市值变动缓慢）
3. 计算 ratio = main_net / float_market_cap
4. ratio > 5bp (spike 阈值) → 记录买入信号
5. 从 bar_cache 读日 K 线收盘价，计算持有 hold_days 后的收益
6. 汇总胜率、平均收益、最大回撤、夏普比率
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.cache.store import CacheStore

# flow_in_spike 阈值 5bp = 0.0005
SPIKE_THRESHOLD = Decimal("0.0005")

# 无风险年化利率 2%
RISK_FREE_ANNUAL = 0.02
_TRADING_DAYS = 252


@dataclass
class BacktestResult:
    """回测汇总结果。"""

    total_signals: int
    winning_signals: int
    losing_signals: int
    win_rate: float
    avg_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    signals_detail: list[dict] = field(default_factory=list)
    message: str = ""


class BacktestEngine:
    """在缓存的历史数据上回放信号规则。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.cache = CacheStore(db_path)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_code_data(self, code: str, start_date: str, end_date: str) -> dict | None:
        """加载单只 code 的历史数据，返回 None 表示数据不足。"""
        # ---- 流通市值（从 quote_cache 取当前值做近似）----
        quote_entry = self.cache.get_quote(code)
        float_mcap: Decimal | None = None
        if quote_entry and quote_entry.quote.circulating_market_cap:
            float_mcap = quote_entry.quote.circulating_market_cap.amount
        if float_mcap is None or float_mcap <= 0:
            return None

        # ---- 日 K 线 ----
        bars = self.cache.get_bars(code, "1d", "forward", start_date, end_date)
        if not bars:
            return None
        bar_by_date: dict[str, dict] = {}
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
            "bar_by_date": bar_by_date,
            "flow_by_date": flow_by_date,
        }

    # ------------------------------------------------------------------
    # 信号回放
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_returns(
        bar_by_date: dict[str, dict],
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
    ) -> BacktestResult:
        """回放 flow_in_spike 信号规则。

        Args:
            codes: 要回测的股票代码列表
            start_date: 起始日期 "YYYY-MM-DD"
            end_date: 结束日期 "YYYY-MM-DD"
            hold_days: 持有天数（默认 3）

        Returns:
            BacktestResult 汇总结果
        """
        # 1. 加载所有 code 的数据
        all_data: dict[str, dict] = {}
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
            )

        # 2. 收集所有交易日（取并集）
        all_dates: set[str] = set()
        for data in all_data.values():
            all_dates.update(data["flow_by_date"].keys())
        trading_days = sorted(all_dates)

        # 3. 回放
        horizons = [1, 3, 5]
        signals_detail: list[dict] = []

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
                signals_detail.append(
                    {
                        "code": code,
                        "name": data["name"],
                        "date": date,
                        "ratio_bp": round(ratio_bp, 2),
                        "main_net_yi": float(main_net) / 100_000_000,
                        **returns,
                        "return_after_hold_pct": hold_return,
                    }
                )

        # 4. 统计
        completed = [s for s in signals_detail if s.get("return_after_hold_pct") is not None]
        winning = [s for s in completed if s["return_after_hold_pct"] > 0]
        losing = [s for s in completed if s["return_after_hold_pct"] <= 0]

        returns_pct = [s["return_after_hold_pct"] for s in completed]  # type: ignore[misc]
        total = len(signals_detail)

        if returns_pct:
            avg_return = sum(returns_pct) / len(returns_pct)
            max_dd = _max_drawdown(returns_pct)
            sharpe = _sharpe_ratio(returns_pct, hold_days)
        else:
            avg_return = 0.0
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
        )


# ----------------------------------------------------------------------
# 辅助统计函数
# ----------------------------------------------------------------------


def _max_drawdown(returns_pct: list[float]) -> float:
    """从交易收益序列计算最大回撤（%，返回正数）。"""
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        equity *= 1 + r / 100
        if equity > peak:
            peak = equity
        dd = (equity - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return abs(max_dd) * 100


def _sharpe_ratio(returns_pct: list[float], hold_days: int) -> float:
    """年化夏普比率。

    rf = 2% 年化，转换为每笔交易的无风险收益。
    """
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
    # 年化：每笔交易覆盖 hold_days 天
    annualization = math.sqrt(_TRADING_DAYS / hold_days)
    return (excess / std_r) * annualization
