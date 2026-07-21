"""回归测试：BACKEND-CAPABILITIES.md §9 记录的三个 API 坑。

1. GET /api/agent/predictions 曾调用不存在的 tracker.list_recent → 恒空
2. GET /api/earnings/scores/{code} 曾访问不存在的 EarningsScore.score → 恒空
3. WSSignalMessage schema 曾定义单数 signal，与实际推送 signals 复数不符
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.earnings.types import EarningsScore, EarningsVerdict

# ---------------------------------------------------------------------------
# 1. /api/agent/predictions
# ---------------------------------------------------------------------------


class _FakeTracker:
    """提供 PredictionTracker.all() 的真实接口。"""

    def all(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        assert status is None
        return [
            {
                "id": 1,
                "code": "600519",
                "name": "贵州茅台",
                "prediction": "突破 1700",
                "direction": "bullish",
                "status": "pending",
                "timeframe": "5d",
            }
        ][:limit]

    def stats(self) -> dict[str, Any]:
        return {
            "total": 10,
            "pending": 4,
            "hit": 3,
            "missed": 2,
            "expired": 1,
            "unverifiable": 0,
            "hit_rate": 0.6,
        }


class TestPredictionsEndpoint:
    def test_returns_tracker_rows(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: _FakeTracker(),
        )
        resp = client.get("/api/agent/predictions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["predictions"][0]["code"] == "600519"
        assert body["predictions"][0]["status"] == "pending"

    def test_tracker_none_returns_empty(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: None,
        )
        resp = client.get("/api/agent/predictions")
        assert resp.status_code == 200
        assert resp.json() == {"predictions": [], "total": 0}


class TestPredictionStatsEndpoint:
    def test_returns_stats(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: _FakeTracker(),
        )
        resp = client.get("/api/agent/predictions/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 10
        assert body["hit"] == 3
        assert body["missed"] == 2
        assert body["pending"] == 4
        assert body["hit_rate"] == 0.6

    def test_tracker_none_returns_zero_stats(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.agent.get_prediction_tracker_safe",
            lambda: None,
        )
        resp = client.get("/api/agent/predictions/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# 2. /api/earnings/scores/{code}
# ---------------------------------------------------------------------------


def _make_score(code: str = "600519") -> EarningsScore:
    return EarningsScore(
        code=code,
        name="贵州茅台",
        period="2026H1",
        predicted_low=Decimal("10"),
        predicted_high=Decimal("20"),
        predicted_mid=Decimal("15"),
        actual_value=Decimal("29800000000"),
        actual_growth=Decimal("18.5"),
        gap_to_mid=Decimal("3.5"),
        gap_to_high=Decimal("-1.5"),
        verdict=EarningsVerdict.BEAT,
        confidence=Decimal("0.8"),
    )


class _FakeEarningsStore:
    """返回真实 EarningsScore dataclass 的假 store（避免跨线程 sqlite）。"""

    def list_scores(
        self,
        period: str | None = None,
        verdict: EarningsVerdict | None = None,
    ) -> list[EarningsScore]:
        return [_make_score()]


class TestEarningsScoresEndpoint:
    def test_returns_real_score_fields(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.earnings._store",
            lambda: _FakeEarningsStore(),
        )

        resp = client.get("/api/earnings/scores/600519")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["code"] == "600519"
        assert item["verdict"] == "beat"
        assert item["confidence"] == "0.8"
        assert item["predicted_mid"] == "15"
        assert item["actual_growth"] == "18.5"
        # 不再存在旧的伪 score 字段
        assert "score" not in item

    def test_other_code_returns_empty(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.earnings._store",
            lambda: _FakeEarningsStore(),
        )

        resp = client.get("/api/earnings/scores/000001")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# 3. WSSignalMessage schema 与实际推送一致（signals 复数）
# ---------------------------------------------------------------------------


class TestWSSignalMessageSchema:
    def test_schema_matches_actual_push(self) -> None:
        from mommy_chaogu.web.schemas import WSSignalMessage

        assert "signals" in WSSignalMessage.model_fields
        assert "signal" not in WSSignalMessage.model_fields

    def test_validates_real_payload(self) -> None:
        from mommy_chaogu.web.mappers import signal_to_out
        from mommy_chaogu.web.schemas import WSSignalMessage

        from .conftest import make_signal

        payload = {
            "type": "signal_triggered",
            "signals": [signal_to_out(make_signal()).model_dump(mode="json")],
        }
        msg = WSSignalMessage.model_validate(payload)
        assert msg.type == "signal_triggered"
        assert len(msg.signals) == 1
        assert msg.signals[0].code == "600519"
