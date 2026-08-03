"""/api/stocks/{code}/backtest 路由测试。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.backtest.engine import BacktestResult
from mommy_chaogu.web.deps import get_backtest_engine


def _make_result(total_signals: int = 12) -> BacktestResult:
    if total_signals == 0:
        return BacktestResult(
            total_signals=0,
            winning_signals=0,
            losing_signals=0,
            win_rate=0.0,
            avg_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            signals_detail=[],
        )
    return BacktestResult(
        total_signals=total_signals,
        winning_signals=7,
        losing_signals=5,
        win_rate=7 / total_signals,
        avg_return_pct=1.24,
        max_drawdown_pct=3.5,
        sharpe_ratio=0.42,
        signals_detail=[{"code": "600519"}] * total_signals,
    )


@pytest.fixture()
def fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.run.return_value = _make_result()
    return engine


@pytest.fixture()
def bt_client(client: TestClient, fake_engine: MagicMock) -> TestClient:
    """在公共 client 上覆盖回测引擎依赖。"""
    client.app.dependency_overrides[get_backtest_engine] = lambda: fake_engine
    yield client
    client.app.dependency_overrides.pop(get_backtest_engine, None)


class TestBacktestRoute:
    def test_success_shape(self, bt_client: TestClient, fake_engine: MagicMock) -> None:
        resp = bt_client.get("/api/stocks/600519/backtest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "600519"
        assert body["hold_days"] == 5  # conftest 默认偏好 swing → 5
        assert body["total_signals"] == 12
        assert body["win_rate"] == pytest.approx(0.5833, abs=1e-4)
        assert body["avg_return_pct"] == 1.24
        assert body["max_drawdown_pct"] == 3.5
        assert body["sharpe_ratio"] == 0.42
        assert body["message"] is None
        # 回测窗口：end = 今天，start = 今天 − 365 天
        end = date.fromisoformat(body["end_date"])
        start = date.fromisoformat(body["start_date"])
        assert end == date.today()
        assert (end - start).days == 365

    def test_default_hold_days_follows_preference(
        self,
        bt_client: TestClient,
        fake_engine: MagicMock,
        mock_watchlist_store: MagicMock,
    ) -> None:
        """缺省 hold_days 取服务端偏好的 holding_period 派生值（long → 20）。"""
        prefs = mock_watchlist_store.get_user_preferences.return_value
        prefs["holding_period"] = "long"

        resp = bt_client.get("/api/stocks/600519/backtest")
        assert resp.status_code == 200
        assert resp.json()["hold_days"] == 20
        assert fake_engine.run.call_args.kwargs["hold_days"] == 20

    def test_explicit_hold_days_wins(
        self,
        bt_client: TestClient,
        fake_engine: MagicMock,
        mock_watchlist_store: MagicMock,
    ) -> None:
        """显式 hold_days 覆盖偏好默认值。"""
        prefs = mock_watchlist_store.get_user_preferences.return_value
        prefs["holding_period"] = "long"

        resp = bt_client.get("/api/stocks/600519/backtest?hold_days=10")
        assert resp.status_code == 200
        assert resp.json()["hold_days"] == 10
        assert fake_engine.run.call_args.kwargs["hold_days"] == 10

    def test_invalid_hold_days_422(self, bt_client: TestClient) -> None:
        assert bt_client.get("/api/stocks/600519/backtest?hold_days=0").status_code == 422
        assert bt_client.get("/api/stocks/600519/backtest?hold_days=61").status_code == 422
        assert bt_client.get("/api/stocks/600519/backtest?hold_days=abc").status_code == 422

    def test_invalid_code_422(self, bt_client: TestClient) -> None:
        assert bt_client.get("/api/stocks/abc/backtest").status_code == 422
        assert bt_client.get("/api/stocks/12345/backtest").status_code == 422

    def test_zero_signals_sets_message_and_null_metrics(
        self, bt_client: TestClient, fake_engine: MagicMock
    ) -> None:
        fake_engine.run.return_value = _make_result(total_signals=0)

        resp = bt_client.get("/api/stocks/600519/backtest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_signals"] == 0
        assert body["message"] == "区间内未触发信号或缓存数据不足"
        assert body["win_rate"] is None
        assert body["avg_return_pct"] is None
        assert body["max_drawdown_pct"] is None
        assert body["sharpe_ratio"] is None

    def test_engine_exception_returns_clean_500(
        self, bt_client: TestClient, fake_engine: MagicMock
    ) -> None:
        fake_engine.run.side_effect = RuntimeError("cache corrupt")

        resp = bt_client.get("/api/stocks/600519/backtest")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "回测计算失败，请稍后重试"

    def test_engine_receives_code_and_window(
        self, bt_client: TestClient, fake_engine: MagicMock
    ) -> None:
        bt_client.get("/api/stocks/000858/backtest?hold_days=3")
        args = fake_engine.run.call_args.args
        assert args[0] == ["000858"]
        assert args[1] <= args[2]  # start_date <= end_date
        assert fake_engine.run.call_args.kwargs["hold_days"] == 3
