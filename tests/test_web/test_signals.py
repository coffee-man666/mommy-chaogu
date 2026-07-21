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


class TestHistoryFromStore:
    """GET /api/signals/history — #10 结构化库读取（主路径）。"""

    def test_reads_from_store(self, client: TestClient, tmp_path: object) -> None:
        import pathlib
        from datetime import datetime
        from decimal import Decimal

        from mommy_chaogu.signals import SignalStore
        from mommy_chaogu.signals.types import Signal, SignalSeverity
        from mommy_chaogu.web.deps import get_alerter, get_signal_store

        db_path = pathlib.Path("/tmp/test_signals_store.db")
        db_path.unlink(missing_ok=True)
        store = SignalStore(db_path)
        store.insert(
            [
                Signal(
                    timestamp=datetime(2026, 7, 1, 10, 30, 0),
                    code="600519",
                    name="贵州茅台",
                    rule_id="price_change",
                    severity=SignalSeverity.WARNING,
                    title="茅台涨超5%",
                    detail="现价1850 涨6.2%",
                    trigger_value=Decimal("6.2"),
                    threshold_value=Decimal("5.0"),
                )
            ]
        )
        client.app.dependency_overrides[get_signal_store] = lambda: store  # type: ignore[attr-defined]
        # 覆盖 alerter（conftest 的 MagicMock 实例会触发 FastAPI 签名探测 422）
        alerter_mock = MagicMock()
        alerter_mock.log_path = None
        client.app.dependency_overrides[get_alerter] = lambda: alerter_mock  # type: ignore[attr-defined]

        resp = client.get("/api/signals/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "600519"
        assert data[0]["severity"] == "warning"
        assert data[0]["trigger_value"] == "6.2"

        store.close()
        db_path.unlink(missing_ok=True)
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]

    def test_store_empty_falls_back_to_log(self, client: TestClient) -> None:
        """库为空时回退日志解析。"""
        import pathlib

        from mommy_chaogu.signals import SignalStore
        from mommy_chaogu.web.deps import get_alerter, get_signal_store

        # 空 store
        db_path = pathlib.Path("/tmp/test_signals_empty.db")
        db_path.unlink(missing_ok=True)
        store = SignalStore(db_path)
        client.app.dependency_overrides[get_signal_store] = lambda: store  # type: ignore[attr-defined]

        # 配置 alerter 的 log_path 有内容
        log_file = pathlib.Path("/tmp/test_signals_fallback.log")
        log_file.write_text(
            "2026-06-27 14:32:15 [CRITICAL] 600519 茅台 main_flow_threshold: ok\n",
            encoding="utf-8",
        )
        alerter = MagicMock()
        alerter.log_path = log_file
        client.app.dependency_overrides[get_alerter] = lambda: alerter  # type: ignore[attr-defined]

        resp = client.get("/api/signals/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1  # 从日志回退解析
        assert data[0]["code"] == "600519"

        store.close()
        db_path.unlink(missing_ok=True)
        log_file.unlink(missing_ok=True)
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
