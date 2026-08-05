"""us_market_service 单元测试（mock adapter，不依赖网络）。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType
from mommy_chaogu.services.us_market_service import (
    US_MARKET_BRIEF,
    fetch_us_market_brief,
)


def _quote(code: str, name: str, price: str, pct: str) -> Quote:
    price_d = Decimal(price)
    prev = Decimal("100.00")
    return Quote(
        code=code,
        name=name,
        market=MarketType.US,
        quote_type=QuoteType.INDEX,
        price=price_d,
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        prev_close=prev,
        change=price_d - prev,
        change_pct=Decimal(pct),
        volume=0,
        turnover=Money(Decimal("0"), "USD"),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime(2026, 8, 4, 20, 0, tzinfo=UTC),
    )


class TestUsMarketBrief:
    def test_brief_constants_cover_five_indexes(self) -> None:
        codes = [c for c, _ in US_MARKET_BRIEF]
        assert codes == ["^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX"]

    def test_fetch_returns_quotes_with_chinese_labels(self) -> None:
        adapter = MagicMock()
        adapter.get_quote.side_effect = [
            _quote("^GSPC", "S&P 500", "7736.52", "1.79"),
            _quote("^IXIC", "NASDAQ Composite", "26584.99", "2.59"),
            None,  # ^DJI 失败 → 跳过
            _quote("^VIX", "CBOE Volatility Index", "16.5", "4.04"),
            _quote("^TNX", "CBOE Interest Rate 10 Year", "4.627", "-1.26"),
        ]

        items = fetch_us_market_brief(adapter)

        assert [i["code"] for i in items] == ["^GSPC", "^IXIC", "^VIX", "^TNX"]
        assert items[0]["name"] == "标普500"  # 用中文展示名
        assert items[0]["price"] == Decimal("7736.52")
        assert items[0]["change_pct"] == Decimal("1.79")
        # 每个代码恰好请求一次
        assert [call.args[0] for call in adapter.get_quote.call_args_list] == [
            "^GSPC",
            "^IXIC",
            "^DJI",
            "^VIX",
            "^TNX",
        ]

    def test_fetch_all_fail_returns_empty(self) -> None:
        adapter = MagicMock()
        adapter.get_quote.return_value = None
        assert fetch_us_market_brief(adapter) == []
