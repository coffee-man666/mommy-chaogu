"""Web routes 补充测试（PLAN 三档 #12 覆盖率提升）。

覆盖 market._ranking 纯逻辑 + portfolio 路由行为断言。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# market._ranking 纯逻辑（过滤 ST/退市/异常值 + 排序 + 格式化）
# ---------------------------------------------------------------------------


def _make_quote(
    code: str = "600519",
    name: str = "贵州茅台",
    price: Decimal = Decimal("1680"),
    change_pct: float = 5.2,
    change: Decimal = Decimal("80"),
    volume: int = 100000,
    market: str = "SH",
) -> SimpleNamespace:
    """构造一个带 turnover 的假 quote。"""
    return SimpleNamespace(
        code=code,
        name=name,
        price=price,
        change_pct=change_pct,
        change=change,
        volume=volume,
        turnover=SimpleNamespace(amount=Decimal("1000000")),
        market=SimpleNamespace(value=market),
    )


class TestRankingLogic:
    def test_filters_st_stocks(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        quotes = [
            _make_quote(code="600519", name="贵州茅台", change_pct=5.0),
            _make_quote(code="000001", name="ST平安", change_pct=10.0),
        ]
        result = _ranking(quotes, "up", limit=10)
        codes = [r["code"] for r in result]
        assert "600519" in codes
        assert "000001" not in codes

    def test_filters_delisted(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        result = _ranking([_make_quote(code="000002", name="万科退", change_pct=3.0)], "up", 10)
        assert len(result) == 0

    def test_filters_abnormal_pct(self) -> None:
        """涨跌幅 > 11% 视为新上市，过滤。"""
        from mommy_chaogu.web.routes.market import _ranking

        result = _ranking(
            [_make_quote(change_pct=15.0)],
            "up",
            10,  # 15% > 11%
        )
        assert len(result) == 0

    def test_filters_bad_code_length(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        result = _ranking([_make_quote(code="123", name="测试", change_pct=3.0)], "up", 10)
        assert len(result) == 0

    def test_sorts_descending_for_up(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        quotes = [
            _make_quote(code="000001", name="A", change_pct=3.0),
            _make_quote(code="000002", name="B", change_pct=8.0),
            _make_quote(code="000003", name="C", change_pct=5.0),
        ]
        result = _ranking(quotes, "up", limit=10)
        pcts = [float(r["change_pct"]) for r in result]
        assert pcts == sorted(pcts, reverse=True)
        assert pcts[0] == 8.0

    def test_sorts_ascending_for_down(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        quotes = [
            _make_quote(code="000001", name="A", change_pct=-3.0),
            _make_quote(code="000002", name="B", change_pct=-8.0),
            _make_quote(code="000003", name="C", change_pct=-5.0),
        ]
        result = _ranking(quotes, "down", limit=10)
        pcts = [float(r["change_pct"]) for r in result]
        assert pcts == sorted(pcts)  # 最负在前
        assert pcts[0] == -8.0

    def test_limit_applied(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        quotes = [
            _make_quote(code=f"00000{i}", name=f"S{i}", change_pct=float(i)) for i in range(1, 6)
        ]
        result = _ranking(quotes, "up", limit=3)
        assert len(result) == 3

    def test_empty_input(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        assert _ranking([], "up", 10) == []

    def test_output_format(self) -> None:
        from mommy_chaogu.web.routes.market import _ranking

        result = _ranking([_make_quote(code="600519", name="贵州茅台", change_pct=5.2)], "up", 10)
        assert len(result) == 1
        r = result[0]
        assert r["code"] == "600519"
        assert r["name"] == "贵州茅台"
        assert r["change_pct"] == "5.2"
        assert r["market"] == "SH"


# ---------------------------------------------------------------------------
# Portfolio 路由行为
# ---------------------------------------------------------------------------


class TestPortfolioRoutes:
    def test_empty_portfolio(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_portfolio_store

        store = MagicMock()
        store.list_positions.return_value = []
        client.app.dependency_overrides[get_portfolio_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_positions"] == 0
        assert data["positions"] == []
        assert data["total_cost"] == "0"

        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]

    def test_list_positions(self, client: TestClient) -> None:
        from datetime import UTC, datetime

        from mommy_chaogu.portfolio.models import Position
        from mommy_chaogu.web.deps import get_portfolio_store

        pos = Position(
            id=1,
            code="600519",
            name="贵州茅台",
            buy_price="1600",
            shares=100,
            buy_date=None,
            note="测试",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        store = MagicMock()
        store.list_positions.return_value = [pos]
        client.app.dependency_overrides[get_portfolio_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.get("/api/portfolio/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "600519"

        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]

    def test_remove_position_not_found(self, client: TestClient) -> None:
        from mommy_chaogu.portfolio.store import PositionNotFoundError
        from mommy_chaogu.web.deps import get_portfolio_store

        store = MagicMock()
        store.remove_position.side_effect = PositionNotFoundError("not found")
        client.app.dependency_overrides[get_portfolio_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.delete("/api/portfolio/positions/999")
        assert resp.status_code == 404

        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]

    def test_add_position_bad_date(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_portfolio_store

        store = MagicMock()
        client.app.dependency_overrides[get_portfolio_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.post(
            "/api/portfolio/positions",
            json={
                "code": "600519",
                "name": "茅台",
                "buy_price": "1600",
                "shares": 100,
                "buy_date": "not-a-date",
            },
        )
        assert resp.status_code == 400

        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]

    def test_add_position_success(self, client: TestClient) -> None:
        from datetime import UTC, datetime

        from mommy_chaogu.portfolio.models import Position
        from mommy_chaogu.web.deps import get_portfolio_store

        pos = Position(
            id=1,
            code="600519",
            name="贵州茅台",
            buy_price="1600",
            shares=100,
            buy_date=None,
            note=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        store = MagicMock()
        store.add_position.return_value = pos
        client.app.dependency_overrides[get_portfolio_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.post(
            "/api/portfolio/positions",
            json={
                "code": "600519",
                "name": "贵州茅台",
                "buy_price": "1600",
                "shares": 100,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["code"] == "600519"

        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]

    def test_list_adjustments_not_found(self, client: TestClient) -> None:
        from mommy_chaogu.portfolio.store import PositionNotFoundError
        from mommy_chaogu.web.deps import get_portfolio_store

        store = MagicMock()
        store.get_position.side_effect = PositionNotFoundError("not found")
        client.app.dependency_overrides[get_portfolio_store] = lambda: store  # type: ignore[attr-defined]

        resp = client.get("/api/portfolio/positions/999/adjustments")
        assert resp.status_code == 404

        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
