"""/api/setup/weixin 路由测试 + manager 单元测试：微信消息通道 QR 配对后端。

所有测试均为离线：
- 注入/fake WeixinClient (fetch_qr/poll_qr_status)、WeixinStore、gateway 函数
- 不发起真实网络请求、不启动真实 gateway 进程、不写真实文件系统
- 验证响应不含密钥/上游 ID
- 直接 manager 测试使用 asyncio.run / asyncio.gather 验证线程隔离与并发
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.web.app import create_app
from mommy_chaogu.web.background import set_service
from mommy_chaogu.web.weixin_pairing import WeixinPairingManager

from .conftest import make_mock_adapter, make_mock_service


@pytest.fixture(autouse=True)
def _isolate_weixin_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate env so tests never touch real user/project secrets or channel state."""
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(tmp_path / "user-config"))
    monkeypatch.setenv("MOMMY_CHANNEL_STATE_DIR", str(tmp_path / "channel-state"))
    for key in (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "MOONSHOT_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "AGENT_PROVIDER",
        "AGENT_MODEL",
        "MOMMY_API_TOKEN",
    ):
        monkeypatch.setenv(key, "")


# ---------- fakes ----------


class _FakeStore:
    """Minimal in-memory stand-in for WeixinStore."""

    def __init__(self, creds: Any = None) -> None:
        self._creds = creds
        self.saved: list[Any] = []


def _save_credentials(store: _FakeStore, creds: Any) -> None:
    store._creds = creds
    store.saved.append(creds)


def _load_credentials(store: _FakeStore) -> Any:
    return store._creds


class _ScriptedPoller:
    """Returns scripted upstream status dicts, one per poll call."""

    def __init__(self, statuses: list[dict[str, Any]]) -> None:
        self._statuses = list(statuses)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, qrcode_id: str, *, base_url: str = "", verify_code: str = ""
    ) -> dict[str, Any]:
        self.calls.append(
            {"qrcode_id": qrcode_id, "base_url": base_url, "verify_code": verify_code}
        )
        if not self._statuses:
            return {"status": "expired"}
        return self._statuses.pop(0)


def _default_fetch(local_tokens: list[str] | None = None) -> tuple[str, str]:
    return ("qr-id-stub", "weixin://qr/test")


def _default_pid(store: Any) -> int:
    return 12345


_CONFIRMED_RAW = {
    "status": "confirmed",
    "ilink_bot_id": "bot@im.bot",
    "bot_token": "bot-secret",
    "ilink_user_id": "scanner-user",
    "baseurl": "https://redirect.example",
}


def _make_manager(
    *,
    fetch_qr: Any | None = None,
    poll_qr: Any | None = None,
    store: Any | None = None,
    gateway_pid_fn: Any | None = None,
    restart_gateway_fn: Any | None = None,
) -> tuple[WeixinPairingManager, _FakeStore]:
    """Build a manager with fake dependencies for offline testing."""
    if fetch_qr is None:
        fetch_qr = _default_fetch
    if poll_qr is None:
        poll_qr = _ScriptedPoller([_CONFIRMED_RAW])
    if store is None:
        store = _FakeStore()
    if gateway_pid_fn is None:
        gateway_pid_fn = _default_pid
    if restart_gateway_fn is None:
        restart_gateway_fn = MagicMock()

    manager = WeixinPairingManager(
        fetch_qr=fetch_qr,
        poll_qr=poll_qr,
        store=store,
        save_credentials=_save_credentials,
        load_credentials=_load_credentials,
        gateway_pid_fn=gateway_pid_fn,
        restart_gateway_fn=restart_gateway_fn,
    )
    return manager, store


