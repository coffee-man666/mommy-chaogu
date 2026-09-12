"""组合分析：行业集中度、相关性矩阵、风险指标。

通过 PortfolioStore 读取持仓，结合 MarketDataAdapter 获取实时行情和板块信息，
结合 CacheStore 读取历史日 K 线计算收益率相关性、最大回撤、波动率、夏普比率。
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mommy_chaogu.cache.store import CacheStore
    from mommy_chaogu.market_data.adapter import MarketDataAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore


# 无风险年利率（2%）
_RISK_FREE_ANNUAL = 0.02
# 年交易日
_TRADING_DAYS = 252


class PortfolioAnalyzer:
    """组合风险/结构分析器。

    用法::

        analyzer = PortfolioAnalyzer(store, adapter, cache_store)
        sectors = analyzer.sector_concentration()
        corr = analyzer.correlation_matrix(days=30)
        risk = analyzer.risk_metrics(days=30)
    """

    def __init__(
        self,
        store: PortfolioStore,
        adapter: MarketDataAdapter | None = None,
        cache_store: CacheStore | None = None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.cache_store = cache_store

    # ---------- 内部辅助 ----------

    def _position_codes(self) -> list[str]:
        """返回持仓股数 > 0 的去重 code 列表。"""
        positions = self.store.list_positions()
        codes: list[str] = []
        seen: set[str] = set()
        for pos in positions:
            if pos.shares > 0 and pos.code not in seen:
                codes.append(pos.code)
                seen.add(pos.code)
        return codes

    def _market_values(self) -> dict[str, Decimal]:
        """计算每个 code 的市值（price × 累计 shares），无报价的跳过。"""
        if self.adapter is None:
            return {}
        codes = self._position_codes()
        if not codes:
            return {}
        quotes = self.adapter.get_quotes(codes)
        prices: dict[str, Decimal] = {q.code: q.price for q in quotes}

        result: dict[str, Decimal] = {}
        for pos in self.store.list_positions():
            if pos.shares <= 0:
                continue
            price = prices.get(pos.code)
            if price is None:
                continue
            result[pos.code] = result.get(pos.code, Decimal("0")) + price * pos.shares
        return result

    def _dated_daily_returns_from_cache(self, code: str, days: int) -> dict[str, float]:
        """从 bar_cache 读取日 K 线，返回 {日期: 日收益率}。

        日期键为收益率发生的那一天。跨 code 对齐**必须**按日期交集做，
        不能按数组索引——停牌 / 数据缺口会让位置序列错位。
        """
        if self.cache_store is None:
            return {}
        bars = self.cache_store.get_bars(code, "1d", "forward")
        if not bars:
            return {}
        # 取最近 days+1 根 K 线（生成最多 days 个收益率）
        recent = bars[-(days + 1) :]
        dated: dict[str, float] = {}
        prev_close: float | None = None
        for bar in recent:
            close = float(Decimal(str(bar["close"])))
            date = str(bar["timestamp"])[:10]
            if prev_close is not None and prev_close > 0:
                dated[date] = (close - prev_close) / prev_close
            prev_close = close
        return dated

    @staticmethod
    def _pearson(x: list[float], y: list[float]) -> float:
        """计算 Pearson 相关系数。

        调用方必须先按日期对齐出等长序列（见
        :meth:`_dated_daily_returns_from_cache` 的 docstring）。
        """
        n = min(len(x), len(y))
        if n < 2:
            return 0.0
        x = x[:n]
        y = y[:n]
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)
        denom = math.sqrt(var_x * var_y)
        if denom == 0:
            return 0.0
        return cov / denom

    @staticmethod
    def _max_drawdown(returns: list[float]) -> float:
        """从日收益率序列计算最大回撤比例（0~1）。"""
        cumulative = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in returns:
            cumulative *= 1 + r
            if cumulative > peak:
                peak = cumulative
            dd = (peak - cumulative) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    # ---------- 公共 API ----------

    def sector_concentration(self) -> dict[str, float]:
        """返回 {sector_name: pct_of_total_market_value}（百分比）。

        通过 adapter.get_belonging_boards(code) 获取每只持仓所属板块，
        取第一个板块名作为行业分类，按市值加权汇总。
        """
        if self.adapter is None:
            return {}

        market_values = self._market_values()
        if not market_values:
            return {}

        total_mv = sum(market_values.values(), Decimal("0"))
        if total_mv <= 0:
            return {}

        result: dict[str, float] = {}
        for code, mv in market_values.items():
            boards = self.adapter.get_belonging_boards(code)
            sector = boards[0].name if boards else "未分类"
            pct = float(mv / total_mv * Decimal("100"))
            result[sector] = result.get(sector, 0.0) + pct
        return result

    def correlation_matrix(self, days: int = 30) -> dict[str, dict[str, float]]:
        """返回 {code1: {code2: correlation}} 基于 bar_cache 日收益率。

        使用 Pearson 相关系数，**按日期交集对齐**两只股票的收益率序列
        （停牌 / 数据缺口的日子不参与）。对角线为 1.0。
        """
        codes = self._position_codes()
        if len(codes) < 2:
            return {}

        returns_by_code: dict[str, dict[str, float]] = {}
        for code in codes:
            rets = self._dated_daily_returns_from_cache(code, days)
            if len(rets) >= 2:
                returns_by_code[code] = rets

        result: dict[str, dict[str, float]] = {}
        for c1, r1 in returns_by_code.items():
            row: dict[str, float] = {}
            for c2, r2 in returns_by_code.items():
                if c1 == c2:
                    row[c2] = 1.0
                else:
                    common = sorted(set(r1) & set(r2))
                    row[c2] = round(
                        self._pearson([r1[d] for d in common], [r2[d] for d in common]), 4
                    )
            result[c1] = row
        return result

    def risk_metrics(self, days: int = 30) -> dict[str, float]:
        """返回 {max_drawdown_pct, volatility_pct, sharpe_ratio}。

        基于组合整体的历史日收益率（按各持仓市值加权），计算：
        - max_drawdown_pct: 最大回撤百分比
        - volatility_pct: 年化波动率百分比
        - sharpe_ratio: 年化夏普比率（无风险利率 2%）
        """
        default = {"max_drawdown_pct": 0.0, "volatility_pct": 0.0, "sharpe_ratio": 0.0}

        codes = self._position_codes()
        if not codes:
            return default

        market_values = self._market_values()

        # 读取每个 code 的日收益率
        all_returns: dict[str, dict[str, float]] = {}
        for code in codes:
            rets = self._dated_daily_returns_from_cache(code, days)
            if rets:
                all_returns[code] = rets
        if not all_returns:
            return default

        # 按市值计算权重
        total_mv = sum(market_values.values(), Decimal("0"))
        weights: dict[str, float] = {}
        if total_mv > 0:
            for code in all_returns:
                mv = market_values.get(code, Decimal("0"))
                weights[code] = float(mv / total_mv)
        else:
            # 无行情时均权
            n = len(all_returns)
            for code in all_returns:
                weights[code] = 1.0 / n

        # 组合日收益率：按日期对齐，某 code 当日缺收益（停牌 / 数据缺口）
        # 按 0 处理——停牌期间价格冻结，收益即 0
        all_dates = sorted(set().union(*[set(r) for r in all_returns.values()]))
        portfolio_returns: list[float] = [
            sum(weights[code] * all_returns[code].get(d, 0.0) for code in all_returns)
            for d in all_dates
        ]

        if not portfolio_returns:
            return default

        # 最大回撤
        max_dd = self._max_drawdown(portfolio_returns)

        # 波动率（年化）
        mean_ret = sum(portfolio_returns) / len(portfolio_returns)
        variance = sum((r - mean_ret) ** 2 for r in portfolio_returns) / len(portfolio_returns)
        daily_vol = math.sqrt(variance)
        annual_vol = daily_vol * math.sqrt(_TRADING_DAYS)

        # 夏普比率（年化）
        rf_daily = (1 + _RISK_FREE_ANNUAL) ** (1 / _TRADING_DAYS) - 1
        excess = [r - rf_daily for r in portfolio_returns]
        mean_excess = sum(excess) / len(excess)
        sharpe = (mean_excess * _TRADING_DAYS) / annual_vol if annual_vol > 0 else 0.0

        return {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "volatility_pct": round(annual_vol * 100, 2),
            "sharpe_ratio": round(sharpe, 4),
        }
