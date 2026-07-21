"""/api/portfolio 路由单测（真实 SQLite 临时库 + mock adapter）。

覆盖 web/routes/portfolio.py 的 5 个端点：
- GET    /api/portfolio                          — 持仓总览（含空仓 / 有持仓 / 价格拉取失败降级）
- GET    /api/portfolio/positions                — 列表
- POST   /api/portfolio/positions                — 新增（含 buy_date 格式校验）
- DELETE /api/portfolio/positions/{id}           — 删除（含 404）
- GET    /api/portfolio/positions/{id}/adjustments — 调整列表（含 404）
- POST   /api/portfolio/positions/{id}/adjustments — 加仓（含 404）
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType
from mommy_chaogu.portfolio.store import PortfolioStore


@pytest.fixture
def portfolio_db(tmp_path: Path) -> Path:
    return tmp_path / "portfolio.db"


@pytest.fixture
def store(portfolio_db: Path) -> PortfolioStore:
    return PortfolioStore(portfolio_db)


def _make_quote(code: str = "600519", price: str = "1680.00") -> Quote:
    return Quote(
        code=code,
        name="贵州茅台",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal(price),
        open=Decimal("1660"),
        high=Decimal("1690"),
        low=Decimal("1655"),
        prev_close=Decimal("1650"),
        change=Decimal("30"),
        change_pct=Decimal("1.82"),
        volume=12345678,
        turnover=Money(Decimal("2000000000"), "CNY"),
        turnover_rate=Decimal("0.98"),
        volume_ratio=Decimal("1.23"),
        pe_dynamic=Decimal("25.6"),
        total_market_cap=Money(Decimal("2100000000000"), "CNY"),
        circulating_market_cap=Money(Decimal("2100000000000"), "CNY"),
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def client_with_store(store: PortfolioStore, mock_adapter: MagicMock) -> TestClient:
    """带真实临时 PortfolioStore 的 client。"""
    from mommy_chaogu.web.app import create_app
    from mommy_chaogu.web.background import set_service
    from mommy_chaogu.web.deps import get_adapter, get_portfolio_store

    set_service(MagicMock())

    app = create_app()
    app.dependency_overrides[get_adapter] = lambda: mock_adapter
    app.dependency_overrides[get_portfolio_store] = lambda: store
    return TestClient(app, raise_server_exceptions=False)


# ---------- GET /api/portfolio ----------


class TestGetPortfolio:
    def test_empty_positions(
        self,
        client_with_store: TestClient,
    ) -> None:
        resp = client_with_store.get("/api/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_positions"] == 0
        assert body["positions"] == []
        assert body["total_cost"] == "0"
        assert body["total_market_value"] is None

    def test_with_positions_and_prices(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
        mock_adapter: MagicMock,
    ) -> None:
        store.add_position(
            code="600519",
            name="贵州茅台",
            buy_price=Decimal("1500"),
            shares=100,
        )
        mock_adapter.get_quote.return_value = _make_quote("600519", "1680")

        resp = client_with_store.get("/api/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_positions"] == 1
        pos = body["positions"][0]
        assert pos["code"] == "600519"
        assert pos["shares"] == 100
        assert pos["avg_cost"] == "1500.0000"
        assert pos["current_price"] == "1680"
        # total_cost = 1500 * 100 = 150000（avg_cost 量化到 4 位小数）
        assert body["total_cost"] == "150000.0000"
        # market_value = 1680 * 100
        assert body["total_market_value"] == "168000"

    def test_adapter_exception_degrades_gracefully(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
        mock_adapter: MagicMock,
    ) -> None:
        """adapter.get_quote 抛异常时，路由应该 catch 并只返回成本。"""
        store.add_position(
            code="600519",
            name="贵州茅台",
            buy_price=Decimal("1500"),
            shares=100,
        )
        mock_adapter.get_quote.side_effect = RuntimeError("network down")

        resp = client_with_store.get("/api/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        # 降级：市场价相关字段为 None，但成本仍在（量化到 4 位小数）
        assert body["total_cost"] == "150000.0000"
        assert body["total_market_value"] is None


# ---------- GET /api/portfolio/positions ----------


class TestListPositions:
    def test_empty(self, client_with_store: TestClient) -> None:
        resp = client_with_store.get("/api/portfolio/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_positions(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
    ) -> None:
        store.add_position("600519", "贵州茅台", Decimal("1500"), 100)
        store.add_position("000858", "五粮液", Decimal("140"), 200)

        resp = client_with_store.get("/api/portfolio/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # 按 code 排序
        assert body[0]["code"] == "000858"
        assert body[1]["code"] == "600519"


# ---------- POST /api/portfolio/positions ----------


class TestAddPosition:
    def test_creates_position(self, client_with_store: TestClient) -> None:
        resp = client_with_store.post(
            "/api/portfolio/positions",
            json={
                "code": "600519",
                "name": "贵州茅台",
                "buy_price": "1500.00",
                "shares": 100,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["code"] == "600519"
        assert body["name"] == "贵州茅台"
        assert body["buy_price"] == "1500.00"
        assert body["shares"] == 100

    def test_with_buy_date(self, client_with_store: TestClient) -> None:
        resp = client_with_store.post(
            "/api/portfolio/positions",
            json={
                "code": "600519",
                "buy_price": "1500",
                "shares": 100,
                "buy_date": "2026-07-01",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["buy_date"] == "2026-07-01"

    def test_invalid_buy_date_400(self, client_with_store: TestClient) -> None:
        resp = client_with_store.post(
            "/api/portfolio/positions",
            json={
                "code": "600519",
                "buy_price": "1500",
                "shares": 100,
                "buy_date": "not-a-date",
            },
        )
        assert resp.status_code == 400
        assert "buy_date" in resp.json()["detail"]


# ---------- DELETE /api/portfolio/positions/{id} ----------


class TestRemovePosition:
    def test_404_when_missing(self, client_with_store: TestClient) -> None:
        resp = client_with_store.delete("/api/portfolio/positions/9999")
        assert resp.status_code == 404

    def test_deletes(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
    ) -> None:
        pos = store.add_position("600519", "贵州茅台", Decimal("1500"), 100)
        resp = client_with_store.delete(f"/api/portfolio/positions/{pos.id}")
        assert resp.status_code == 204
        # 确认已删
        assert store.list_positions() == []


# ---------- GET /api/portfolio/positions/{id}/adjustments ----------


class TestListAdjustments:
    def test_404_when_position_missing(self, client_with_store: TestClient) -> None:
        resp = client_with_store.get("/api/portfolio/positions/9999/adjustments")
        assert resp.status_code == 404

    def test_empty_adjustments(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
    ) -> None:
        pos = store.add_position("600519", "贵州茅台", Decimal("1500"), 100)
        resp = client_with_store.get(f"/api/portfolio/positions/{pos.id}/adjustments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_adjustments(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
    ) -> None:
        pos = store.add_position("600519", "贵州茅台", Decimal("1500"), 100)
        store.add_adjustment(pos.id, "buy", Decimal("1550"), 50)

        resp = client_with_store.get(f"/api/portfolio/positions/{pos.id}/adjustments")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["action"] == "buy"
        assert body[0]["shares"] == 50
        assert body[0]["price"] == "1550"


# ---------- POST /api/portfolio/positions/{id}/adjustments ----------


class TestAddAdjustment:
    def test_404_when_position_missing(self, client_with_store: TestClient) -> None:
        resp = client_with_store.post(
            "/api/portfolio/positions/9999/adjustments",
            json={"action": "buy", "price": "1500", "shares": 10},
        )
        assert resp.status_code == 404

    def test_adds_buy_adjustment(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
    ) -> None:
        pos = store.add_position("600519", "贵州茅台", Decimal("1500"), 100)
        resp = client_with_store.post(
            f"/api/portfolio/positions/{pos.id}/adjustments",
            json={"action": "buy", "price": "1550", "shares": 50},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["action"] == "buy"
        assert body["shares"] == 50
        assert body["price"] == "1550"

    def test_adds_sell_adjustment(
        self,
        client_with_store: TestClient,
        store: PortfolioStore,
    ) -> None:
        pos = store.add_position("600519", "贵州茅台", Decimal("1500"), 100)
        resp = client_with_store.post(
            f"/api/portfolio/positions/{pos.id}/adjustments",
            json={"action": "sell", "price": "1680", "shares": 30, "note": "止盈"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["action"] == "sell"
        assert body["note"] == "止盈"