def _make_test_client(manager: WeixinPairingManager) -> TestClient:
    """Build a loopback TestClient with the fake pairing manager injected."""
    set_service(make_mock_service())
    app = create_app(api_token="", local_setup_enabled=True)
    app.state.weixin_pairing = manager

    mock_adapter = make_mock_adapter()
    from mommy_chaogu.web.deps import (
        get_adapter,
        get_alerter,
        get_cache_store,
        get_semicon_store,
        get_watchlist_store,
    )

    mock_semicon = MagicMock()
    mock_semicon.list_all.return_value = []
    app.dependency_overrides[get_adapter] = lambda: mock_adapter
    app.dependency_overrides[get_alerter] = MagicMock()
    app.dependency_overrides[get_watchlist_store] = lambda: MagicMock(
        list_entries=MagicMock(return_value=[])
    )
    app.dependency_overrides[get_cache_store] = lambda: MagicMock(
        get_all_quote_entries=MagicMock(return_value=[])
    )
    app.dependency_overrides[get_semicon_store] = lambda: mock_semicon

    return TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 12345))


# ---------- start endpoint ----------


class TestWeixinStart:
    def test_start_requires_json_to_block_simple_cross_origin_requests(self) -> None:
        fetch_qr = MagicMock(return_value=("qr-id", "weixin://qr/test"))
        manager, _ = _make_manager(fetch_qr=fetch_qr)
        client = _make_test_client(manager)

        r = client.post("/api/setup/weixin/start")
        assert r.status_code == 415
        fetch_qr.assert_not_called()

    def test_start_returns_svg_data_url_and_is_secret_free(self) -> None:
        manager, _ = _make_manager(
            fetch_qr=lambda local_tokens=None: ("qr-secret-id", "weixin://qr/secret-payload")
        )
        client = _make_test_client(manager)

        r = client.post("/api/setup/weixin/start", json={})
        assert r.status_code == 200
        body = r.json()

        assert body["pairing_id"]
        assert body["qr_data_url"].startswith("data:image/svg+xml;base64,")
        assert body["expires_in_seconds"] > 0
        assert body["status"] == "waiting"

        body_text = r.text
        assert "qr-secret-id" not in body_text
        assert "secret-payload" not in body_text
        assert "weixin://qr" not in body_text
        assert "token" not in body_text.lower()

    def test_start_returns_valid_svg_content(self) -> None:
        import base64

        manager, _ = _make_manager()
        client = _make_test_client(manager)

        r = client.post("/api/setup/weixin/start", json={})
        data_url = r.json()["qr_data_url"]
        b64 = data_url.split(",", 1)[1]
        svg = base64.b64decode(b64).decode("utf-8")
        assert svg.startswith("<?xml")
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_start_passes_existing_credential_as_local_token(self) -> None:
        store = _FakeStore(creds=MagicMock(token="existing-bot-token"))

        captured: dict[str, Any] = {}

        def fake_fetch(local_tokens: list[str] | None = None) -> tuple[str, str]:
            captured["local_tokens"] = local_tokens
            return ("qr-id", "weixin://qr/test")

        manager, _ = _make_manager(fetch_qr=fake_fetch, store=store)
        client = _make_test_client(manager)

        client.post("/api/setup/weixin/start", json={})
        assert captured["local_tokens"] == ["existing-bot-token"]


# ---------- poll lifecycle ----------


class TestWeixinPollLifecycle:
    def test_waiting_then_scanned_then_connected(self) -> None:
        poller = _ScriptedPoller(
            [
                {"status": "wait"},
                {"status": "scaned"},
                _CONFIRMED_RAW,
            ]
        )
        manager, _ = _make_manager(poll_qr=poller)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r1 = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r1["status"] == "waiting"

        r2 = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r2["status"] == "scanned"

        r3 = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r3["status"] == "connected"
        assert r3["gateway_online"] is True

    def test_verification_required_then_code_forwarded(self) -> None:
        poller = _ScriptedPoller(
            [
                {"status": "need_verifycode"},
                _CONFIRMED_RAW,
            ]
        )
        manager, _ = _make_manager(poll_qr=poller)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r1 = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r1["status"] == "verification_required"

        r2 = client.post(
            "/api/setup/weixin/poll",
            json={"pairing_id": pid, "verify_code": "1234"},
        ).json()
        assert r2["status"] == "connected"

        assert poller.calls[-1]["verify_code"] == "1234"

    def test_already_connected_binded_redirect(self) -> None:
        # With no local credentials, binded_redirect returns error.
        poller = _ScriptedPoller([{"status": "binded_redirect"}])
        manager, _ = _make_manager(poll_qr=poller)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r["status"] == "error"
        assert "本地" in r["message"] or "没有" in r["message"]

    def test_expired_upstream_status(self) -> None:
        poller = _ScriptedPoller([{"status": "expired"}])
        manager, _ = _make_manager(poll_qr=poller)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r["status"] == "expired"


