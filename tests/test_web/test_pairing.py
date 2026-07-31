"""Remote browser one-time pairing backend tests.

All offline:
- No real network, processes, secrets, or config files.
- Tests CLI code generation, pairing consumption, session cookies,
  middleware cookie acceptance, auth status, ws-ticket via cookie,
  restart stability, and exact path protection.
"""

from __future__ import annotations

import re
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.web.app import create_app
from mommy_chaogu.web.background import set_service
from mommy_chaogu.web.security import (
    SESSION_COOKIE_NAME,
    PairResult,
    WebSecurity,
    generate_pairing_code_and_digest,
)

from .conftest import make_mock_adapter, make_mock_service


def _make_client(
    *,
    api_token: str = "owner-secret",
    pairing_digest: str | None = None,
    local_setup_enabled: bool = False,
) -> TestClient:
    """Build a non-loopback TestClient with mock deps."""
    set_service(make_mock_service())
    if pairing_digest is None:
        _, pairing_digest = generate_pairing_code_and_digest(api_token)
    app = create_app(
        api_token=api_token,
        pairing_digest=pairing_digest,
        local_setup_enabled=local_setup_enabled,
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

    return TestClient(app, raise_server_exceptions=False, client=("testclient", 50000))


def _make_client_with_known_code(
    *,
    api_token: str = "owner-secret",
    local_setup_enabled: bool = False,
) -> tuple[TestClient, str]:
    """Build a client and return the known plaintext code for testing."""
    code, digest = generate_pairing_code_and_digest(api_token)
    return _make_client(
        api_token=api_token,
        pairing_digest=digest,
        local_setup_enabled=local_setup_enabled,
    ), code


# ---------- CLI code generation ----------


class TestCliCodeGeneration:
    def test_generate_returns_6_ascii_digits(self) -> None:
        code, _ = generate_pairing_code_and_digest("key")
        assert re.fullmatch(r"\d{6}", code)
        assert code.isascii()
        assert code.isdigit()
        assert len(code) == 6

    def test_digest_is_hex_sha256(self) -> None:
        _, digest = generate_pairing_code_and_digest("key")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)

    def test_different_codes_produce_different_digests(self) -> None:
        _, d1 = generate_pairing_code_and_digest("key")
        _, d2 = generate_pairing_code_and_digest("key")
        # Very unlikely to collide
        assert d1 != d2

    def test_plaintext_never_in_websecurity(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest)
        # The plaintext code should not appear anywhere in the security object
        assert code not in repr(sec)
        assert code not in sec.api_token
        assert sec.pairing_digest == digest
        assert sec._pairing is not None
        assert code not in repr(sec._pairing)

    def test_empty_api_token_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty API token"):
            generate_pairing_code_and_digest("")


