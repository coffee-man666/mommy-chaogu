"""/api/signals 路由测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class TestRecentSignals:
    """GET /api/signals/recent — 最近一次轮询的信号。"""

    def test_returns_signals(self, client: TestClient) -> None:
        resp = client.get("/api/signals/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "600519"
        assert data[0]["severity"] == "critical"

    def test_signal_has_trigger_value(self, client: TestClient) -> None:
        resp = client.get("/api/signals/recent")
        sig = resp.json()[0]
        assert sig["trigger_value"] == "120000000"  # str
        assert sig["threshold_value"] == "80000000"


class TestHistorySignals:
    """GET /api/signals/history — 从 signals.log 解析。"""

    def test_empty_when_no_log(self, client: TestClient) -> None:
        from mommy_chaogu.web.deps import get_alerter

        alerter = MagicMock()
        alerter.log_path = None
        client.app.dependency_overrides[get_alerter] = lambda: alerter  # type: ignore[attr-defined]

        resp = client.get("/api/signals/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_parses_log_line(self, client: TestClient, tmp_path: object) -> None:
        import pathlib

        from mommy_chaogu.web.deps import get_alerter

        log_file = pathlib.Path("/tmp/test_signals.log")
        log_file.write_text(
            "2026-06-27 14:32:15 [CRITICAL] 600519 贵州茅台 main_flow_threshold: "
            "主力净流入 1.2 亿（阈值 8000 万）\n",
            encoding="utf-8",
        )
        alerter = MagicMock()
        alerter.log_path = log_file
        client.app.dependency_overrides[get_alerter] = lambda: alerter

        resp = client.get("/api/signals/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "600519"
        assert data[0]["severity"] == "critical"
        assert data[0]["rule_id"] == "main_flow_threshold"

        log_file.unlink(missing_ok=True)

    def test_filter_by_rule_id(self, client: TestClient) -> None:
        import pathlib

        from mommy_chaogu.web.deps import get_alerter

        log_file = pathlib.Path("/tmp/test_signals_2.log")
        log_file.write_text(
            "2026-06-27 14:32:15 [CRITICAL] 600519 茅台 main_flow_threshold: a\n"
            "2026-06-27 14:33:00 [WARNING] 000858 五粮液 price_change_threshold: b\n",
            encoding="utf-8",
        )
        alerter = MagicMock()
        alerter.log_path = log_file
        client.app.dependency_overrides[get_alerter] = lambda: alerter

        resp = client.get("/api/signals/history?rule_id=price_change_threshold")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["rule_id"] == "price_change_threshold"

        log_file.unlink(missing_ok=True)

    def test_malformed_lines_skipped(self, client: TestClient) -> None:
        import pathlib

        from mommy_chaogu.web.deps import get_alerter

        log_file = pathlib.Path("/tmp/test_signals_3.log")
        log_file.write_text(
            "garbage line\n"
            "2026-06-27 14:32:15 [CRITICAL] 600519 茅台 main_flow_threshold: ok\n"
            "another bad line\n",
            encoding="utf-8",
        )
        alerter = MagicMock()
        alerter.log_path = log_file
        client.app.dependency_overrides[get_alerter] = lambda: alerter

        resp = client.get("/api/signals/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1  # only the valid line
        log_file.unlink(missing_ok=True)