# ---------- confirmed: credentials saved + gateway ----------


class TestConfirmedCredentialsAndGateway:
    def test_credentials_saved_and_gateway_restarted(self) -> None:
        poller = _ScriptedPoller([_CONFIRMED_RAW])
        restart_fn = MagicMock()
        manager, store = _make_manager(poll_qr=poller, restart_gateway_fn=restart_fn)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r["status"] == "connected"
        assert r["gateway_online"] is True

        assert len(store.saved) == 1
        creds = store.saved[0]
        assert creds.account_id == "bot@im.bot"
        assert creds.token == "bot-secret"
        assert creds.owner_user_id == "scanner-user"
        assert creds.base_url == "https://redirect.example"

        restart_fn.assert_called_once()

    def test_gateway_start_failure_retains_credentials(self) -> None:
        poller = _ScriptedPoller([_CONFIRMED_RAW])
        restart_fn = MagicMock(side_effect=RuntimeError("gateway failed"))
        gateway_pid = MagicMock(return_value=None)
        manager, store = _make_manager(
            poll_qr=poller,
            restart_gateway_fn=restart_fn,
            gateway_pid_fn=gateway_pid,
        )
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r["status"] == "connected"
        assert r["gateway_online"] is False
        assert "暂未上线" in r["message"]

        assert store._creds is not None
        assert store._creds.token == "bot-secret"

    def test_incomplete_credentials_on_confirmed(self) -> None:
        poller = _ScriptedPoller(
            [{"status": "confirmed", "ilink_bot_id": "", "bot_token": "x", "ilink_user_id": "u"}]
        )
        manager, _ = _make_manager(poll_qr=poller)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r["status"] == "error"
        assert "凭据不完整" in r["message"]


# ---------- expired / unknown / capped ----------


