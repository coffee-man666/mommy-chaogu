"""自选与持仓工具：自选股、持仓列表、组合分析。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict, cast

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json


class _PortfolioSummary(TypedDict):
    """PortfolioStore.summary() 返回结构的窄化契约（见其 docstring）。"""

    positions: list[dict[str, Any]]
    total_cost: Decimal
    total_market_value: Decimal | None
    total_unrealized_pnl: Decimal | None
    total_unrealized_pnl_pct: Decimal | None
    n_positions: int


DEFS: list[ToolDef] = [
    ToolDef(
        name="get_watchlist",
        description="获取用户的自选股列表。",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="get_portfolio",
        description="获取用户持仓明细（含成本、盈亏）。需要先有行情数据来计算盈亏。",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="get_portfolio_analysis",
        description="分析持仓的行业集中度、相关性矩阵、风险指标（最大回撤/波动率/夏普比率）",
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "分析窗口天数，默认 30",
                    "default": 30,
                }
            },
        },
    ),
]


def _handle_get_watchlist(ctx: ToolContext, _args: dict[str, Any]) -> str:
    if ctx.watchlist_store is None:
        return _json({"error": "自选股未配置"})
    entries = ctx.watchlist_store.list_entries()
    return _json(
        [
            {
                "code": e.code,
                "name": e.name or "—",
                "group": e.group.name,
                "note": e.note or "",
            }
            for e in entries
        ]
    )


def _handle_get_portfolio(ctx: ToolContext, _args: dict[str, Any]) -> str:
    if ctx.portfolio_store is None:
        return _json({"error": "持仓未配置"})
    positions = ctx.portfolio_store.list_positions()
    if not positions:
        return _json({"positions": [], "message": "暂无持仓"})

    # 拉当前报价来算盈亏
    codes = list({p.code for p in positions if p.shares > 0})
    current_prices: dict[str, Decimal] = {}
    if codes:
        quotes = ctx.adapter.get_quotes(codes)
        for q in quotes:
            current_prices[q.code] = q.price

    summary = cast(_PortfolioSummary, ctx.portfolio_store.summary(current_prices))

    result_positions = []
    for item in summary["positions"]:
        pos = item["position"]
        result_positions.append(
            {
                "code": pos.code,
                "name": pos.name or "—",
                "shares": int(item["shares"]),
                "avg_cost": float(item["avg_cost"]),
                "current_price": float(item["current_price"]) if item["current_price"] else None,
                "market_value": float(item["market_value"]) if item["market_value"] else None,
                "total_cost": float(item["total_cost"]),
                "unrealized_pnl": float(item["unrealized_pnl"]) if item["unrealized_pnl"] else None,
                "unrealized_pnl_pct": (
                    float(item["unrealized_pnl_pct"]) if item["unrealized_pnl_pct"] else None
                ),
            }
        )

    return _json(
        {
            "positions": result_positions,
            "total_cost": float(summary["total_cost"]),
            "total_market_value": (
                float(summary["total_market_value"]) if summary["total_market_value"] else None
            ),
            "total_unrealized_pnl": (
                float(summary["total_unrealized_pnl"]) if summary["total_unrealized_pnl"] else None
            ),
            "total_unrealized_pnl_pct": (
                float(summary["total_unrealized_pnl_pct"])
                if summary["total_unrealized_pnl_pct"]
                else None
            ),
            "n_positions": int(summary["n_positions"]),
        }
    )


def _handle_get_portfolio_analysis(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.portfolio_store is None:
        return _json({"error": "持仓未配置"})
    days = args.get("days", 30)

    from mommy_chaogu.cache.store import CacheStore
    from mommy_chaogu.portfolio.analysis import PortfolioAnalyzer

    cache_store: CacheStore | None = None
    if ctx.db_path is not None:
        cache_store = CacheStore(ctx.db_path)

    analyzer = PortfolioAnalyzer(
        store=ctx.portfolio_store,
        adapter=ctx.adapter,
        cache_store=cache_store,
    )

    risk = analyzer.risk_metrics(days=days)
    sectors = analyzer.sector_concentration()
    correlation = analyzer.correlation_matrix(days=days)

    return _json(
        {
            "risk_metrics": risk,
            "sector_concentration": sectors,
            "correlation_matrix": correlation,
            "days": days,
        }
    )


HANDLERS: dict[str, ToolHandler] = {
    "get_watchlist": _handle_get_watchlist,
    "get_portfolio": _handle_get_portfolio,
    "get_portfolio_analysis": _handle_get_portfolio_analysis,
}
