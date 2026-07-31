"""/api/setup 路由测试：本机零令牌向导后端。

覆盖：
- 本机 loopback 免令牌可访问 /api/setup/*（local_setup_enabled=True + loopback 对端）
- 远程（非 loopback）无凭证被拒
- 远程 auth 禁用（--allow-unauthenticated-remote 等价：token="" + 非 loopback）仍被拒
- 远程持有效 Bearer 可访问
- 响应不含密钥/文件系统路径
- 校验/保存 mock validate_llm_connection，不发真实网络请求
- 保存写盘 0600 + 热更新 os.environ + 失效 agent 缓存
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from mommy_chaogu.web.app import create_app
from mommy_chaogu.web.background import set_service

from .conftest import make_mock_adapter, make_mock_service

# ---------- helpers ----------


def _make_client(
    *,
    api_token: str = "",
    local_setup_enabled: bool = False,
    loopback: bool = False,
    pairing_digest: str = "",
) -> TestClient:
    """Build a TestClient with mock deps and controllable setup security.

    loopback=True sets the ASGI client tuple to ("127.0.0.1", 12345) via
    Starlette's native ``client`` kwarg, so is_loopback_request() sees a real
    loopback socket peer without any patching.
    """
    set_service(make_mock_service())
    app = create_app(
        api_token=api_token,
        local_setup_enabled=local_setup_enabled,
        pairing_digest=pairing_digest,
    )

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

    client_kw: tuple[str, int] = ("127.0.0.1", 12345) if loopback else ("testclient", 50000)
    return TestClient(app, raise_server_exceptions=False, client=client_kw)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate env so tests never touch real user/project secrets."""
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
    ):
        monkeypatch.setenv(key, "")


# ---------- access control ----------


