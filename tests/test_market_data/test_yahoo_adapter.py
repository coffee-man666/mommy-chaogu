"""YahooAdapter 单元测试（mock client，不依赖网络）。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    BarInterval,
    MarketType,
    QuoteType,
)
from mommy_chaogu.market_data.yahoo_adapter import YahooAdapter, _is_us_ticker


def _ts(y: int, m: int, d: int, h: int = 0) -> int:
    return int(datetime(y, m, d, h, tzinfo=UTC).timestamp())


def _chart(meta: dict, bars: list[tuple], adjclose: list[float] | None = None) -> dict:
    """构造 chart 响应：meta + OHLCV 数组（可选 adjclose）。"""
    indicators: dict = {
        "quote": [
            {
                "open": [b[1] for b in bars],
                "high": [b[2] for b in bars],
                "low": [b[3] for b in bars],
                "close": [b[4] for b in bars],
                "volume": [b[5] for b in bars],
            }
        ]
    }
    if adjclose is not None:
        indicators["adjclose"] = [{"adjclose": adjclose}]
    return {
        "chart": {
            "result": [
                {
                    "meta": meta,
                    "timestamp": [b[0] for b in bars],
                    "indicators": indicators,
                }
            ]
        }
    }


AAPL_BARS = [
    (_ts(2026, 7, 29), 339.73, 344.57, 337.35, 338.19, 56090800),
    (_ts(2026, 7, 30), 333.10, 334.75, 329.59, 333.43, 74817800),
    (_ts(2026, 7, 31), 304.81, 310.69, 300.00, 308.91, 132489100),
    (_ts(2026, 8, 3), 309.58, 311.80, 302.56, 303.42, 75052000),
    (_ts(2026, 8, 4), 302.73, 310.42, 301.32, 309.38, 67778746),
]

AAPL_META = {
    "symbol": "AAPL",
    "longName": "Apple Inc.",
    "shortName": "Apple Inc.",
    "instrumentType": "EQUITY",
    "currency": "USD",
    "regularMarketPrice": 309.38,
    "regularMarketTime": _ts(2026, 8, 4, 20),
    "regularMarketDayHigh": 310.42,
    "regularMarketDayLow": 301.32,
    "regularMarketVolume": 67778746,
    "gmtoffset": -14400,
}

GSPC_BARS = [
    (_ts(2026, 7, 31), 7488.00, 7500.00, 7400.00, 7450.00, 0),
    (_ts(2026, 8, 3), 7460.00, 7500.00, 7350.00, 7428.78, 0),
    (_ts(2026, 8, 4), 7440.00, 7758.21, 7629.10, 7736.52, 0),
]

GSPC_META = {
    "symbol": "^GSPC",
    "longName": "S&P 500",
    "shortName": "S&P 500",
    "instrumentType": "INDEX",
    "currency": "USD",
    "regularMarketPrice": 7736.52,
    "regularMarketTime": _ts(2026, 8, 4, 20),
    "regularMarketDayHigh": 7758.21,
    "regularMarketDayLow": 7629.10,
    "regularMarketVolume": 3703215000,
    "gmtoffset": -14400,
}


def _make_adapter() -> tuple[YahooAdapter, MagicMock]:
    adapter = YahooAdapter(timeout=5)
    adapter._client = MagicMock()
    return adapter, adapter._client


def _pct(a: str, b: str) -> Decimal:
    return (Decimal(a) - Decimal(b)) / Decimal(b) * Decimal("100")


# ---------- _is_us_ticker ----------


class TestIsUsTicker:
    def test_us_codes(self):
        assert _is_us_ticker("AAPL") is True
        assert _is_us_ticker("BRK.B") is True
        assert _is_us_ticker("^GSPC") is True
        assert _is_us_ticker("^VIX") is True
        assert _is_us_ticker("^TNX") is True

    def test_non_us_codes(self):
        assert _is_us_ticker("600519") is False
        assert _is_us_ticker("000001") is False
        assert _is_us_ticker("") is False


# ---------- Protocol ----------


class TestProtocol:
    def test_satisfies_protocol(self):
        adapter, _ = _make_adapter()
        assert isinstance(adapter, MarketDataAdapter)


# ---------- A 股代码快速返回 ----------


class TestAStockSkip:
    def test_a_stock_quote_returns_none(self):
        adapter, client = _make_adapter()
        client.get_chart.side_effect = AssertionError("不应该对 A 股代码发请求")
        assert adapter.get_quote("600519") is None

    def test_a_stock_bars_returns_empty(self):
        adapter, client = _make_adapter()
        client.get_chart.side_effect = AssertionError("不应该对 A 股代码发请求")
        assert adapter.get_bars("600519") == []


# ---------- get_quote ----------


class TestGetQuote:
    def test_index_quote(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(GSPC_META, GSPC_BARS)

        q = adapter.get_quote("^GSPC")

        assert q is not None
        assert q.code == "^GSPC"
        assert q.name == "S&P 500"
        assert q.market == MarketType.US
        assert q.quote_type == QuoteType.INDEX
        assert q.price == Decimal("7736.52")
        assert q.prev_close == Decimal("7428.78")
        assert q.change == Decimal("307.74")
        assert q.change_pct == _pct("7736.52", "7428.78").quantize(Decimal("0.01"))
        assert q.volume == 0  # 指数无成交量
        assert q.turnover.amount == Decimal("0")
        assert q.timestamp == datetime(2026, 8, 4, 20, tzinfo=UTC)
        # 请求的是 5d 日 K 用于计算涨跌幅
        assert client.get_chart.call_args[0] == ("^GSPC",)
        assert client.get_chart.call_args[1]["range"] == "5d"

    def test_stock_quote(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(AAPL_META, AAPL_BARS)

        q = adapter.get_quote("aapl")

        assert q is not None
        assert q.code == "AAPL"
        assert q.name == "Apple Inc."
        assert q.quote_type == QuoteType.STOCK
        assert q.price == Decimal("309.38")
        assert q.prev_close == Decimal("303.42")
        assert q.change == Decimal("5.96")
        assert q.change_pct == _pct("309.38", "303.42").quantize(Decimal("0.01"))
        assert q.volume == 67778746
        assert q.turnover.amount == Decimal("309.38") * Decimal(67778746)
        assert q.turnover.currency == "USD"

    def test_single_bar_falls_back_to_meta_previous_close(self):
        meta = dict(AAPL_META, previousClose=300.0)
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(meta, AAPL_BARS[-1:])

        q = adapter.get_quote("AAPL")

        assert q is not None
        assert q.prev_close == Decimal("300.0")
        assert q.change == Decimal("9.38")

    def test_meta_only_quote(self):
        """只有 meta 没有 K 线也能出报价（prev_close 兜底为 price，涨跌幅 0）。"""
        meta = dict(AAPL_META)
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(meta, [])

        q = adapter.get_quote("AAPL")

        assert q is not None
        assert q.price == Decimal("309.38")
        assert q.change_pct == Decimal("0")
        assert q.volume == 67778746  # 从 meta 取

    def test_client_failure_returns_none(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = None
        assert adapter.get_quote("^GSPC") is None

    def test_missing_regular_price_returns_none(self):
        meta = dict(AAPL_META)
        del meta["regularMarketPrice"]
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(meta, AAPL_BARS)
        assert adapter.get_quote("AAPL") is None


# ---------- get_quotes ----------


class TestGetQuotes:
    def test_dedupe_and_skip_a_stock(self):
        adapter, client = _make_adapter()
        client.get_chart.side_effect = [
            _chart(GSPC_META, GSPC_BARS),
            _chart(AAPL_META, AAPL_BARS),
        ]

        quotes = adapter.get_quotes(["^GSPC", "AAPL", "^GSPC", "600519"])

        assert [q.code for q in quotes] == ["^GSPC", "AAPL"]
        # A 股代码没有发任何请求
        assert client.get_chart.call_count == 2

    def test_skip_failures(self):
        adapter, client = _make_adapter()
        client.get_chart.side_effect = [None, _chart(AAPL_META, AAPL_BARS)]

        quotes = adapter.get_quotes(["^GSPC", "AAPL"])

        assert [q.code for q in quotes] == ["AAPL"]


# ---------- get_bars ----------


class TestGetBars:
    def test_daily_limit_slices_last_n(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(AAPL_META, AAPL_BARS)

        bars = adapter.get_bars("AAPL", interval=BarInterval.D1, limit=3)

        assert len(bars) == 3
        assert bars[-1].close == Decimal("309.38")
        assert bars[0].timestamp.date() == date(2026, 7, 31)
        assert bars[-1].timestamp.date() == date(2026, 8, 4)
        assert bars[-1].turnover.amount == Decimal("309.38") * Decimal(67778746)
        assert bars[-1].turnover.currency == "USD"

    def test_start_end_filter(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(AAPL_META, AAPL_BARS)

        bars = adapter.get_bars(
            "AAPL", interval=BarInterval.D1, start=date(2026, 8, 3), end=date(2026, 8, 4)
        )

        assert len(bars) == 2
        assert [b.timestamp.date() for b in bars] == [date(2026, 8, 3), date(2026, 8, 4)]

    def test_adjusted_close_used_when_not_none_adjustment(self):
        adjclose = [338.5, 333.8, 309.2, 303.7, 309.5]
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(AAPL_META, AAPL_BARS, adjclose=adjclose)

        bars_fwd = adapter.get_bars(
            "AAPL", interval=BarInterval.D1, adjustment=AdjustmentType.FORWARD
        )
        assert bars_fwd[-1].close == Decimal("309.5")

        bars_raw = adapter.get_bars("AAPL", interval=BarInterval.D1, adjustment=AdjustmentType.NONE)
        assert bars_raw[-1].close == Decimal("309.38")

    def test_interval_mapping(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = _chart(AAPL_META, AAPL_BARS[-1:])

        adapter.get_bars("AAPL", interval=BarInterval.M60, limit=5)
        assert client.get_chart.call_args[1]["interval"] == "1h"

        adapter.get_bars("AAPL", interval=BarInterval.W1, limit=5)
        assert client.get_chart.call_args[1]["interval"] == "1wk"

    def test_empty_response(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = None
        assert adapter.get_bars("AAPL") == []


# ---------- 不支持的方法 ----------


class TestUnsupportedMethods:
    def test_returns_empty_or_none(self):
        adapter, _ = _make_adapter()
        assert adapter.list_market_quotes() == []
        assert adapter.get_order_book("AAPL") is None
        assert adapter.get_ticks("AAPL") == []
        assert adapter.get_today_money_flow("AAPL") == []
        assert adapter.get_history_money_flow("AAPL") == []
        assert adapter.get_belonging_boards("AAPL") == []


# ---------- health_check ----------


class TestHealthCheck:
    def test_healthy(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = {"chart": {"result": []}}
        assert adapter.health_check() is True
        assert client.get_chart.call_args[0] == ("^GSPC",)

    def test_unhealthy(self):
        adapter, client = _make_adapter()
        client.get_chart.return_value = None
        assert adapter.health_check() is False


# ---------- fallback 链路由 ----------


class TestChainRouting:
    def test_index_falls_through_massive_to_yahoo(self, monkeypatch):
        import mommy_chaogu.market_data as md

        hits: list[str] = []

        class _Massive:
            name = "massive"

            def get_quote(self, code):
                return None

        class _Yahoo:
            name = "yahoo"

            def get_quote(self, code):
                hits.append(code)
                return "YAHOO-QUOTE"

        class _Efinance:
            name = "efinance"

            def get_quote(self, code):
                return None

        class _Tencent:
            name = "tencent"

            def get_quote(self, code):
                return None

        monkeypatch.setattr(md, "MassiveAdapter", lambda: _Massive())
        monkeypatch.setattr(md, "YahooAdapter", lambda: _Yahoo())
        monkeypatch.setattr(md, "EfinanceAdapter", lambda: _Efinance())
        monkeypatch.setattr(md, "TencentAdapter", lambda: _Tencent())

        chain = md.create_adapter_chain()
        assert chain.get_quote("^GSPC") == "YAHOO-QUOTE"
        assert hits == ["^GSPC"]

    def test_massive_skips_caret_index_codes(self):
        """Massive 对 ^ 前缀快速返回 None（_is_us_code 不认），Yahoo 才有机会接管。"""
        from mommy_chaogu.market_data.massive_adapter import MassiveAdapter

        adapter = MassiveAdapter(api_key="test_key")
        adapter._client = MagicMock()
        adapter._client.get_snapshot.side_effect = AssertionError("不应请求")
        assert adapter.get_quote("^GSPC") is None


# ---------- 真实探测（可选） ----------


@pytest.mark.network
def test_live_index_quote():
    """真实网络探测：Yahoo 指数报价可用。"""
    adapter = YahooAdapter(timeout=10)
    quote = adapter.get_quote("^GSPC")
    assert quote is not None
    assert quote.quote_type == QuoteType.INDEX
    assert quote.market == MarketType.US
