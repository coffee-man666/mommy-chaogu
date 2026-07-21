"""/api/earnings 路由单测（mock EarningsStore）。

覆盖 web/routes/earnings.py：
- GET /api/earnings/calendar       — 财报日历（含异常降级）
- GET /api/earnings/stock/{code}   — 个股业绩（含 limit / 不匹配 / 异常降级）
- GET /api/earnings/scores/{code}  — 评分异常降级路径

注：/scores 的正常路径已在 test_api_pitfalls.py 覆盖。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.earnings.types import (
    EarningsCalendar,
    EarningsScore,
    EarningsVerdict,
)

# ---------- helpers ----------


def _make_calendar(
    code: str = "600519",
    name: str = "贵州茅台",
    period: str = "2026H1",
) -> EarningsCalendar:
    return EarningsCalendar(
        code=code,
        name=name,
        period=period,
        disclosure_date=date(2026, 8, 15),
        is_estimated=False,
        source="交易所公告",
    )


def _make_actual(code: str = "600519") -> SimpleNamespace:
    """个股业绩假对象。

    路由层访问的字段（code/name/period/report_date/revenue/revenue_yoy/
    net_profit/net_profit_yoy/eps）未必全在 EarningsActual dataclass 上，
    这里用 SimpleNamespace 提供路由实际读取的全部字段以走通序列化分支。
    """
    return SimpleNamespace(
        code=code,
        name="贵州茅台",
        period="2026H1",
        report_date=date(2026, 8, 15),
        revenue=Decimal("700000000000"),
        revenue_yoy=Decimal("15.3"),
        net_profit=Decimal("300000000000"),
        net_profit_yoy=Decimal("18.5"),
        eps=Decimal("23.8"),
    )


def _make_score(code: str = "600519") -> EarningsScore:
    return EarningsScore(
        code=code,
        name="贵州茅台",
        period="2026H1",
        predicted_low=Decimal("10"),
        predicted_high=Decimal("20"),
        predicted_mid=Decimal("15"),
        actual_value=Decimal("300000000000"),
        actual_growth=Decimal("18.5"),
        gap_to_mid=Decimal("3.5"),
        gap_to_high=Decimal("-1.5"),
        verdict=EarningsVerdict.BEAT,
        confidence=Decimal("0.8"),
    )


class _FakeStore:
    """可配置的假 EarningsStore。"""

    def __init__(
        self,
        calendars: list[EarningsCalendar] | None = None,
        actuals: list[Any] | None = None,
        scores: list[EarningsScore] | None = None,
        raise_on_calendars: bool = False,
        raise_on_actuals: bool = False,
        raise_on_scores: bool = False,
    ) -> None:
        self._calendars = calendars or []
        self._actuals = actuals or []
        self._scores = scores or []
        self._raise_on_calendars = raise_on_calendars
        self._raise_on_actuals = raise_on_actuals
        self._raise_on_scores = raise_on_scores

    def list_calendars(
        self,
        since_date: str | None = None,
        period: str | None = None,
        days_ahead: int | None = None,
    ) -> list[EarningsCalendar]:
        if self._raise_on_calendars:
            raise RuntimeError("calendar db locked")
        return self._calendars

    def list_actuals(self, period: str | None = None, since_date: str | None = None) -> list[Any]:
        if self._raise_on_actuals:
            raise RuntimeError("actuals db locked")
        return self._actuals

    def list_scores(
        self,
        period: str | None = None,
        verdict: EarningsVerdict | None = None,
    ) -> list[EarningsScore]:
        if self._raise_on_scores:
            raise RuntimeError("scores db locked")
        return self._scores


@pytest.fixture
def patch_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """提供一个可配置的 _store 替换函数（绕过 lru_cache）。"""

    holder: dict[str, Any] = {"store": None}

    def _factory(store: _FakeStore) -> None:
        holder["store"] = store

    def _fake_store() -> _FakeStore:
        assert holder["store"] is not None, "test forgot to call factory"
        return holder["store"]

    monkeypatch.setattr("mommy_chaogu.web.routes.earnings._store", _fake_store)
    return _factory


# ---------- GET /api/earnings/calendar ----------


class TestGetCalendar:
    def test_returns_calendars(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        store = _FakeStore(calendars=[_make_calendar("600519", "贵州茅台")])
        patch_store(store)

        resp = client.get("/api/earnings/calendar")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["code"] == "600519"
        assert item["name"] == "贵州茅台"
        assert item["period"] == "2026H1"
        assert item["disclosure_date"] == "2026-08-15"
        assert item["is_estimated"] is False
        assert item["source"] == "交易所公告"

    def test_limit_truncates(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        cals = [
            EarningsCalendar(
                code=f"60000{i}",
                name=f"股{i}",
                period="2026H1",
                disclosure_date=date(2026, 8, i + 1),
                is_estimated=False,
                source="src",
            )
            for i in range(5)
        ]
        patch_store(_FakeStore(calendars=cals))

        resp = client.get("/api/earnings/calendar?limit=3")
        body = resp.json()
        assert body["total"] == 3

    def test_passes_since_and_days_ahead(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        store = _FakeStore(calendars=[_make_calendar()])
        patch_store(store)
        resp = client.get("/api/earnings/calendar?since=2026-08-01&days_ahead=30")
        assert resp.status_code == 200

    def test_exception_returns_empty(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        patch_store(_FakeStore(raise_on_calendars=True))
        resp = client.get("/api/earnings/calendar")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_empty_calendars(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        patch_store(_FakeStore(calendars=[]))
        resp = client.get("/api/earnings/calendar")
        assert resp.json() == {"items": [], "total": 0}


# ---------- GET /api/earnings/stock/{code} ----------


class TestGetStockEarnings:
    def test_returns_actuals_for_code(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        patch_store(_FakeStore(actuals=[_make_actual("600519"), _make_actual("000001")]))
        resp = client.get("/api/earnings/stock/600519")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["code"] == "600519"
        assert item["name"] == "贵州茅台"
        assert item["period"] == "2026H1"
        assert item["report_date"] == "2026-08-15"
        # Decimal → str
        assert item["revenue"] == "700000000000"
        assert item["revenue_yoy"] == "15.3"
        assert item["net_profit"] == "300000000000"
        assert item["net_profit_yoy"] == "18.5"
        assert item["eps"] == "23.8"

    def test_non_matching_code_returns_empty(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        patch_store(_FakeStore(actuals=[_make_actual("600519")]))
        resp = client.get("/api/earnings/stock/000001")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_limit_truncates(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        actuals = [
            SimpleNamespace(
                code="600519",
                name="贵州茅台",
                period=f"2026Q{i}",
                report_date=date(2026, i + 1, 1),
                revenue=Decimal("100"),
                revenue_yoy=Decimal("1"),
                net_profit=Decimal("50"),
                net_profit_yoy=Decimal("2"),
                eps=Decimal("1"),
            )
            for i in range(1, 5)
        ]
        patch_store(_FakeStore(actuals=actuals))
        resp = client.get("/api/earnings/stock/600519?limit=2")
        body = resp.json()
        assert body["total"] == 2

    def test_exception_returns_empty(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        patch_store(_FakeStore(raise_on_actuals=True))
        resp = client.get("/api/earnings/stock/600519")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_none_fields_become_none(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        """revenue_yoy/net_profit_yoy/eps/report_date 为 None 时输出 None。"""
        patch_store(
            _FakeStore(
                actuals=[
                    SimpleNamespace(
                        code="600519",
                        name="贵州茅台",
                        period="2026H1",
                        report_date=None,
                        revenue=None,
                        revenue_yoy=None,
                        net_profit=None,
                        net_profit_yoy=None,
                        eps=None,
                    )
                ]
            )
        )
        resp = client.get("/api/earnings/stock/600519")
        body = resp.json()
        item = body["items"][0]
        assert item["report_date"] is None
        assert item["revenue"] is None
        assert item["revenue_yoy"] is None
        assert item["net_profit"] is None
        assert item["net_profit_yoy"] is None
        assert item["eps"] is None


# ---------- GET /api/earnings/scores/{code} (异常降级) ----------


class TestGetScoresDegraded:
    def test_exception_returns_empty(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        patch_store(_FakeStore(raise_on_scores=True))
        resp = client.get("/api/earnings/scores/600519")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_none_growth_renders_as_none(
        self,
        client: TestClient,
        patch_store: Any,
    ) -> None:
        """actual_growth / gap_to_* 为 None 时输出 None。"""
        score = EarningsScore(
            code="600519",
            name="贵州茅台",
            period="2026H1",
            predicted_low=Decimal("10"),
            predicted_high=Decimal("20"),
            predicted_mid=Decimal("15"),
            actual_value=Decimal("300000000000"),
            actual_growth=None,
            gap_to_mid=None,
            gap_to_high=None,
            verdict=EarningsVerdict.UNKNOWN,
            confidence=Decimal("0.5"),
        )
        patch_store(_FakeStore(scores=[score]))
        resp = client.get("/api/earnings/scores/600519")
        body = resp.json()
        item = body["items"][0]
        assert item["actual_growth"] is None
        assert item["gap_to_mid"] is None
        assert item["gap_to_high"] is None
        assert item["verdict"] == "unknown"
