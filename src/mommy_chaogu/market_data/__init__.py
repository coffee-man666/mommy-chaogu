"""market_data 包：行情数据源抽象层。"""

from mommy_chaogu.market_data.adapter import (
    MarketDataAdapter,
    filter_by_market,
    find_quote,
)
from mommy_chaogu.market_data.efinance_adapter import EfinanceAdapter
from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter
from mommy_chaogu.market_data.massive_adapter import MassiveAdapter
from mommy_chaogu.market_data.massive_client import MassiveClient
from mommy_chaogu.market_data.tencent_adapter import TencentAdapter
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    OrderBookLevel,
    Quote,
    QuoteType,
    Tick,
)
from mommy_chaogu.market_data.yahoo_adapter import YahooAdapter
from mommy_chaogu.market_data.yahoo_client import YahooClient


def create_adapter_chain() -> MarketDataAdapter:
    """构造默认适配器链：[Massive(美股), Yahoo(美股备用/指数/利率/VIX), Efinance(A股), Tencent(A股兜底)]。

    MassiveAdapter 在链首——美股代码命中；`^` 前缀指数（^GSPC/^VIX/^TNX）Massive 无数据，
    自动落到 YahooAdapter。A 股代码前两个源快速返回 None/[]（零网络开销），走 Efinance。
    """
    adapters: list[MarketDataAdapter] = [MassiveAdapter(), YahooAdapter()]
    adapters.append(EfinanceAdapter())
    adapters.append(TencentAdapter())
    return FallbackAdapter(adapters)


__all__ = [
    "AdjustmentType",
    "Bar",
    "BarInterval",
    "Board",
    "EfinanceAdapter",
    "FallbackAdapter",
    "MarketDataAdapter",
    "MarketType",
    "MassiveAdapter",
    "MassiveClient",
    "Money",
    "MoneyFlow",
    "OrderBook",
    "OrderBookLevel",
    "Quote",
    "QuoteType",
    "TencentAdapter",
    "Tick",
    "YahooAdapter",
    "YahooClient",
    "create_adapter_chain",
    "filter_by_market",
    "find_quote",
]