class TestExpiredUnknownCapped:
    def test_unknown_pairing_id_returns_expired(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": "nonexistent-id"}).json()
        assert r["status"] == "expired"

    def test_cap_prevents_unbounded_attempts(self) -> None:
        fetch_qr = MagicMock(side_effect=lambda local_tokens=None: ("qr-id", "weixin://qr"))
        manager, _ = _make_manager(
            fetch_qr=fetch_qr,
            poll_qr=_ScriptedPoller([]),
        )
        manager._max_attempts = 3  # type: ignore[attr-defined]
        client = _make_test_client(manager)

        for _ in range(3):
            assert client.post("/api/setup/weixin/start", json={}).status_code == 200

        r = client.post("/api/setup/weixin/start", json={})
        body = r.json()
        assert body["status"] == "error"
        assert body["qr_data_url"] == ""
        assert body["pairing_id"] == ""


# ---------- Fix 1: nonblocking via threadpool ----------


class TestNonblockingThreadpool:
    """Direct async manager test: save/restart/pid/load run on different threads."""

    def test_blocking_ops_run_in_threadpool(self) -> None:
        event_loop_tid = threading.get_ident()
        threads: dict[str, int] = {}

        store = _FakeStore(creds=MagicMock(token="existing"))

        def load_creds(s: Any) -> Any:
            threads["load"] = threading.get_ident()
            return s._creds

        def save_creds(s: Any, c: Any) -> None:
            threads["save"] = threading.get_ident()
            s._creds = c

        def pid_fn(s: Any) -> int | None:
            threads["pid"] = threading.get_ident()
            return 999

        def restart_fn(s: Any) -> None:
            threads["restart"] = threading.get_ident()

        manager = WeixinPairingManager(
            fetch_qr=_default_fetch,
            poll_qr=_ScriptedPoller([_CONFIRMED_RAW]),
            store=store,
            save_credentials=save_creds,
            load_credentials=load_creds,
            gateway_pid_fn=pid_fn,
            restart_gateway_fn=restart_fn,
        )

        async def run() -> None:
            await manager.start()
            # get the pairing_id from the manager
            pid = next(iter(manager._attempts))
            await manager.poll(pid)

        asyncio.run(run())

        assert "load" in threads
        assert "save" in threads
        assert "restart" in threads
        assert "pid" in threads
        for op, tid in threads.items():
            assert tid != event_loop_tid, f"{op} ran on event loop thread"


# ---------- Fix 2: real concurrent poll ----------


class TestRealConcurrentPoll:
    def test_gather_two_polls_one_upstream_call(self) -> None:
        """Two truly concurrent polls (asyncio.gather) for the same attempt.

        Deterministic coordination:
        - Task 1 enters upstream, signals 'entered', blocks on 'release'.
        - We start Task 2, confirm it is pending (waiting for the lock).
        - We set 'release', then gather both.
        - Assert exactly one upstream call and both return the same terminal result.
        No sleeps, no timeout-driven success.
        """
        entered = threading.Event()
        release = threading.Event()
        poll_calls: list[str] = []

        def blocking_poll(
            qrcode_id: str, *, base_url: str = "", verify_code: str = ""
        ) -> dict[str, Any]:
            poll_calls.append(qrcode_id)
            entered.set()
            release.wait()  # block deterministically until released by the test
            return _CONFIRMED_RAW

        manager, _ = _make_manager(poll_qr=blocking_poll)

        async def run() -> list[Any]:
            start = await manager.start()
            pid = start.pairing_id

            # Start poll task 1 — it will enter upstream and block.
            task1 = asyncio.ensure_future(manager.poll(pid))

            # Wait until task 1 has entered the upstream call (running in a
            # threadpool thread). This is deterministic — no sleep.
            while not entered.is_set():
                await asyncio.sleep(0)

            # Start poll task 2 while task 1 is still inside upstream.
            # Task 2 should block on the attempt lock (task 1 holds it).
            task2 = asyncio.ensure_future(manager.poll(pid))
            await asyncio.sleep(0)  # let task 2 be scheduled

            # Task 2 must not have entered upstream yet (lock is held by task 1).
            assert len(poll_calls) == 1

            # Release task 1's upstream call.
            release.set()

            # Gather both — task 1 resolves, task 2 sees cached terminal_result.
            r1, r2 = await asyncio.gather(task1, task2)
            return [r1, r2]

        results = asyncio.run(run())

        assert len(poll_calls) == 1  # exactly one upstream call
        assert all(r.status == "connected" for r in results)
        assert all(r.gateway_online for r in results)


# ---------- Fix 3: verify code one-shot ----------


class TestVerifyCodeOneShot:
    def test_verify_code_not_resent_on_automatic_poll(self) -> None:
        """The submitted verify_code is used for ONE upstream poll only,
        then cleared — never resent on subsequent automatic polls."""
        poller = _ScriptedPoller(
            [
                {"status": "need_verifycode"},
                _CONFIRMED_RAW,
            ]
        )
        manager, _ = _make_manager(poll_qr=poller)

        async def run() -> None:
            start = await manager.start()
            pid = start.pairing_id

            # Poll 1: need_verifycode
            await manager.poll(pid)

            # Poll 2: submit verify_code → confirmed
            await manager.poll(pid, verify_code="5678")

            return [c["verify_code"] for c in poller.calls]

        calls_verify_codes = asyncio.run(run())

        assert calls_verify_codes == ["", "5678"]


# ---------- Fix 4: error secrecy ----------


class TestErrorSecrecy:
    def test_poll_error_returns_fixed_message_not_exception_text(self) -> None:
        sentinel = "SECRET-API-KEY-IN-EXCEPTION-12345"

        class FakeApiError(Exception):
            pass

        def leaking_poll(
            qrcode_id: str, *, base_url: str = "", verify_code: str = ""
        ) -> dict[str, Any]:
            raise FakeApiError(f"auth failed with key={sentinel}")

        manager, _ = _make_manager(poll_qr=leaking_poll)

        async def run() -> Any:
            start = await manager.start()
            return await manager.poll(start.pairing_id)

        result = asyncio.run(run())

        assert result.status == "error"
        assert sentinel not in result.message
        assert "FakeApiError" not in result.message

    def test_weixin_api_error_does_not_leak_str(self) -> None:
        from mommy_chaogu.channels.weixin import WeixinApiError

        sentinel = "SECRET-BOT-TOKEN-IN-ERROR"

        def leaking_poll(
            qrcode_id: str, *, base_url: str = "", verify_code: str = ""
        ) -> dict[str, Any]:
            raise WeixinApiError(f"upstream error containing {sentinel}")

        manager, _ = _make_manager(poll_qr=leaking_poll)

        async def run() -> Any:
            start = await manager.start()
            return await manager.poll(start.pairing_id)

        result = asyncio.run(run())

        assert result.status == "error"
        assert sentinel not in result.message


# ---------- Fix 5: binded_redirect both paths ----------


class TestBindedRedirectPaths:
    def test_binded_redirect_online_no_restart_needed(self) -> None:
        """Usable creds + gateway already online → already_connected, no restart."""
        creds = MagicMock(token="existing", account_id="bot@im.bot")
        store = _FakeStore(creds=creds)
        poller = _ScriptedPoller([{"status": "binded_redirect"}])
        pid_fn = MagicMock(return_value=12345)
        restart_fn = MagicMock()
        manager, _ = _make_manager(
            poll_qr=poller,
            store=store,
            gateway_pid_fn=pid_fn,
            restart_gateway_fn=restart_fn,
        )

        async def run() -> Any:
            start = await manager.start()
            return await manager.poll(start.pairing_id)

        result = asyncio.run(run())
        assert result.status == "already_connected"
        assert result.gateway_online is True
        assert result.gateway_started is False  # was already online, no restart
        restart_fn.assert_not_called()

    def test_binded_redirect_offline_tries_restart_then_rechecks(self) -> None:
        """Usable creds + gateway offline → restart, then recheck PID."""
        creds = MagicMock(token="existing", account_id="bot@im.bot")
        store = _FakeStore(creds=creds)
        poller = _ScriptedPoller([{"status": "binded_redirect"}])
        # First PID check: offline. After restart: online.
        pid_fn = MagicMock(side_effect=[None, 12345])
        restart_fn = MagicMock()
        manager, _ = _make_manager(
            poll_qr=poller,
            store=store,
            gateway_pid_fn=pid_fn,
            restart_gateway_fn=restart_fn,
        )

        async def run() -> Any:
            start = await manager.start()
            return await manager.poll(start.pairing_id)

        result = asyncio.run(run())
        assert result.status == "already_connected"
        assert result.gateway_online is True  # recheck succeeded
        assert result.gateway_started is True  # restart was called
        restart_fn.assert_called_once()

    def test_binded_redirect_offline_restart_fails_reports_offline(self) -> None:
        """Usable creds + gateway offline + restart fails → offline truthfully."""
        creds = MagicMock(token="existing", account_id="bot@im.bot")
        store = _FakeStore(creds=creds)
        poller = _ScriptedPoller([{"status": "binded_redirect"}])
        pid_fn = MagicMock(return_value=None)  # always offline
        restart_fn = MagicMock(side_effect=RuntimeError("cannot start"))
        manager, _ = _make_manager(
            poll_qr=poller,
            store=store,
            gateway_pid_fn=pid_fn,
            restart_gateway_fn=restart_fn,
        )

        async def run() -> Any:
            start = await manager.start()
            return await manager.poll(start.pairing_id)

        result = asyncio.run(run())
        assert result.status == "already_connected"
        assert result.gateway_online is False
        assert result.gateway_started is False  # restart raised, not completed

    def test_binded_redirect_no_creds_returns_error(self) -> None:
        """No usable local credentials → status=error, not already_connected."""
        store = _FakeStore(creds=None)
        poller = _ScriptedPoller([{"status": "binded_redirect"}])
        manager, _ = _make_manager(poll_qr=poller, store=store)

        async def run() -> Any:
            start = await manager.start()
            return await manager.poll(start.pairing_id)

        result = asyncio.run(run())
        assert result.status == "error"
        assert result.gateway_online is False
        assert "本地" in result.message or "没有" in result.message


# ---------- Fix 6: expired terminal/cached ----------


class TestExpiredCaching:
    def test_expired_upstream_status_is_terminal(self) -> None:
        """After upstream returns expired, subsequent polls must NOT call upstream."""
        poller = _ScriptedPoller([{"status": "expired"}])
        manager, _ = _make_manager(poll_qr=poller)

        async def run() -> Any:
            start = await manager.start()
            pid = start.pairing_id
            r1 = await manager.poll(pid)
            r2 = await manager.poll(pid)
            return [r1, r2]

        results = asyncio.run(run())
        assert results[0].status == "expired"
        assert results[1].status == "expired"
        assert len(poller.calls) == 1  # only one upstream call


# ---------- concurrent poll protection (sequential) ----------


class TestConcurrentPollProtection:
    def test_finished_attempt_returns_cached_result(self) -> None:
        poll_count: list[int] = []

        def poll_fn(qrcode_id: str, *, base_url: str = "", verify_code: str = "") -> dict[str, Any]:
            poll_count.append(1)
            return _CONFIRMED_RAW

        manager, _ = _make_manager(poll_qr=poll_fn)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r1 = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r1["status"] == "connected"
        assert len(poll_count) == 1

        r2 = client.post("/api/setup/weixin/poll", json={"pairing_id": pid}).json()
        assert r2["status"] == "connected"
        assert len(poll_count) == 1  # no additional upstream call


# ---------- no auth coupling ----------


class TestNoAuthCoupling:
    def test_qr_flow_does_not_create_web_auth(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)

        client.post("/api/setup/weixin/start", json={})

        status = client.get("/api/setup/status").json()
        assert status["auth_mode"] == "none"
        assert status["weixin"]["connected"] is False

    def test_setup_gate_still_applies_remotely(self) -> None:
        manager, _ = _make_manager()
        set_service(make_mock_service())
        app = create_app(api_token="owner-secret", local_setup_enabled=True)
        app.state.weixin_pairing = manager

        from mommy_chaogu.web.deps import (
            get_adapter,
            get_alerter,
            get_cache_store,
            get_semicon_store,
            get_watchlist_store,
        )

        mock_adapter = make_mock_adapter()
        mock_semicon = MagicMock()
        mock_semicon.list_all.return_value = []
        app.dependency_overrides[get_adapter] = lambda: mock_adapter
        app.dependency_overrides[get_alerter] = MagicMock()
        app.dependency_overrides[get_watchlist_store] = lambda: MagicMock(
            list_entries=MagicMock(return_value=[])
        )
        app.dependency_overrides[get_cache_store] = lambda: MagicMock(
            get_all_quote_entries=MagicMock(return_value=[])
        )
        app.dependency_overrides[get_semicon_store] = lambda: mock_semicon

        remote_client = TestClient(app, raise_server_exceptions=False, client=("testclient", 50000))

        r = remote_client.post("/api/setup/weixin/start", json={})
        assert r.status_code == 401

        r = remote_client.post("/api/setup/weixin/poll", json={"pairing_id": "x"})
        assert r.status_code == 401

    def test_remote_accepted_with_valid_bearer(self) -> None:
        manager, _ = _make_manager()
        set_service(make_mock_service())
        app = create_app(api_token="owner-secret", local_setup_enabled=False)
        app.state.weixin_pairing = manager

        from mommy_chaogu.web.deps import (
            get_adapter,
            get_alerter,
            get_cache_store,
            get_semicon_store,
            get_watchlist_store,
        )

        mock_adapter = make_mock_adapter()
        mock_semicon = MagicMock()
        mock_semicon.list_all.return_value = []
        app.dependency_overrides[get_adapter] = lambda: mock_adapter
        app.dependency_overrides[get_alerter] = MagicMock()
        app.dependency_overrides[get_watchlist_store] = lambda: MagicMock(
            list_entries=MagicMock(return_value=[])
        )
        app.dependency_overrides[get_cache_store] = lambda: MagicMock(
            get_all_quote_entries=MagicMock(return_value=[])
        )
        app.dependency_overrides[get_semicon_store] = lambda: mock_semicon

        remote_client = TestClient(
            app,
            raise_server_exceptions=False,
            client=("testclient", 50000),
        )

        r = remote_client.post(
            "/api/setup/weixin/start",
            json={},
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200


# ---------- response secret-leakage review ----------


class TestSecretLeakage:
    def test_poll_response_contains_no_upstream_secrets(self) -> None:
        poller = _ScriptedPoller([_CONFIRMED_RAW])
        manager, _ = _make_manager(poll_qr=poller)
        client = _make_test_client(manager)

        start = client.post("/api/setup/weixin/start", json={}).json()
        pid = start["pairing_id"]

        r = client.post("/api/setup/weixin/poll", json={"pairing_id": pid})
        body_text = r.text.lower()

        assert "bot-secret" not in body_text
        assert "redirect.example" not in body_text
        assert "scanner-user" not in body_text
        assert "bot@im.bot" not in body_text


# ---------- Fix 7: Pydantic input bounds ----------


class TestInputBounds:
    def test_blank_pairing_id_rejected(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)
        r = client.post("/api/setup/weixin/poll", json={"pairing_id": ""})
        assert r.status_code == 422

    def test_oversized_pairing_id_rejected(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)
        r = client.post("/api/setup/weixin/poll", json={"pairing_id": "x" * 200})
        assert r.status_code == 422

    def test_non_digit_verify_code_rejected(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)
        r = client.post(
            "/api/setup/weixin/poll",
            json={"pairing_id": "valid-id", "verify_code": "abcd"},
        )
        assert r.status_code == 422

    def test_oversized_verify_code_rejected(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)
        r = client.post(
            "/api/setup/weixin/poll",
            json={"pairing_id": "valid-id", "verify_code": "123456789"},
        )
        assert r.status_code == 422

    def test_setup_provider_max_length(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)
        r = client.post(
            "/api/setup/validate",
            json={"provider": "x" * 200, "model": "m", "api_key": "k"},
        )
        assert r.status_code == 422

    def test_setup_blank_provider_rejected(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)
        r = client.post(
            "/api/setup/validate",
            json={"provider": "", "model": "m", "api_key": "k"},
        )
        assert r.status_code == 422


# ---------- status separation ----------


class TestStatusSeparation:
    def test_weixin_status_independent_of_llm_and_auth(self) -> None:
        manager, _ = _make_manager()
        client = _make_test_client(manager)

        status = client.get("/api/setup/status").json()
        assert "auth_mode" in status
        assert "llm_configured" in status
        assert "weixin" in status
        assert set(status["weixin"].keys()) == {"connected", "online"}
        assert status["auth_mode"] == "none"
        assert status["llm_configured"] is False
        assert status["weixin"]["connected"] is False
