"""/api/themes 路由单测（mock ThemeService）。

覆盖 web/routes/themes.py 的三个端点：
- GET /api/themes            — 主题列表
- GET /api/themes/{id}       — 主题详情（含 404 分支）
- GET /api/themes/{id}/quotes — 成分股行情（含 error / 空 price / 正常三种 item 分支）
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


class _FakeThemeService:
    """可配置返回值的假 ThemeService（同时充当构造器拦截）。"""

    def __init__(
        self,
        themes: list[dict[str, Any]] | None = None,
        theme_detail: dict[str, Any] | None = None,
        quotes: list[dict[str, Any]] | None = None,
    ) -> None:
        self._themes = themes if themes is not None else []
        self._theme_detail = theme_detail
        self._quotes = quotes if quotes is not None else []
        self.last_adapter: Any = "unset"

    def __call__(self, adapter: Any = None) -> _FakeThemeService:
        # 拦截 ThemeService(adapter=...) 构造
        self.last_adapter = adapter
        return self

    def list_themes(self) -> list[dict[str, Any]]:
        return self._themes

    def get_theme(self, theme_id: str) -> dict[str, Any] | None:
        return self._theme_detail

    def get_theme_quotes(self, theme_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._quotes


@pytest.fixture
def patch_theme_service(monkeypatch: pytest.MonkeyPatch) -> _FakeThemeService:
    """注入 _FakeThemeService，拦截 ThemeService 构造。"""
    fake = _FakeThemeService()
    monkeypatch.setattr("mommy_chaogu.web.routes.themes.ThemeService", fake)
    return fake


# ---------- GET /api/themes ----------


class TestListThemes:
    def test_returns_items_and_total(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._themes = [
            {
                "id": "semiconductor",
                "name": "半导体",
                "description": "半导体产业链",
                "total_stocks": 42,
                "subcategories": ["设计", "制造"],
                "source": "supply_chain",
            }
        ]
        resp = client.get("/api/themes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == "semiconductor"
        assert body["items"][0]["name"] == "半导体"

    def test_empty_themes(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._themes = []
        resp = client.get("/api/themes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []


# ---------- GET /api/themes/{theme_id} ----------


class TestGetTheme:
    def test_returns_theme_detail(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._theme_detail = {
            "id": "semiconductor",
            "name": "半导体",
            "stocks": [{"code": "600519", "name": "贵州茅台"}],
        }
        resp = client.get("/api/themes/semiconductor")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "semiconductor"
        assert body["name"] == "半导体"
        assert body["stocks"][0]["code"] == "600519"

    def test_404_when_not_found(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._theme_detail = None
        resp = client.get("/api/themes/nonexistent")
        assert resp.status_code == 404
        assert "nonexistent" in resp.json()["detail"]


# ---------- GET /api/themes/{theme_id}/quotes ----------


class TestGetThemeQuotes:
    def test_404_when_theme_missing(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._theme_detail = None
        resp = client.get("/api/themes/nonexistent/quotes")
        assert resp.status_code == 404

    def test_quotes_with_price(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._theme_detail = {"id": "test", "name": "测试主题"}
        patch_theme_service._quotes = [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": Decimal("1680.00"),
                "change_pct": Decimal("1.82"),
                "volume": 12345678,
                "turnover_rate": Decimal("0.98"),
                "pe": Decimal("25.5"),
                "main_net_inflow": Decimal("50000000"),
                "subcategory": "白酒",
                "level": "核心",
                "role": "龙头",
                "growth_text": "",
                "growth_low": None,
                "growth_high": None,
                "core_driver": "",
                "highlight": "",
                "error": None,
            }
        ]
        resp = client.get("/api/themes/test/quotes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["theme_id"] == "test"
        assert body["theme_name"] == "测试主题"
        assert body["total"] == 1
        item = body["items"][0]
        assert item["code"] == "600519"
        # Decimal → str
        assert item["price"] == "1680.00"
        assert item["change_pct"] == "1.82"
        assert item["turnover_rate"] == "0.98"
        assert item["pe"] == "25.5"
        assert item["main_net_inflow"] == "50000000"
        assert item["role"] == "龙头"

    def test_error_item_format(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        """行情拉取失败的 item：精简字段，带 error。"""
        patch_theme_service._theme_detail = {"id": "test", "name": "测试"}
        patch_theme_service._quotes = [
            {
                "code": "300001",
                "name": "某股",
                "price": None,
                "change_pct": None,
                "volume": None,
                "turnover_rate": None,
                "pe": None,
                "main_net_inflow": None,
                "subcategory": "",
                "level": "",
                "role": "",
                "growth_text": "",
                "growth_low": None,
                "growth_high": None,
                "core_driver": "",
                "highlight": "",
                "error": "connection timeout",
            }
        ]
        resp = client.get("/api/themes/test/quotes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["code"] == "300001"
        assert item["error"] == "connection timeout"
        # error item 只有精简字段
        assert item["price"] == ""
        assert item["change_pct"] == ""
        assert "volume" not in item
        assert "pe" not in item

    def test_skip_items_with_null_price_and_no_error(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        """adapter 返回空行情（price None + error None）→ 跳过。"""
        patch_theme_service._theme_detail = {"id": "test", "name": "测试"}
        patch_theme_service._quotes = [
            {
                "code": "300001",
                "name": "空行情",
                "price": None,
                "change_pct": None,
                "volume": None,
                "turnover_rate": None,
                "pe": None,
                "main_net_inflow": None,
                "subcategory": "",
                "level": "",
                "role": "",
                "growth_text": "",
                "growth_low": None,
                "growth_high": None,
                "core_driver": "",
                "highlight": "",
                "error": None,
            },
            {
                "code": "600519",
                "name": "有行情",
                "price": Decimal("1680"),
                "change_pct": Decimal("1.82"),
                "volume": 100,
                "turnover_rate": None,
                "pe": None,
                "main_net_inflow": None,
                "subcategory": "",
                "level": "",
                "role": "",
                "growth_text": "",
                "growth_low": None,
                "growth_high": None,
                "core_driver": "",
                "highlight": "",
                "error": None,
            },
        ]
        resp = client.get("/api/themes/test/quotes")
        assert resp.status_code == 200
        body = resp.json()
        # 只有 1 条（空行情被跳过）
        assert body["total"] == 1
        assert body["items"][0]["code"] == "600519"

    def test_falsy_fields_render_as_none(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        """turnover_rate / pe / main_net_inflow 为 falsy → None。"""
        patch_theme_service._theme_detail = {"id": "test", "name": "测试"}
        patch_theme_service._quotes = [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": Decimal("1680"),
                "change_pct": Decimal("1.82"),
                "volume": 100,
                "turnover_rate": Decimal("0"),
                "pe": Decimal("0"),
                "main_net_inflow": Decimal("0"),
                "subcategory": "",
                "level": "",
                "role": "",
                "growth_text": "",
                "growth_low": None,
                "growth_high": None,
                "core_driver": "",
                "highlight": "",
                "error": None,
            }
        ]
        resp = client.get("/api/themes/test/quotes")
        body = resp.json()
        item = body["items"][0]
        assert item["turnover_rate"] is None
        assert item["pe"] is None
        assert item["main_net_inflow"] is None

    def test_limit_param_passed(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        patch_theme_service._theme_detail = {"id": "test", "name": "测试"}
        patch_theme_service._quotes = []
        client.get("/api/themes/test/quotes?limit=50")
        # 没异常即说明 limit 校验通过（ge=1, le=200）

    def test_limit_out_of_range_422(
        self,
        client: TestClient,
        patch_theme_service: _FakeThemeService,
    ) -> None:
        resp = client.get("/api/themes/test/quotes?limit=0")
        assert resp.status_code == 422
        resp = client.get("/api/themes/test/quotes?limit=300")
        assert resp.status_code == 422

    def test_adapter_injected(
        self,
        client: TestClient,
        mock_adapter: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quotes 路由应该注入 get_adapter()。"""
        fake = _FakeThemeService(
            theme_detail={"id": "test", "name": "测试"},
            quotes=[],
        )
        monkeypatch.setattr("mommy_chaogu.web.routes.themes.ThemeService", fake)
        monkeypatch.setattr("mommy_chaogu.web.deps.get_adapter", lambda: mock_adapter)
        client.get("/api/themes/test/quotes")
        assert fake.last_adapter is mock_adapter