class TestSetupAccessControl:
    """Verify the loopback-or-credential gate for /api/setup/*."""

    def test_local_loopback_allows_without_token(self) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        r = client.get("/api/setup/status")
        assert r.status_code == 200, r.text

    def test_remote_rejected_without_auth(self) -> None:
        """Default TestClient peer is 'testclient' (non-loopback) → 401."""
        client = _make_client(local_setup_enabled=False)
        for path in ("/api/setup/status", "/api/setup/providers"):
            r = client.get(path)
            assert r.status_code == 401, f"{path} should be rejected"

    def test_remote_rejected_even_if_local_setup_enabled_but_not_loopback(self) -> None:
        """local_setup_enabled=True but non-loopback peer → still 401."""
        client = _make_client(local_setup_enabled=True, loopback=False)
        r = client.get("/api/setup/status")
        assert r.status_code == 401

    def test_auth_disabled_remote_rejects_setup(self) -> None:
        """--allow-unauthenticated-remote equivalent: token='' + non-loopback.

        General APIs are open (auth disabled), but setup must still be closed.
        """
        client = _make_client(api_token="", local_setup_enabled=False)
        # regular API is open (auth disabled)
        assert client.get("/api/health").status_code == 200
        # but setup is not
        r = client.get("/api/setup/status")
        assert r.status_code == 401

    def test_remote_accepted_with_valid_bearer(self) -> None:
        client = _make_client(api_token="owner-secret", local_setup_enabled=False)
        r = client.get(
            "/api/setup/status",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200, r.text

    def test_remote_rejected_with_invalid_bearer(self) -> None:
        client = _make_client(api_token="owner-secret", local_setup_enabled=False)
        r = client.get(
            "/api/setup/status",
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401

    def test_setupfoo_not_treated_as_setup(self) -> None:
        """/api/setupfoo must NOT match the setup prefix — normal API auth applies."""
        # With auth enabled and no token, a non-existent /api/setupfoo path
        # gets the normal 401 (missing owner token), NOT the setup-specific
        # 401 message. This proves _is_setup_path doesn't over-match.
        client = _make_client(api_token="owner-secret", local_setup_enabled=True)
        r = client.get("/api/setupfoo")
        assert r.status_code == 401
        # Normal API auth message, not the setup-specific one.
        assert "owner token" in r.json()["detail"].lower()


class TestStatusAuthMode:
    """auth_mode must reflect the runtime WebSecurity.auth_mode truth source.

    Local CLI intentionally forces api_token="" on loopback even if
    MOMMY_API_TOKEN is configured. status must report the actual runtime state.
    """

    def test_stale_config_token_reports_none_when_runtime_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MOMMY_API_TOKEN in env but runtime token="" (loopback) → mode=none."""
        monkeypatch.setenv("MOMMY_API_TOKEN", "stale-configured-for-remote")
        client = _make_client(
            api_token="",  # runtime: loopback forced it empty
            local_setup_enabled=True,
            loopback=True,
        )
        body = client.get("/api/setup/status").json()
        assert body["auth_mode"] == "none"

    def test_runtime_token_reports_token_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Runtime token set (no pairing digest) → mode=token."""
        monkeypatch.setenv("MOMMY_API_TOKEN", "")
        client = _make_client(
            api_token="owner-secret",  # runtime: explicitly set
            local_setup_enabled=False,
        )
        r = client.get(
            "/api/setup/status",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["auth_mode"] == "token"

    def test_pairing_digest_reports_pairing_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Runtime token + pairing_digest → mode=pairing, not token."""
        from mommy_chaogu.web.security import generate_pairing_code_and_digest

        _, digest = generate_pairing_code_and_digest("owner-secret")
        monkeypatch.setenv("MOMMY_API_TOKEN", "")
        client = _make_client(
            api_token="owner-secret",
            local_setup_enabled=False,
            pairing_digest=digest,
        )
        r = client.get(
            "/api/setup/status",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["auth_mode"] == "pairing"


# ---------- secret-free responses ----------


class TestSecretFreeResponses:
    def test_status_has_no_secrets_or_paths(self) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        body = client.get("/api/setup/status").json()
        text = repr(body)
        assert "api_key" not in text.lower()
        assert ".env" not in text
        assert "credentials.json" not in text
        assert "/" not in body.get("provider", "")  # provider is a bare name
        # expected shape
        assert set(body.keys()) == {
            "auth_mode",
            "llm_configured",
            "provider",
            "model",
            "weixin",
            "data_ok",
        }
        assert set(body["weixin"].keys()) == {"connected", "online"}

    def test_providers_have_no_secrets(self) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        providers = client.get("/api/setup/providers").json()
        assert len(providers) > 0
        for p in providers:
            assert set(p.keys()) == {"id", "label", "default_model", "env_key"}
            # env_key is the *name* of the env var (e.g. DEEPSEEK_API_KEY), not a value

    def test_save_response_never_echoes_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        # mock validate so no network call
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.validate_llm_connection",
            lambda p, m, k: (True, "连接成功"),
        )
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup._write_env_file",
            lambda *a, **kw: None,
        )
        r = client.post(
            "/api/setup/save",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-secret-xyz"},
        )
        assert r.status_code == 200
        body_text = r.text.lower()
        assert "sk-secret-xyz" not in body_text


# ---------- validate ----------


class TestValidate:
    def test_validate_uses_mocked_validator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)

        called: dict[str, object] = {}

        def fake_validate(provider: str, model: str, key: str) -> tuple[bool, str]:
            called["args"] = (provider, model, key)
            return True, "连接成功"

        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.validate_llm_connection",
            fake_validate,
        )
        r = client.post(
            "/api/setup/validate",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "message": "连接成功"}
        assert called["args"] == ("deepseek", "deepseek-chat", "sk-test")

    def test_validate_rejects_unsupported_provider(self) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        r = client.post(
            "/api/setup/validate",
            json={"provider": "bogus", "model": "m", "api_key": "k"},
        )
        assert r.status_code == 422

    def test_validate_rejects_blank_model(self) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        r = client.post(
            "/api/setup/validate",
            json={"provider": "deepseek", "model": "  ", "api_key": "k"},
        )
        assert r.status_code == 422

    def test_validate_rejects_blank_key(self) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        r = client.post(
            "/api/setup/validate",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": ""},
        )
        assert r.status_code == 422

    def test_validate_returns_failure_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.validate_llm_connection",
            lambda p, m, k: (False, "API key 无效或已失效"),
        )
        r = client.post(
            "/api/setup/validate",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "bad"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": False, "message": "API key 无效或已失效"}


# ---------- save ----------


class TestSave:
    def test_save_writes_env_file_and_hot_reloads(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)

        written: dict[str, object] = {}

        def fake_validate(p: str, m: str, k: str) -> tuple[bool, str]:
            return True, "连接成功"

        def fake_write(env_path: Path, provider: str, api_key: str, **kw: object) -> None:
            written["path"] = env_path
            written["provider"] = provider
            written["model"] = kw.get("model")

        monkeypatch.setattr("mommy_chaogu.web.routes.setup.validate_llm_connection", fake_validate)
        monkeypatch.setattr("mommy_chaogu.web.routes.setup._write_env_file", fake_write)

        cleared: list[str] = []
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.reload_agent_caches",
            lambda: cleared.append("called"),
        )

        r = client.post(
            "/api/setup/save",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-real"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # _write_env_file was called with the right provider/model
        assert written["provider"] == "deepseek"
        assert written["model"] == "deepseek-chat"

        # os.environ hot-updated in current process
        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-real"
        assert os.environ.get("AGENT_PROVIDER") == "deepseek"
        assert os.environ.get("AGENT_MODEL") == "deepseek-chat"

        # cache invalidation triggered
        assert cleared == ["called"]

    def test_save_does_not_write_when_validation_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(local_setup_enabled=True, loopback=True)

        write_called: list[bool] = []

        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.validate_llm_connection",
            lambda p, m, k: (False, "API key 无效或已失效"),
        )
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup._write_env_file",
            lambda *a, **kw: write_called.append(True),
        )
        monkeypatch.setattr("mommy_chaogu.web.routes.setup.reload_agent_caches", lambda: None)

        r = client.post(
            "/api/setup/save",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "bad"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert write_called == []  # no write on validation failure

    def test_save_real_0600_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """End-to-end with real _write_env_file on an isolated temp path."""
        env_file = tmp_path / "test.env"

        client = _make_client(local_setup_enabled=True, loopback=True)

        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.validate_llm_connection",
            lambda p, m, k: (True, "连接成功"),
        )
        # Redirect preferred_setup_env_path to our temp file
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.setup.preferred_setup_env_path",
            lambda: env_file,
        )
        monkeypatch.setattr("mommy_chaogu.web.routes.setup.reload_agent_caches", lambda: None)

        r = client.post(
            "/api/setup/save",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-0600"},
        )
        assert r.status_code == 200, r.text

        assert env_file.is_file()
        mode = stat.S_IMODE(env_file.stat().st_mode)
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

        content = env_file.read_text(encoding="utf-8")
        assert "sk-0600" in content
        assert "AGENT_PROVIDER=deepseek" in content
        assert "AGENT_MODEL=deepseek-chat" in content


# ---------- cache invalidation integration ----------


class TestCacheInvalidation:
    def test_reload_agent_caches_clears_targeted_caches(self) -> None:
        """reload_agent_caches should clear get_agent_service + get_memory_service
        + _get_router, but NOT close shared market/adapter resources."""
        from mommy_chaogu.web.deps import (
            get_agent_service,
            get_memory_service,
            reload_agent_caches,
        )
        from mommy_chaogu.web.routes.agent import _get_router

        cleared: list[str] = []

        original_agent_clear = get_agent_service.cache_clear
        original_mem_clear = get_memory_service.cache_clear
        original_router_clear = _get_router.cache_clear

        get_agent_service.cache_clear = lambda: cleared.append("agent")  # type: ignore[method-assign]
        get_memory_service.cache_clear = lambda: cleared.append("memory")  # type: ignore[method-assign]
        _get_router.cache_clear = lambda: cleared.append("router")  # type: ignore[method-assign]

        try:
            reload_agent_caches()
            assert set(cleared) == {"agent", "memory", "router"}
        finally:
            get_agent_service.cache_clear = original_agent_clear  # type: ignore[method-assign]
            get_memory_service.cache_clear = original_mem_clear  # type: ignore[method-assign]
            _get_router.cache_clear = original_router_clear  # type: ignore[method-assign]


# ---------- pure loopback helper ----------


def _make_request(client_host: str | None, scope_extras: dict | None = None) -> Request:
    """Construct a minimal Starlette Request from an ASGI scope dict.

    Tests the real is_loopback_request code path including ipaddress parsing,
    without MagicMock or subprocesses.
    """
    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": (client_host, 50000) if client_host else None,
    }
    if scope_extras:
        scope.update(scope_extras)
    return Request(scope)


class TestIsLoopbackRequest:
    """Unit-test the pure is_loopback_request helper with real Request scopes."""

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
    def test_loopback_addresses(self, host: str) -> None:
        from mommy_chaogu.web.security import is_loopback_request

        assert is_loopback_request(_make_request(host)) is True

    def test_localhost_hostname(self) -> None:
        from mommy_chaogu.web.security import is_loopback_request

        assert is_loopback_request(_make_request("localhost")) is True

    def test_non_loopback_address(self) -> None:
        from mommy_chaogu.web.security import is_loopback_request

        assert is_loopback_request(_make_request("93.184.216.34")) is False

    def test_missing_client(self) -> None:
        from mommy_chaogu.web.security import is_loopback_request

        assert is_loopback_request(_make_request(None)) is False

    def test_x_forwarded_for_does_not_spoof_loopback(self) -> None:
        """A real non-loopback peer with spoofed X-Forwarded-For must stay False."""
        from mommy_chaogu.web.security import is_loopback_request

        request = _make_request(
            "93.184.216.34",
            scope_extras={"headers": [(b"x-forwarded-for", b"127.0.0.1")]},
        )
        assert is_loopback_request(request) is False

    def test_x_forwarded_for_does_not_spoof_non_loopback(self) -> None:
        """A real loopback peer with spoofed X-Forwarded-For must stay True."""
        from mommy_chaogu.web.security import is_loopback_request

        request = _make_request(
            "127.0.0.1",
            scope_extras={"headers": [(b"x-forwarded-for", b"8.8.8.8")]},
        )
        assert is_loopback_request(request) is True
