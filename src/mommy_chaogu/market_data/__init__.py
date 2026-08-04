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


def create_adapter_chain() -> MarketDataAdapter:
    """构造默认适配器链：[Massive(美股), Efinance(A股), Tencent(A股兜底)]。

    MassiveAdapter 在链首——美股代码命中，A 股代码快速返回 None/[]（零网络开销），
    自动 fallback 到 EfinanceAdapter。
    """
    adapters: list[MarketDataAdapter] = [MassiveAdapter()]
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
    "MassiveAdapter",
    "MassiveClient",
    "MarketDataAdapter",
    "MarketType",
    "Money",
    "MoneyFlow",
    "OrderBook",
    "OrderBookLevel",
    "Quote",
    "QuoteType",
    "TencentAdapter",
    "Tick",
    "create_adapter_chain",
    "filter_by_market",
    "find_quote",
]