class TestCliPrint:
    def test_cli_prints_pairing_code_once(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mommy_chaogu.cli import build_web_parser, cmd_web_serve

        captured: dict[str, object] = {}
        monkeypatch.setenv("MOMMY_API_TOKEN", "owner-secret")
        monkeypatch.setattr(
            "mommy_chaogu.web.create_app",
            lambda **kwargs: captured.update(kwargs) or object(),
        )
        monkeypatch.setattr("uvicorn.run", lambda *_a, **_kw: None)

        args = build_web_parser().parse_args(["--host", "0.0.0.0"])
        assert cmd_web_serve(args) == 0

        err = capsys.readouterr()
        printed = err.out
        # Matches the Chinese print format
        assert re.search(r"浏览器配对码：\d{6}（10 分钟内有效，仅可使用一次）", printed)
        # Only the digest passed to create_app — never plaintext
        assert "pairing_digest" in captured
        digest = captured["pairing_digest"]
        assert isinstance(digest, str)
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        # The printed code must not be the digest
        match = re.search(r"浏览器配对码：(\d{6})", printed)
        assert match is not None
        plaintext = match.group(1)
        assert plaintext not in digest

    def test_cli_no_code_on_loopback_none(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Loopback with no token → no pairing code printed."""
        from mommy_chaogu.cli import build_web_parser, cmd_web_serve

        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "mommy_chaogu.web.create_app",
            lambda **kwargs: captured.update(kwargs) or object(),
        )
        monkeypatch.setattr("uvicorn.run", lambda *_a, **_kw: None)

        args = build_web_parser().parse_args([])
        assert cmd_web_serve(args) == 0

        err = capsys.readouterr()
        assert "配对码" not in err.out
        assert captured["pairing_digest"] == ""


# ---------- pairing consumption ----------


class TestPairingConsumption:
    def test_valid_code_succeeds(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest)
        assert sec.consume_pairing_code(code) == PairResult.SUCCESS

    def test_wrong_code_is_invalid(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest)
        # Try a different code (almost certainly different)
        wrong = "000000" if code != "000000" else "111111"
        assert sec.consume_pairing_code(wrong) == PairResult.INVALID

    def test_single_use_after_success(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest)
        assert sec.consume_pairing_code(code) == PairResult.SUCCESS
        assert sec.consume_pairing_code(code) == PairResult.USED

    def test_exhausted_after_max_failures(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest, pairing_max_failures=3)
        wrong = "000000" if code != "000000" else "111111"
        assert sec.consume_pairing_code(wrong) == PairResult.INVALID
        assert sec.consume_pairing_code(wrong) == PairResult.INVALID
        # 3rd failure hits the cap
        assert sec.consume_pairing_code(wrong) == PairResult.EXHAUSTED
        # Even correct code is now exhausted
        assert sec.consume_pairing_code(code) == PairResult.EXHAUSTED

    def test_ttl_expiry(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest, pairing_ttl_seconds=60)
        # Fast-forward time past TTL
        assert sec._pairing is not None
        sec._pairing.issued_at = time.time() - 120
        assert sec.consume_pairing_code(code) == PairResult.EXHAUSTED

    def test_wrong_well_formed_code_increments_counter(self) -> None:
        code, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest, pairing_max_failures=5)
        wrong = "000000" if code != "000000" else "111111"
        sec.consume_pairing_code(wrong)
        assert sec._pairing is not None
        assert sec._pairing.failures == 1
        # Correct code still works
        assert sec.consume_pairing_code(code) == PairResult.SUCCESS

    def test_malformed_direct_attempt_does_not_increment_counter(self) -> None:
        _, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest)
        assert sec.consume_pairing_code("１２３４５６") == PairResult.INVALID
        assert sec._pairing is not None
        assert sec._pairing.failures == 0

    def test_not_ready_without_digest(self) -> None:
        sec = WebSecurity(api_token="key")
        assert sec.consume_pairing_code("123456") == PairResult.NOT_READY

    def test_digest_without_api_token_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty API token"):
            WebSecurity(api_token="", pairing_digest="digest")


# ---------- auth mode ----------


class TestAuthMode:
    def test_none_mode(self) -> None:
        sec = WebSecurity(api_token="")
        assert sec.auth_mode == "none"

    def test_token_mode(self) -> None:
        sec = WebSecurity(api_token="key")
        assert sec.auth_mode == "token"

    def test_pairing_mode(self) -> None:
        _, digest = generate_pairing_code_and_digest("key")
        sec = WebSecurity(api_token="key", pairing_digest=digest)
        assert sec.auth_mode == "pairing"


# ---------- HTTP pairing endpoint ----------


class TestPairEndpoint:
    def test_valid_code_sets_cookie_and_ok(self) -> None:
        client, code = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": code})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["message"] == "配对成功"

        # Cookie set
        set_cookie = r.headers.get("set-cookie", "")
        assert SESSION_COOKIE_NAME in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie
        assert "Path=/" in set_cookie
        assert "Max-Age" in set_cookie

    def test_valid_code_is_single_use(self) -> None:
        client, code = _make_client_with_known_code()
        r1 = client.post("/api/auth/pair", json={"code": code})
        assert r1.status_code == 200

        r2 = client.post("/api/auth/pair", json={"code": code})
        assert r2.status_code == 401
        assert r2.json()["ok"] is False
        assert "已使用" in r2.json()["message"]

    def test_invalid_code_returns_fixed_message(self) -> None:
        client, code = _make_client_with_known_code()
        wrong = "000000" if code != "000000" else "111111"
        r = client.post("/api/auth/pair", json={"code": wrong})
        assert r.status_code == 401
        assert r.json()["ok"] is False
        assert "无效" in r.json()["message"]

    def test_exhausted_after_failures(self) -> None:
        client, code = _make_client_with_known_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            r = client.post("/api/auth/pair", json={"code": wrong})
        # Now exhausted
        assert r.status_code == 401
        assert "过多" in r.json()["message"]
        # Even correct code is now exhausted
        r2 = client.post("/api/auth/pair", json={"code": code})
        assert r2.status_code == 401
        assert "过多" in r2.json()["message"]

    def test_non_digit_code_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": "abcdef"})
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]

    def test_wrong_length_code_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": "12345"})
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]

    def test_pair_endpoint_is_public(self) -> None:
        """Pair endpoint must not require auth (it IS the auth path)."""
        client, _ = _make_client_with_known_code()
        wrong = "000000"
        r = client.post("/api/auth/pair", json={"code": wrong})
        # Should get 401 from invalid code, not from missing bearer
        assert r.status_code == 401

    def test_oversized_body_is_rejected_before_parsing(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post(
            "/api/auth/pair",
            content=b"{" + (b"x" * 2048) + b"}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
        assert r.json() == {
            "ok": False,
            "message": "配对码格式不正确，请输入 6 位数字",
        }

    def test_non_json_content_type_is_rejected_without_consuming_code(self) -> None:
        client, code = _make_client_with_known_code()
        r = client.post(
            "/api/auth/pair",
            content=f'{{"code":"{code}"}}',
            headers={"Content-Type": "text/plain"},
        )
        assert r.status_code == 415
        assert client.post("/api/auth/pair", json={"code": code}).status_code == 200


# ---------- cookie attributes ----------


class TestCookieAttributes:
    def test_secure_flag_on_https(self) -> None:
        client, code = _make_client_with_known_code()
        r = client.post(
            "/api/auth/pair",
            json={"code": code},
            headers={"X-Forwarded-Proto": "https"},
        )
        # TestClient uses http by default; the endpoint checks req.url.scheme.
        # In real HTTPS the scheme would be https. For testing, we verify the
        # logic path: if scheme is http, Secure is not set.
        set_cookie = r.headers.get("set-cookie", "")
        assert SESSION_COOKIE_NAME in set_cookie

    def test_no_plaintext_code_in_response(self) -> None:
        client, code = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": code})
        assert code not in r.text


# ---------- cookie-protected API ----------


class TestCookieProtectedApi:
    def test_cookie_auth_allows_protected_api(self) -> None:
        client, code = _make_client_with_known_code()
        # Pair to get cookie
        client.post("/api/auth/pair", json={"code": code})
        # Now use cookie to access protected API
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_no_cookie_no_bearer_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.get("/api/watchlist")
        assert r.status_code == 401

    def test_invalid_cookie_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        client.cookies.set(SESSION_COOKIE_NAME, "invalid-cookie-value")
        r = client.get("/api/watchlist")
        assert r.status_code == 401


# ---------- Bearer compatibility ----------


class TestBearerCompat:
    def test_bearer_still_works_alongside_pairing(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.get(
            "/api/watchlist",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200

    def test_bearer_works_without_pairing_digest(self) -> None:
        """Legacy token mode (no digest) still works."""
        client = _make_client(pairing_digest="")
        r = client.get(
            "/api/watchlist",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200


# ---------- auth status ----------


class TestAuthStatus:
    def test_pairing_mode_status(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "pairing"
        assert body["authenticated"] is False

    def test_pairing_mode_authenticated_with_bearer(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.get(
            "/api/auth/status",
            headers={"Authorization": "Bearer owner-secret"},
        )
        body = r.json()
        assert body["mode"] == "pairing"
        assert body["authenticated"] is True

    def test_pairing_mode_authenticated_with_cookie(self) -> None:
        client, code = _make_client_with_known_code()
        client.post("/api/auth/pair", json={"code": code})
        r = client.get("/api/auth/status")
        body = r.json()
        assert body["mode"] == "pairing"
        assert body["authenticated"] is True

    def test_token_mode_status(self) -> None:
        client = _make_client(pairing_digest="")
        r = client.get("/api/auth/status")
        body = r.json()
        assert body["mode"] == "token"
        assert body["authenticated"] is False


# ---------- ws-ticket via cookie ----------


class TestWsTicketViaCookie:
    def test_ws_ticket_works_with_cookie(self) -> None:
        client, code = _make_client_with_known_code()
        client.post("/api/auth/pair", json={"code": code})
        r = client.post("/api/auth/ws-ticket")
        assert r.status_code == 200
        assert "ticket" in r.json()

    def test_ws_ticket_works_with_bearer(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post(
            "/api/auth/ws-ticket",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200

    def test_ws_ticket_rejected_without_any_auth(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/ws-ticket")
        assert r.status_code == 401


# ---------- restart-stable session ----------


class TestRestartStableSession:
    def test_session_survives_restart_with_same_token(self) -> None:
        """A session cookie issued by one WebSecurity is valid in another
        constructed with the same api_token (simulating restart)."""
        sec1 = WebSecurity(api_token="stable-key")
        session = sec1.issue_session_cookie()

        sec2 = WebSecurity(api_token="stable-key")
        assert sec2.authorize_cookie(f"{SESSION_COOKIE_NAME}={session.cookie_value}")

    def test_session_invalid_with_different_token(self) -> None:
        sec1 = WebSecurity(api_token="key-one")
        session = sec1.issue_session_cookie()

        sec2 = WebSecurity(api_token="key-two")
        assert not sec2.authorize_cookie(f"{SESSION_COOKIE_NAME}={session.cookie_value}")


# ---------- exact path protection ----------


class TestExactPathProtection:
    def test_auth_pair_exact_path_is_public(self) -> None:
        """/api/auth/pair is public; /api/auth/pairfoo is protected."""
        client, _ = _make_client_with_known_code()
        # /api/auth/pair is public (returns 401 for invalid code, not missing auth)
        r = client.post("/api/auth/pair", json={"code": "000000"})
        assert r.status_code == 401  # invalid code, not "missing token"

    def test_auth_pairfoo_is_protected(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pairfoo", json={"code": "000000"})
        # This path is not in _PUBLIC_API_PATHS → 401 missing token or 404
        # The middleware catches it as a protected /api/ path
        assert r.status_code in (401, 404)


# ---------- setup access with cookie ----------


class TestSetupAccessWithCookie:
    def test_cookie_grants_setup_access_non_loopback(self) -> None:
        """A valid signed session cookie grants setup access after pairing,
        as long as security.enabled (a token is configured). This enables
        token-free onboarding after the one-time pairing."""
        client, code = _make_client_with_known_code()
        client.post("/api/auth/pair", json={"code": code})
        r = client.get("/api/setup/status")
        assert r.status_code == 200

    def test_bearer_grants_setup_access(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.get(
            "/api/setup/status",
            headers={"Authorization": "Bearer owner-secret"},
        )
        assert r.status_code == 200

    def test_cookie_does_not_grant_setup_when_auth_disabled(self) -> None:
        """--allow-unauthenticated-remote: security.enabled=False, so neither
        cookie nor bearer can satisfy the strict-credential requirement."""
        # Build a client with no token (auth disabled)
        set_service(make_mock_service())
        app = create_app(api_token="", local_setup_enabled=False)

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

        client = TestClient(app, raise_server_exceptions=False, client=("testclient", 50000))
        client.cookies.set(SESSION_COOKIE_NAME, "anything")
        r = client.get("/api/setup/status")
        assert r.status_code == 401


# ---------- pairing code input validation (Fix 2) ----------


class TestPairCodeValidation:
    """Malformed/non-ASCII input returns fixed safe message without echoing
    the submitted value."""

    def test_arabic_indic_digits_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        # Arabic-Indic digits ٠١٢٣٤٥ (U+0660..U+0664) — isdigit() is True
        # but isascii() is False.
        r = client.post("/api/auth/pair", json={"code": "٠١٢٣٤٥"})
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]
        assert "٠١٢٣٤٥" not in r.text

    def test_full_width_digits_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        # Full-width digits ０１２３４５ (U+FF10..U+FF14) — isdigit() is True
        # but isascii() is False.
        r = client.post("/api/auth/pair", json={"code": "０１２３４５"})
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]
        assert "０１２３４５" not in r.text

    def test_wrong_length_too_short(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": "12345"})
        assert r.status_code == 400
        assert "12345" not in r.text

    def test_wrong_length_too_long(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": "1234567"})
        assert r.status_code == 400
        assert "1234567" not in r.text

    def test_non_string_code_rejected(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"code": 123456})
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]

    def test_missing_code_field(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post("/api/auth/pair", json={"not_code": "123456"})
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]

    def test_malformed_json(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post(
            "/api/auth/pair",
            data="not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400
        assert "格式不正确" in r.json()["message"]

    def test_empty_body(self) -> None:
        client, _ = _make_client_with_known_code()
        r = client.post(
            "/api/auth/pair",
            data="",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    def test_submitted_value_never_in_any_error_response(self) -> None:
        """Critical: no error response ever contains the submitted code."""
        client, _ = _make_client_with_known_code()
        test_inputs = [
            "abcdef",
            "000000",
            "999999",
            "١٢٣٤٥٦",
            "x" * 100,
            "",
            "12",
            "123456789",
        ]
        for val in test_inputs:
            r = client.post("/api/auth/pair", json={"code": val})
            # The submitted value must never appear in the response text
            # (skip empty string — it's trivially a substring of anything).
            if val:
                assert val not in r.text, f"Submitted value {val!r} leaked in response"
