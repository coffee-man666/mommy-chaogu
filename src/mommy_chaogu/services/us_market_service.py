"""美股大盘概览聚合服务（REPL 工作流 / Web / TUI 共用）。

把三大指数 + VIX + 10Y 美债利率的查询聚合成统一结构，
各前端薄封装调用，避免重复实现同一组查询。
"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import Quote

# (代码, 展示名)——Yahoo 约定的 ^ 前缀指数；Massive 不提供这些数据，fallback 链自动落到 Yahoo
US_MARKET_BRIEF: tuple[tuple[str, str], ...] = (
    ("^GSPC", "标普500"),
    ("^IXIC", "纳斯达克综合"),
    ("^DJI", "道琼斯"),
    ("^VIX", "VIX 恐慌指数"),
    ("^TNX", "10Y 美债利率"),
)


def fetch_us_market_brief(adapter: MarketDataAdapter) -> list[dict[str, Any]]:
    """拉取美股大盘概览（三大指数 + VIX + 10Y 利率）。

    返回 dict 列表（金额保留 Decimal，失败项跳过）：
    code / name（中文展示名）/ price / change_pct / change / open / high / low /
    prev_close / volume / timestamp。
    """
    out: list[dict[str, Any]] = []
    for code, label in US_MARKET_BRIEF:
        quote = adapter.get_quote(code)
        if quote is None:
            continue
        out.append(_to_brief_dict(quote, label))
    return out


def _to_brief_dict(q: Quote, label: str) -> dict[str, Any]:
    return {
        "code": q.code,
        "name": label,
        "price": q.price,
        "change_pct": q.change_pct,
        "change": q.change,
        "open": q.open,
        "high": q.high,
        "low": q.low,
        "prev_close": q.prev_close,
        "volume": q.volume,
        "timestamp": q.timestamp.isoformat(),
    }
