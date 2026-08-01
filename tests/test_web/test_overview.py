"""/api/overview 聚合端点测试。

验证：
- 正常返回 5 个区块，各区块独立标记 ok/stale/unavailable
- 部分失败（指数拉不到）不拖垮整页
- 自选股为空时返回空区块，不报错
- 持仓为空时返回空提醒
- 快照未生成时降级为静态自选列表（stale）
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _d(v: str) -> Decimal:
    return Decimal(v)


def _patch_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch fetch_indexes to return the 4 core indexes."""
    from mommy_chaogu.market_data.rankings import IndexQuote

    monkeypatch.setattr(
        "mommy_chaogu.web.routes.overview.fetch_indexes",
        lambda: [
            IndexQuote("sh000001", "上证指数", "1.000001", _d("3100"), _d("0.6"), _d("3080")),
            IndexQuote("sz399001", "深证成指", "0.399001", _d("9500"), _d("-0.3"), _d("9528")),
            IndexQuote("sz399006", "创业板指", "0.399006", _d("1850"), _d("1.2"), _d("1828")),
            IndexQuote("sh000300", "沪深300", "1.000300", _d("3600"), _d("0.4"), _d("3586")),
        ],
    )


class TestOverviewBasic:
    """基本结构测试。"""

    def test_overview_returns_all_blocks(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """正常请求返回 5 个区块。"""
        _patch_indexes(monkeypatch)
        resp = client.get("/api/overview")
        assert resp.status_code == 200
        data = resp.json()
        for block in ("indexes", "watchlist", "portfolio", "themes", "signals"):
            assert block in data

    def test_indexes_only_core_four(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指数只返回 4 个核心，不返回科创50/上证50。"""
        from mommy_chaogu.market_data.rankings import IndexQuote

        monkeypatch.setattr(
            "mommy_chaogu.web.routes.overview.fetch_indexes",
            lambda: [
                IndexQuote("sh000001", "上证指数", "1.000001", _d("3100"), _d("0.6"), _d("3080")),
                IndexQuote("sz399001", "深证成指", "0.399001", _d("9500"), _d("-0.3"), _d("9528")),
                IndexQuote("sz399006", "创业板指", "0.399006", _d("1850"), _d("1.2"), _d("1828")),
                IndexQuote("sh000300", "沪深300", "1.000300", _d("3600"), _d("0.4"), _d("3586")),
                IndexQuote("sh000688", "科创50", "1.000688", _d("720"), _d("-1.0"), _d("727")),
                IndexQuote("sh000016", "上证50", "1.000016", _d("2600"), _d("0.2"), _d("2595")),
            ],
        )
        data = client.get("/api/overview").json()
        names = [i["name"] for i in data["indexes"]["indexes"]]
        assert len(names) == 4
        assert "科创50" not in names
        assert "上证50" not in names

    def test_indexes_block_ok_status(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        assert data["indexes"]["block"]["status"] == "ok"


class TestOverviewWatchlist:
    """自选股区块测试。"""

    def test_watchlist_from_snapshot(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """有快照时从快照返回行情数据。"""
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        wl = data["watchlist"]
        assert wl["total"] == 2
        assert wl["n_up"] == 1
        assert wl["n_down"] == 1
        assert wl["block"]["status"] == "ok"
        assert len(wl["items"]) == 2

    def test_watchlist_empty(
        self,
        client: pytest.fixture,
        mock_service: MagicMock,
        mock_watchlist_store: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无自选股且无快照时返回空。"""
        mock_service.latest_snapshot = None
        mock_watchlist_store.list_entries.return_value = []
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        wl = data["watchlist"]
        assert wl["total"] == 0
        assert wl["items"] == []
        assert wl["block"]["status"] == "ok"

    def test_watchlist_stale_fallback(
        self,
        client: pytest.fixture,
        mock_service: MagicMock,
        mock_watchlist_store: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """快照未生成但有自选股时降级为 stale。"""
        from mommy_chaogu.watchlist.models import Group
        from tests.test_web.conftest import make_stock_entry

        mock_service.latest_snapshot = None
        entry = make_stock_entry("600519", "贵州茅台")
        entry.group = Group(name="持仓", description="")
        mock_watchlist_store.list_entries.return_value = [entry]

        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        wl = data["watchlist"]
        assert wl["block"]["status"] == "stale"
        assert wl["total"] == 1
        assert wl["items"][0]["code"] == "600519"


class TestOverviewPortfolio:
    """持仓区块测试。"""

    def test_portfolio_empty(
        self,
        client: pytest.fixture,
        mock_portfolio_store: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无持仓时返回空提醒。"""
        mock_portfolio_store.list_positions.return_value = []
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        pf = data["portfolio"]
        assert pf["n_positions"] == 0
        assert pf["alerts"] == []
        assert pf["block"]["status"] == "ok"


class TestOverviewPartialFailure:
    """部分失败不拖垮整页。"""

    def test_indexes_fail_but_rest_ok(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指数拉取失败，但其他区块正常。"""

        def _boom() -> list[object]:
            raise RuntimeError("network error")

        monkeypatch.setattr("mommy_chaogu.web.routes.overview.fetch_indexes", _boom)
        data = client.get("/api/overview").json()
        assert data["indexes"]["block"]["status"] == "unavailable"
        assert data["watchlist"]["block"]["status"] == "ok"

    def test_indexes_empty_list(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指数返回空列表。"""
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.overview.fetch_indexes",
            lambda: [],
        )
        data = client.get("/api/overview").json()
        assert data["indexes"]["block"]["status"] == "unavailable"


class TestOverviewThemes:
    """主题区块测试。"""

    def test_themes_loaded(self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        themes = data["themes"]
        assert themes["block"]["status"] in ("ok", "unavailable")
        assert isinstance(themes["items"], list)


class TestOverviewSignals:
    """信号区块测试。"""

    def test_signals_present(self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        sig = data["signals"]
        # conftest mock_service 有 1 个 critical signal
        assert sig["summary"] is not None
        assert sig["summary"]["n_recent"] >= 1

    def test_signals_empty(
        self,
        client: pytest.fixture,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_service.latest_signals = []
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        sig = data["signals"]
        assert sig["summary"] is None


class TestOverviewBlockFailureIsolation:
    """每个区块独立失败不拖垮整页。"""

    def test_watchlist_store_failure(
        self,
        client: pytest.fixture,
        mock_service: MagicMock,
        mock_watchlist_store: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """自选股 store 抛异常 → unavailable，但其他区块正常。"""
        mock_service.latest_snapshot = None
        mock_watchlist_store.list_entries.side_effect = RuntimeError("DB error")
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        assert data["watchlist"]["block"]["status"] == "unavailable"
        assert data["indexes"]["block"]["status"] == "ok"
        assert data["portfolio"]["block"]["status"] == "ok"

    def test_portfolio_store_failure(
        self,
        client: pytest.fixture,
        mock_portfolio_store: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """持仓 store 抛异常 → unavailable，但其他区块正常。"""
        mock_portfolio_store.list_positions.side_effect = RuntimeError("DB error")
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        assert data["portfolio"]["block"]["status"] == "unavailable"
        assert data["indexes"]["block"]["status"] == "ok"
        assert data["watchlist"]["block"]["status"] == "ok"

    def test_signals_failure(
        self,
        client: pytest.fixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """信号构建抛异常 → unavailable，但其他区块正常。"""

        def _boom(service: object | None = None) -> object:
            raise RuntimeError("signal read error")

        monkeypatch.setattr("mommy_chaogu.web.routes.overview._build_signals", _boom)
        _patch_indexes(monkeypatch)
        data = client.get("/api/overview").json()
        assert data["signals"]["block"]["status"] == "unavailable"
        assert data["indexes"]["block"]["status"] == "ok"

    def test_malformed_index_row_isolated(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.overview.fetch_indexes",
            lambda: [object()],
        )

        response = client.get("/api/overview")
        assert response.status_code == 200
        assert response.json()["indexes"]["block"]["status"] == "unavailable"

    def test_malformed_theme_row_isolated(
        self, client: pytest.fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_indexes(monkeypatch)
        monkeypatch.setattr(
            "mommy_chaogu.services.theme_service.ThemeService.list_themes",
            lambda _self: [{"id": "missing-name"}],
        )

        response = client.get("/api/overview")
        assert response.status_code == 200
        assert response.json()["themes"]["block"]["status"] == "unavailable"
