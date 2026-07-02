"""/api/quotes 路由测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class TestGetSnapshot:
    """GET /api/quotes — 自选股快照。"""

    def test_returns_snapshot(self, client: TestClient) -> None:
        resp = client.get("/api/quotes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_codes"] == 2
        assert len(data["quotes"]) == 2
        assert data["n_up"] == 1
        assert data["n_down"] == 1

    def test_snapshot_has_quotes_with_code(self, client: TestClient) -> None:
        resp = client.get("/api/quotes")
        quotes = resp.json()["quotes"]
        codes = {q["code"] for q in quotes}
        assert "600519" in codes
        assert "000858" in codes

    def test_decimal_as_string(self, client: TestClient) -> None:
        """Decimal 序列化为 str，不是 float。"""
        resp = client.get("/api/quotes")
        price = resp.json()["quotes"][0]["price"]
        assert isinstance(price, str)
        assert price == "1680.50"


class TestGetQuote:
    """GET /api/quotes/{code} — 单股报价。"""

    def test_found_in_snapshot(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "600519"
        assert data["name"] == "贵州茅台"

    def test_not_in_snapshot_fallback_adapter(
        self, client: TestClient, mock_adapter: MagicMock
    ) -> None:
        """不在 snapshot 里的股票，走 adapter fallback。"""
        resp = client.get("/api/quotes/300750")
        assert resp.status_code == 200
        # mock_adapter.get_quote 返回默认 600519，但 code 可能对不上
        # 关键是 adapter 被调用了
        mock_adapter.get_quote.assert_called_with("300750")

    def test_404_when_adapter_returns_none(
        self, client: TestClient, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.get_quote.return_value = None
        resp = client.get("/api/quotes/999999")
        assert resp.status_code == 404


class TestGetBars:
    """GET /api/quotes/{code}/bars — K 线。"""

    def test_default_params(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519/bars")
        assert resp.status_code == 200
        bars = resp.json()
        assert len(bars) == 3  # mock 返回 3 根

    def test_custom_interval_and_limit(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519/bars?interval=5m&limit=30")
        assert resp.status_code == 200

    def test_limit_out_of_range(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519/bars?limit=0")
        assert resp.status_code == 422  # validation error

    def test_limit_too_large(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519/bars?limit=600")
        assert resp.status_code == 422


class TestGetOrderbook:
    """GET /api/quotes/{code}/orderbook — 5 档盘口。"""

    def test_found(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519/orderbook")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "600519"
        assert len(data["bids"]) == 5
        assert len(data["asks"]) == 5

    def test_404_when_none(self, client: TestClient, mock_adapter: MagicMock) -> None:
        mock_adapter.get_order_book.return_value = None
        resp = client.get("/api/quotes/999999/orderbook")
        assert resp.status_code == 404


class TestGetMoneyFlow:
    """GET /api/quotes/{code}/money_flow/today — 当日资金流。"""

    def test_found(self, client: TestClient) -> None:
        resp = client.get("/api/quotes/600519/money_flow/today")
        assert resp.status_code == 200
        data = resp.json()
        # API 设计：{items: [...], cumulative: {...}}
        assert "items" in data
        assert "cumulative" in data
        assert len(data["items"]) == 1
        assert "main_net" in data["items"][0]
        assert data["items"][0]["main_net"] == "120000000"  # str not float
        # 最后一条即累计
        assert data["cumulative"]["main_net"] == "120000000"

    def test_empty_list(self, client: TestClient, mock_adapter: MagicMock) -> None:
        mock_adapter.get_today_money_flow.return_value = []
        resp = client.get("/api/quotes/600519/money_flow/today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        # 空数据累计全 0
        assert data["cumulative"] == {
            "main_net": "0",
            "super_net": "0",
            "big_net": "0",
            "medium_net": "0",
            "small_net": "0",
        }
