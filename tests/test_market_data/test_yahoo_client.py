"""YahooClient 单元测试（mock HTTP，不依赖网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock

from requests import HTTPError, Response, Timeout

from mommy_chaogu.market_data.yahoo_client import DEFAULT_BASE_URL, YahooClient

# ---------- 工具 ----------


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=Response)
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def _make_client() -> YahooClient:
    return YahooClient()


# ---------- get_chart ----------


class TestGetChart:
    def test_encodes_caret_symbol_in_path(self):
        client = _make_client()
        mock_get = MagicMock(return_value=_mock_response({"chart": {"result": []}}))
        client._session.get = mock_get

        client.get_chart("^GSPC", range="5d", interval="1d")

        url = mock_get.call_args[0][0]
        assert url == f"{DEFAULT_BASE_URL}/v8/finance/chart/%5EGSPC"

    def test_params(self):
        client = _make_client()
        mock_get = MagicMock(return_value=_mock_response({"chart": {"result": []}}))
        client._session.get = mock_get

        client.get_chart("^VIX", range="1mo", interval="1d", include_prepost=True)

        params = mock_get.call_args[1]["params"]
        assert params["range"] == "1mo"
        assert params["interval"] == "1d"
        assert params["includePrePost"] == "true"

    def test_uppercases_symbol(self):
        client = _make_client()
        mock_get = MagicMock(return_value=_mock_response({"chart": {"result": []}}))
        client._session.get = mock_get

        client.get_chart("aapl", range="1d", interval="1d")

        url = mock_get.call_args[0][0]
        assert url.endswith("/AAPL")

    def test_returns_payload(self):
        client = _make_client()
        payload = {"chart": {"result": [{"meta": {"symbol": "^GSPC"}}]}}
        mock_get = MagicMock(return_value=_mock_response(payload))
        client._session.get = mock_get

        assert client.get_chart("^GSPC") == payload

    def test_http_error_returns_none(self):
        client = _make_client()
        resp = _mock_response({}, status=500)
        resp.raise_for_status.side_effect = HTTPError("HTTP 500")
        client._session.get = MagicMock(return_value=resp)

        assert client.get_chart("^GSPC") is None

    def test_exception_returns_none(self):
        client = _make_client()
        client._session.get = MagicMock(side_effect=Timeout("timeout"))

        assert client.get_chart("^GSPC") is None


# ---------- 初始化 ----------


class TestInit:
    def test_default_base_url(self):
        assert YahooClient().base_url == DEFAULT_BASE_URL

    def test_custom_base_url_strips_trailing_slash(self):
        client = YahooClient(base_url="https://custom.yahoo.com/")
        assert client.base_url == "https://custom.yahoo.com"
