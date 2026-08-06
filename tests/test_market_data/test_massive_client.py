"""MassiveClient 单元测试（mock HTTP，不依赖网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from requests import Response

from mommy_chaogu.market_data.massive_client import MassiveClient

# ---------- 工具 ----------


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=Response)
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def _make_client(key: str = "test_key") -> MassiveClient:
    return MassiveClient(api_key=key)


@pytest.fixture
def _clean_env(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)


# ---------- 初始化 ----------


class TestInit:
    def test_enabled_with_key(self):
        c = MassiveClient(api_key="xxx")
        assert c.enabled is True
        assert c._key == "xxx"

    def test_disabled_without_key(self, _clean_env):
        c = MassiveClient(api_key=None)
        assert c.enabled is False

    def test_env_var_massive(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "env_key")
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        c = MassiveClient()
        assert c.enabled is True
        assert c._key == "env_key"

    def test_env_var_polygon_legacy(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        monkeypatch.setenv("POLYGON_API_KEY", "legacy_key")
        c = MassiveClient()
        assert c.enabled is True
        assert c._key == "legacy_key"

    def test_param_overrides_env(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "env_key")
        c = MassiveClient(api_key="param_key")
        assert c._key == "param_key"

    def test_custom_base_url(self):
        c = MassiveClient(api_key="x", base_url="https://custom.api.com/")
        assert c.base_url == "https://custom.api.com"

    def test_disabled_get_returns_none(self, _clean_env):
        c = MassiveClient(api_key=None)
        assert c._get("/any/path") is None


# ---------- Tickers / Reference ----------


class TestTickers:
    def test_get_ticker_details(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": {"ticker": "AAPL", "name": "Apple Inc."}})
        )
        data = c.get_ticker_details("aapl")
        assert data is not None
        assert data["results"]["ticker"] == "AAPL"

    def test_list_tickers(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": [{"ticker": "AAPL"}, {"ticker": "MSFT"}]})
        )
        tickers = c.list_tickers(limit=10)
        assert len(tickers) == 2
        assert tickers[0]["ticker"] == "AAPL"

    def test_get_ticker_types(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": [{"asset_type": "stock"}]})
        )
        data = c.get_ticker_types()
        assert data is not None
        assert data["results"][0]["asset_type"] == "stock"

    def test_get_related_companies(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": [{"ticker": "MSFT"}]}))
        data = c.get_related_companies("AAPL")
        assert data is not None
        assert data["results"][0]["ticker"] == "MSFT"


# ---------- Snapshots ----------


class TestSnapshots:
    def test_get_snapshot(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": {"ticker": "AAPL", "day": {"c": "190.0"}}})
        )
        data = c.get_snapshot("AAPL")
        assert data is not None
        assert data["results"]["day"]["c"] == "190.0"

    def test_get_snapshots_batch(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": [{"ticker": "AAPL"}, {"ticker": "MSFT"}]})
        )
        data = c.get_snapshots_batch(["AAPL", "MSFT"])
        assert data is not None
        # 验证 tickers 参数传了
        call_args = c._session.get.call_args
        assert "tickers" in call_args.kwargs["params"]

    def test_get_snapshots_batch_truncates_to_250(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": []}))
        c.get_snapshots_batch(["A" + str(i) for i in range(300)])
        params = c._session.get.call_args.kwargs["params"]
        tickers = params["tickers"].split(",")
        assert len(tickers) == 250

    def test_get_gainers_losers(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"tickers": [{"ticker": "GME"}]}))
        data = c.get_gainers_losers("gainers")
        assert data is not None
        assert data["tickers"][0]["ticker"] == "GME"

    def test_get_gainers_losers_invalid_direction_defaults(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"tickers": []}))
        c.get_gainers_losers("invalid")
        call_url = c._session.get.call_args.args[0]
        assert "gainers" in call_url


# ---------- Aggs ----------


class TestAggs:
    def test_get_aggs(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response(
                {"results": [{"t": 1700000000000, "o": "189.0", "c": "190.0"}]}
            )
        )
        data = c.get_aggs("AAPL", multiplier=1, timespan="day", from_="2024-01-01", to="2024-06-01")
        assert data is not None
        assert len(data["results"]) == 1

    def test_get_grouped_daily(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": []}))
        c.get_grouped_daily("2024-01-15")
        call_url = c._session.get.call_args.args[0]
        assert "2024-01-15" in call_url

    def test_get_daily_open_close(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"open": 189.0, "close": 190.0}))
        data = c.get_daily_open_close("AAPL", "2024-01-15")
        assert data is not None
        assert data["close"] == 190.0

    def test_get_previous_close(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": [{"c": 188.0}]}))
        data = c.get_previous_close("AAPL")
        assert data is not None
        assert data["results"][0]["c"] == 188.0


# ---------- Technical Indicators ----------


class TestIndicators:
    def test_get_sma(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": {"values": [{"value": "150.0"}]}})
        )
        data = c.get_sma("AAPL", window=50)
        assert data is not None
        url = c._session.get.call_args.args[0]
        assert "/v1/indicators/sma/AAPL" in url

    def test_get_ema(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": {"values": []}}))
        c.get_ema("MSFT", window=20)
        url = c._session.get.call_args.args[0]
        assert "/v1/indicators/ema/MSFT" in url

    def test_get_rsi(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": {"values": []}}))
        c.get_rsi("GOOGL", window=14)
        url = c._session.get.call_args.args[0]
        assert "/v1/indicators/rsi/GOOGL" in url

    def test_get_macd(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": {"values": []}}))
        c.get_macd("TSLA")
        url = c._session.get.call_args.args[0]
        assert "/v1/indicators/macd/TSLA" in url

    def test_window_clamped(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": {"values": []}}))
        c.get_sma("AAPL", window=500)
        params = c._session.get.call_args.kwargs["params"]
        assert params["window"] == 200  # clamped to max


# ---------- Market Operations ----------


class TestMarketOps:
    def test_get_market_status(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"market": "US", "serverTime": 1700000000000})
        )
        data = c.get_market_status()
        assert data is not None
        assert data["market"] == "US"

    def test_get_market_holidays(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": [{"exchange": "NASDAQ"}]})
        )
        data = c.get_market_holidays()
        assert data is not None

    def test_get_exchanges(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": [{"id": 1}]}))
        data = c.get_exchanges()
        assert data is not None


# ---------- Corporate Actions ----------


class TestCorporateActions:
    def test_get_splits(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": [{"split_ratio": "4:1"}]})
        )
        data = c.get_splits("AAPL")
        assert data is not None
        assert data["results"][0]["split_ratio"] == "4:1"

    def test_get_dividends(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": [{"amount": "0.24"}]}))
        data = c.get_dividends("MSFT")
        assert data is not None

    def test_get_short_interest(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": [{"ticker": "AAPL"}]}))
        data = c.get_short_interest("AAPL")
        assert data is not None

    def test_get_float(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": {"ticker": "AAPL", "float": 15000000000}})
        )
        data = c.get_float("AAPL")
        assert data is not None


# ---------- News ----------


class TestNews:
    def test_get_news_with_ticker(self):
        c = _make_client()
        c._session.get = MagicMock(
            return_value=_mock_response({"results": [{"title": "Apple earnings"}]})
        )
        data = c.get_news("AAPL", limit=5)
        assert data is not None
        params = c._session.get.call_args.kwargs["params"]
        assert params["ticker"] == "AAPL"
        assert params["limit"] == 5

    def test_get_news_without_ticker(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": []}))
        c.get_news()
        params = c._session.get.call_args.kwargs["params"]
        assert "ticker" not in params


# ---------- Pagination ----------


class TestPagination:
    def test_single_page_no_next_url(self):
        c = _make_client()
        c._session.get = MagicMock(return_value=_mock_response({"results": [{"a": 1}, {"b": 2}]}))
        results = c._get_paginated("/test", max_results=100)
        assert len(results) == 2
        assert c._session.get.call_count == 1

    def test_multi_page_with_next_url(self):
        c = _make_client()
        page1 = _mock_response(
            {"results": [{"a": 1}], "next_url": "https://api.massive.com/test?page=2"}
        )
        page2 = _mock_response({"results": [{"b": 2}]})
        c._session.get = MagicMock(side_effect=[page1, page2])
        results = c._get_paginated("/test", max_results=100)
        assert len(results) == 2
        assert c._session.get.call_count == 2

    def test_max_results_truncation(self):
        c = _make_client()
        page1 = _mock_response(
            {
                "results": [{"a": i} for i in range(100)],
                "next_url": "https://api.massive.com/test?page=2",
            }
        )
        page2 = _mock_response({"results": [{"b": i} for i in range(100)]})
        c._session.get = MagicMock(side_effect=[page1, page2])
        results = c._get_paginated("/test", max_results=50)
        assert len(results) == 50


# ---------- Error Handling ----------


class TestErrorHandling:
    def test_http_error_returns_none(self):
        c = _make_client()
        mock_resp = MagicMock(spec=Response)
        mock_resp.raise_for_status.side_effect = Exception("HTTP 429")
        c._session.get = MagicMock(return_value=mock_resp)
        assert c._get("/any") is None

    def test_exception_returns_none(self):
        c = _make_client()
        c._session.get = MagicMock(side_effect=Exception("network error"))
        assert c._get("/any") is None

    def test_disabled_returns_none(self, _clean_env):
        c = MassiveClient(api_key=None)
        assert c.get_snapshot("AAPL") is None
        assert c.get_aggs("AAPL") is None
        assert c.get_market_status() is None
