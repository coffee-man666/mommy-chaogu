"""MassiveAdapter 单元测试（mock client，不依赖网络）。"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.massive_adapter import MassiveAdapter, _is_us_code
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    BarInterval,
    MarketType,
    QuoteType,
)


# ---------- 工具函数 ----------


def _make_adapter(key: str = "test_key") -> MassiveAdapter:
    """构造一个带 key 的 MassiveAdapter。"""
    adapter = MassiveAdapter(api_key=key)
    # 替换内部 client 为 mock
    adapter._client = MagicMock()
    return adapter


# ---------- _is_us_code ----------


class TestIsUsCode:
    def test_alpha_codes(self):
        assert _is_us_code("AAPL") is True
        assert _is_us_code("MSFT") is True
        assert _is_us_code("GOOGL") is True
        assert _is_us_code("BRK.B") is True

    def test_numeric_codes(self):
        assert _is_us_code("600519") is False
        assert _is_us_code("000001") is False
        assert _is_us_code("300750") is False

    def test_empty(self):
        assert _is_us_code("") is False


# ---------- Protocol ----------


class TestProtocol:
    def test_satisfies_protocol(self):
        """MassiveAdapter 必须实现 MarketDataAdapter 的所有方法。"""
        adapter = _make_adapter()
        assert isinstance(adapter, MarketDataAdapter)


# ---------- 无 key 行为 ----------


@pytest.fixture
def _clean_env(monkeypatch):
    """清除环境中的 Massive/Polygon key。"""
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)


class TestDisabled:
    def test_no_key_returns_none_for_quote(self, _clean_env):
        adapter = MassiveAdapter(api_key=None)
        assert adapter._enabled is False
        assert adapter.get_quote("AAPL") is None

    def test_no_key_returns_empty_for_quotes(self, _clean_env):
        adapter = MassiveAdapter(api_key=None)
        assert adapter.get_quotes(["AAPL", "MSFT"]) == []

    def test_no_key_returns_empty_for_bars(self, _clean_env):
        adapter = MassiveAdapter(api_key=None)
        assert adapter.get_bars("AAPL") == []

    def test_no_key_health_check_false(self, _clean_env):
        adapter = MassiveAdapter(api_key=None)
        assert adapter.health_check() is False


# ---------- A 股代码快速返回 ----------


class TestAStockCodes:
    def test_a_stock_quote_returns_none(self):
        """A 股代码不应该走 Massive API。"""
        adapter = _make_adapter()
        adapter._client.get_snapshot.side_effect = AssertionError("不应该对 A 股代码发请求")
        assert adapter.get_quote("600519") is None

    def test_a_stock_bars_returns_empty(self):
        adapter = _make_adapter()
        adapter._client.get_aggs.side_effect = AssertionError("不应该对 A 股代码发请求")
        assert adapter.get_bars("000001") == []

    def test_a_stock_filtered_from_quotes(self):
        """混合列表中的 A 股代码被过滤，但美股代码正常请求。"""
        adapter = _make_adapter()
        adapter._client.get_snapshots_batch.return_value = {"results": [
            {"ticker": "AAPL", "name": "Apple", "day": {"c": "190.0", "o": "189.0", "h": "191.0", "l": "188.0", "v": 1000, "vw": "189.5"}, "prevDay": {"c": "188.0"}},
        ]}
        quotes = adapter.get_quotes(["600519", "AAPL", "000001"])
        # A 股被过滤，只有 AAPL 请求了
        assert len(quotes) == 1
        assert quotes[0].code == "AAPL"


# ---------- get_quote ----------


class TestGetQuote:
    def test_parses_snapshot(self):
        """验证 snapshot JSON → Quote 字段映射。"""
        snap_data = {
            "results": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "day": {"o": "189.50", "h": "191.00", "l": "188.20", "c": "190.30", "v": 50000000, "vw": "189.85"},
                "prevDay": {"c": "188.00"},
                "market_cap": 3000000000000,
                "updated": 1700000000000,
            }
        }
        adapter = _make_adapter()
        adapter._client.get_snapshot.return_value = snap_data

        q = adapter.get_quote("AAPL")
        assert q is not None
        assert q.code == "AAPL"
        assert q.name == "Apple Inc."
        assert q.market == MarketType.US
        assert q.quote_type == QuoteType.STOCK
        assert q.price == Decimal("190.30")
        assert q.open == Decimal("189.50")
        assert q.high == Decimal("191.00")
        assert q.low == Decimal("188.20")
        assert q.prev_close == Decimal("188.00")
        assert q.change == Decimal("2.30")
        assert q.change_pct > Decimal("1.21")
        assert q.change_pct < Decimal("1.23")
        assert q.volume == 50000000
        assert q.turnover.currency == "USD"
        assert q.turnover.amount == Decimal("189.85") * Decimal("50000000")
        assert q.total_market_cap is not None
        assert q.total_market_cap.amount == Decimal("3000000000000")
        assert q.total_market_cap.currency == "USD"

    def test_uppercase_ticker(self):
        """小写 ticker 自动转大写。"""
        snap_data = {"results": {"ticker": "AAPL", "name": "Apple", "day": {"c": "190.0", "o": "189.0", "h": "191.0", "l": "188.0", "v": 100, "vw": "189.5"}, "prevDay": {"c": "188.0"}}}
        adapter = _make_adapter()
        adapter._client.get_snapshot.return_value = snap_data
        q = adapter.get_quote("aapl")
        assert q is not None
        assert q.code == "AAPL"

    def test_none_snapshot_falls_back_to_prev_close(self):
        """Basic tier: snapshot=None → fallback to previous_close."""
        prev_data = {"results": [{"T": "AAPL", "o": "309.0", "h": "311.0", "l": "302.0", "c": "303.0", "v": 75000000, "vw": "306.0", "t": 1700000000000}]}
        details = {"results": {"name": "Apple Inc.", "market_cap": 4000000000000}}
        adapter = _make_adapter()
        adapter._client.get_snapshot.return_value = None
        adapter._client.get_previous_close.return_value = prev_data
        adapter._client.get_ticker_details.return_value = details
        q = adapter.get_quote("AAPL")
        assert q is not None
        assert q.code == "AAPL"
        assert q.name == "Apple Inc."
        assert q.price == Decimal("303.0")
        assert q.total_market_cap is not None
        assert q.total_market_cap.amount == Decimal("4000000000000")

    def test_both_snapshot_and_prev_close_none(self):
        adapter = _make_adapter()
        adapter._client.get_snapshot.return_value = None
        adapter._client.get_previous_close.return_value = None
        assert adapter.get_quote("AAPL") is None

    def test_fills_name_from_ticker_details(self):
        """snapshot 没带 name → 查 ticker details 补全。"""
        snap_data = {"results": {"ticker": "AAPL", "day": {"c": "190.0", "o": "189.0", "h": "191.0", "l": "188.0", "v": 100, "vw": "189.5"}, "prevDay": {"c": "188.0"}}}
        adapter = _make_adapter()
        adapter._client.get_snapshot.return_value = snap_data
        adapter._client.get_ticker_details.return_value = {"results": {"name": "Apple Inc."}}
        q = adapter.get_quote("AAPL")
        assert q is not None
        assert q.name == "Apple Inc."


# ---------- get_quotes ----------


class TestGetQuotes:
    def test_batch_snapshot(self):
        batch_data = {
            "results": [
                {
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "day": {"o": "189.0", "h": "191.0", "l": "188.0", "c": "190.0", "v": 1000, "vw": "189.5"},
                    "prevDay": {"c": "188.0"},
                },
                {
                    "ticker": "MSFT",
                    "name": "Microsoft Corp.",
                    "day": {"o": "410.0", "h": "415.0", "l": "408.0", "c": "412.0", "v": 2000, "vw": "411.0"},
                    "prevDay": {"c": "409.0"},
                },
            ]
        }
        adapter = _make_adapter()
        adapter._client.get_snapshots_batch.return_value = batch_data

        quotes = adapter.get_quotes(["AAPL", "MSFT", "600519"])
        assert len(quotes) == 2
        codes = {q.code for q in quotes}
        assert codes == {"AAPL", "MSFT"}
        assert all(q.market == MarketType.US for q in quotes)

    def test_empty_input(self):
        adapter = _make_adapter()
        assert adapter.get_quotes([]) == []

    def test_batch_fallback_to_prev_close(self):
        """Basic tier: batch snapshot returns empty → fallback to previous_close per ticker."""
        prev_aapl = {"results": [{"o": "189.0", "h": "191.0", "l": "188.0", "c": "190.0", "v": 1000, "vw": "189.5", "t": 1700000000000}]}
        details_aapl = {"results": {"name": "Apple Inc."}}
        adapter = _make_adapter()
        adapter._client.get_snapshots_batch.return_value = {"results": []}  # empty → fallback
        adapter._client.get_previous_close.return_value = prev_aapl
        adapter._client.get_ticker_details.return_value = details_aapl
        quotes = adapter.get_quotes(["AAPL"])
        assert len(quotes) == 1
        assert quotes[0].code == "AAPL"
        assert quotes[0].name == "Apple Inc."


# ---------- get_bars ----------


class TestGetBars:
    def test_parses_aggregate_bars(self):
        agg_data = {
            "results": [
                {"t": 1700000000000, "o": "189.0", "h": "191.0", "l": "188.0", "c": "190.0", "v": 50000, "vw": "189.5"},
                {"t": 1700086400000, "o": "190.0", "h": "192.0", "l": "189.5", "c": "191.5", "v": 60000, "vw": "190.8"},
            ]
        }
        adapter = _make_adapter()
        adapter._client.get_aggs.return_value = agg_data

        bars = adapter.get_bars("AAPL", interval=BarInterval.D1, limit=10)
        assert len(bars) == 2
        assert bars[0].code == "AAPL"
        assert bars[0].close == Decimal("190.0")
        assert bars[0].open == Decimal("189.0")
        assert bars[0].volume == 50000
        assert bars[0].turnover.currency == "USD"
        assert bars[0].interval == BarInterval.D1
        assert bars[0].adjustment == AdjustmentType.FORWARD
        assert bars[0].timestamp < bars[1].timestamp

    def test_limit_truncation(self):
        """limit 截断取最后 N 根。"""
        results = [
            {"t": 1700000000000 + i * 86400000, "o": "100", "h": "101", "l": "99", "c": "100.5", "v": 1000, "vw": "100.2"}
            for i in range(10)
        ]
        adapter = _make_adapter()
        adapter._client.get_aggs.return_value = {"results": results}

        bars = adapter.get_bars("AAPL", interval=BarInterval.D1, limit=3)
        assert len(bars) == 3

    def test_empty_results(self):
        adapter = _make_adapter()
        adapter._client.get_aggs.return_value = {"results": []}
        assert adapter.get_bars("AAPL") == []

    def test_none_results(self):
        adapter = _make_adapter()
        adapter._client.get_aggs.return_value = {"results": None}
        assert adapter.get_bars("AAPL") == []

    def test_client_returns_none(self):
        adapter = _make_adapter()
        adapter._client.get_aggs.return_value = None
        assert adapter.get_bars("AAPL") == []


# ---------- health_check ----------


class TestHealthCheck:
    def test_enabled_and_ok(self):
        adapter = _make_adapter()
        adapter._client.get_market_status.return_value = {"market": "US", "serverTime": 1700000000000}
        assert adapter.health_check() is True

    def test_enabled_but_bad_response(self):
        adapter = _make_adapter()
        adapter._client.get_market_status.return_value = {}
        assert adapter.health_check() is False

    def test_enabled_but_none(self):
        adapter = _make_adapter()
        adapter._client.get_market_status.return_value = None
        assert adapter.health_check() is False


# ---------- 不支持的方法 ----------


class TestUnsupportedMethods:
    def test_list_market_quotes_empty(self):
        adapter = _make_adapter()
        assert adapter.list_market_quotes() == []

    def test_get_order_book_none(self):
        adapter = _make_adapter()
        assert adapter.get_order_book("AAPL") is None

    def test_get_ticks_empty(self):
        adapter = _make_adapter()
        assert adapter.get_ticks("AAPL") == []

    def test_today_money_flow_empty(self):
        adapter = _make_adapter()
        assert adapter.get_today_money_flow("AAPL") == []

    def test_history_money_flow_empty(self):
        adapter = _make_adapter()
        assert adapter.get_history_money_flow("AAPL") == []

    def test_belonging_boards_empty(self):
        adapter = _make_adapter()
        assert adapter.get_belonging_boards("AAPL") == []
