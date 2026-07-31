"""Single-owner HTTP/WebSocket authentication, pairing codes, and agent concurrency.

Authentication modes:
- ``none``   — no api_token configured (local loopback default).
- ``token``  — api_token set; requests authenticate via Bearer header (legacy).
- ``pairing`` — api_token set + a pairing code digest provided; browsers
  exchange the one-time code for an HMAC-signed HttpOnly session cookie,
  eliminating copy/paste of MOMMY_API_TOKEN. Bearer remains fully compatible.

Security invariants:
- The plaintext pairing code is generated once in the CLI, printed once, then
  immediately discarded — only its HMAC-SHA256 digest enters ``WebSecurity``.
- Session cookies are HMAC-signed with context separation and embedded expiry;
  validation is constant-time and survives restarts (same api_token).
- All error messages are fixed Chinese strings; exception text and credentials
  are never returned or logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

_PUBLIC_API_PATHS = frozenset({"/api/health", "/api/auth/status", "/api/auth/pair"})

# Read-only + write endpoints exposed by web/routes/setup.py. They are never
# unconditionally public; OwnerAuthMiddleware admits them only when the request
# arrives from a genuine loopback socket peer (and the server opted into the
# local-setup capability) OR carries a strictly valid owner credential.
SETUP_API_PREFIX = "/api/setup"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Session cookie name — exported for tests.
SESSION_COOKIE_NAME = "mommy-session"

_PAIRING_TTL_SECONDS = 10 * 60
_PAIRING_MAX_FAILURES = 5
_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

_PAIRING_CONTEXT = "mommy-pairing-v1"
_SESSION_CONTEXT = "mommy-session-v1"

# Fixed messages — never include exception text or credentials.
_MSG_PAIR_INVALID = "配对码无效或已过期，请重启服务获取新码"
_MSG_PAIR_EXHAUSTED = "配对尝试次数过多，请重启服务获取新码"
_MSG_PAIR_USED = "配对码已使用，请重启服务获取新码"
_MSG_PAIR_NOT_READY = "当前服务未启用浏览器配对，请使用访问令牌"


class PairResult(Enum):
    """Outcome of a pairing-code consumption attempt."""

    SUCCESS = "success"
    INVALID = "invalid"
    EXHAUSTED = "exhausted"
    USED = "used"
    NOT_READY = "not_ready"


def is_loopback_request(request: Request) -> bool:
    """Return True only when the actual socket peer is loopback.

    Never trusts X-Forwarded-For or any client-supplied header: a reverse proxy
    can spoof those. The peer is taken from the live connection.
    """
    client = request.client
    if client is None or not client.host:
        return False
    if client.host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False


def _pairing_digest(api_token: str, code: str) -> str:
    """Compute HMAC-SHA256 digest of a pairing code keyed by api_token."""
    return hmac.new(
        api_token.encode("utf-8"),
        f"{_PAIRING_CONTEXT}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_pairing_code_and_digest(
    api_token: str,
) -> tuple[str, str]:
    """Generate a cryptographically random 6-digit pairing code and its digest.

    Returns ``(plaintext_code, digest)``. The plaintext is intended to be
    printed once by the CLI then discarded; only the digest enters WebSecurity.
    """
    if not api_token:
        raise ValueError("Pairing requires a non-empty API token")
    code = f"{secrets.randbelow(1_000_000):06d}"
    return code, _pairing_digest(api_token, code)


@dataclass(slots=True)
class _PairingState:
    """Mutable state for the one-time pairing code consumption."""

    digest: str
    issued_at: float
    ttl_seconds: int
    consumed: bool = False
    failures: int = 0


@dataclass(frozen=True, slots=True)
class SessionData:
    """Result of a session-cookie issuance."""

    cookie_value: str
    expires_at: int


@dataclass(slots=True)
class WebSecurity:
    """Application-scoped security state for one owner token.

    ``pairing_digest`` is the HMAC-SHA256 digest of the one-time pairing code,
    keyed by ``api_token``. When non-empty, the server is in *pairing* mode:
    browsers can exchange the code for a session cookie at ``/api/auth/pair``.
    Bearer-token auth remains fully compatible in all modes.
    """

    api_token: str = ""
    ticket_ttl_seconds: int = 60
    agent_max_concurrency: int = 2
    local_setup_enabled: bool = False
    pairing_digest: str = ""
    pairing_ttl_seconds: int = _PAIRING_TTL_SECONDS
    pairing_max_failures: int = _PAIRING_MAX_FAILURES
    session_ttl_seconds: int = _SESSION_TTL_SECONDS
    _active_agent_requests: int = field(default=0, init=False)
    _agent_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _pairing: _PairingState | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.ticket_ttl_seconds < 10 or self.ticket_ttl_seconds > 300:
            raise ValueError("WebSocket ticket TTL must be between 10 and 300 seconds")
        if self.agent_max_concurrency < 1:
            raise ValueError("Agent max concurrency must be at least 1")
        if self.pairing_ttl_seconds < 60 or self.pairing_ttl_seconds > 3600:
            raise ValueError("Pairing TTL must be between 60 and 3600 seconds")
        if self.pairing_max_failures < 1 or self.pairing_max_failures > 20:
            raise ValueError("Pairing max failures must be between 1 and 20")
        if self.session_ttl_seconds < 3600 or self.session_ttl_seconds > 365 * 24 * 3600:
            raise ValueError("Session TTL must be between 1 hour and 365 days")
        if self.pairing_digest and not self.api_token:
            raise ValueError("Pairing digest requires a non-empty API token")

        if self.pairing_digest:
            self._pairing = _PairingState(
                digest=self.pairing_digest,
                issued_at=time.time(),
                ttl_seconds=self.pairing_ttl_seconds,
            )

    # ----- mode -----

    @property
    def auth_mode(self) -> Literal["none", "token", "pairing"]:
        """One truthful authentication mode for this server instance."""
        if not self.enabled:
            return "none"
        if self._pairing is not None:
            return "pairing"
        return "token"

    @property
    def enabled(self) -> bool:
        return bool(self.api_token)

    # ----- HTTP authorization -----

    def authorize_header(self, authorization: str | None) -> bool:
        """Validate an HTTP Bearer token using constant-time comparison."""
        if not self.enabled:
            return True
        if not authorization or not authorization.startswith("Bearer "):
            return False
        candidate = authorization.removeprefix("Bearer ").strip()
        return bool(candidate) and secrets.compare_digest(candidate, self.api_token)

    def authorize_cookie(self, cookie_header: str | None) -> bool:
        """Validate a session cookie using constant-time HMAC comparison."""
        if not self.enabled:
            return True
        if not cookie_header:
            return False
        cookie_value = _extract_cookie(cookie_header, SESSION_COOKIE_NAME)
        if not cookie_value:
            return False
        return self._validate_session_cookie(cookie_value)

    # ----- pairing -----

    def consume_pairing_code(self, code: str) -> PairResult:
        """Consume a pairing code in constant time. Returns a safe enum.

        - Validates TTL, failure cap, single-use, and digest match.
        - Invalid input does NOT increment the failure counter (only a
          well-formed code that doesn't match counts).
        """
        p = self._pairing
        if p is None:
            return PairResult.NOT_READY

        # Defence in depth: malformed values do not consume one of the five
        # online guesses, even when this method is called outside the route.
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            return PairResult.INVALID

        if p.consumed:
            return PairResult.USED

        now = time.time()
        if now - p.issued_at > p.ttl_seconds:
            return PairResult.EXHAUSTED

        if p.failures >= self.pairing_max_failures:
            return PairResult.EXHAUSTED

        candidate_digest = _pairing_digest(self.api_token, code)
        if secrets.compare_digest(candidate_digest, p.digest):
            p.consumed = True
            return PairResult.SUCCESS

        p.failures += 1
        if p.failures >= self.pairing_max_failures:
            return PairResult.EXHAUSTED
        return PairResult.INVALID

    def issue_session_cookie(self) -> SessionData:
        """Issue a 30-day HMAC-signed session cookie value."""
        expires_at = int(time.time()) + self.session_ttl_seconds
        nonce = secrets.token_urlsafe(18)
        payload = f"{expires_at}.{nonce}"
        signature = hmac.new(
            self.api_token.encode("utf-8"),
            f"{_SESSION_CONTEXT}:{payload}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return SessionData(
            cookie_value=f"{payload}.{signature}",
            expires_at=expires_at,
        )

    def _validate_session_cookie(self, cookie_value: str) -> bool:
        """Validate signature and expiry of a session cookie."""
        try:
            expires_raw, nonce, signature = cookie_value.split(".", 2)
            expires_at = int(expires_raw)
        except (TypeError, ValueError):
            return False
        if expires_at < int(time.time()) or not nonce:
            return False
        payload = f"{expires_at}.{nonce}"
        expected = hmac.new(
            self.api_token.encode("utf-8"),
            f"{_SESSION_CONTEXT}:{payload}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return secrets.compare_digest(signature, expected)

    # ----- WebSocket tickets -----

    def issue_ws_ticket(self) -> tuple[str, int]:
        """Issue a short-lived HMAC-signed WebSocket ticket."""
        expires_at = int(time.time()) + self.ticket_ttl_seconds
        nonce = secrets.token_urlsafe(18)
        payload = f"{expires_at}.{nonce}"
        signature = hmac.new(
            self.api_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"{payload}.{signature}", expires_at

    def validate_ws_ticket(self, ticket: str | None) -> bool:
        """Validate signature and expiry for a WebSocket ticket."""
        if not self.enabled:
            return True
        if not ticket:
            return False
        try:
            expires_raw, nonce, signature = ticket.split(".", 2)
            expires_at = int(expires_raw)
        except (TypeError, ValueError):
            return False
        if expires_at < int(time.time()) or not nonce:
            return False
        payload = f"{expires_at}.{nonce}"
        expected = hmac.new(
            self.api_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return secrets.compare_digest(signature, expected)

    # ----- agent concurrency -----

    async def try_acquire_agent(self) -> bool:
        """Reserve one agent request slot without waiting."""
        async with self._agent_lock:
            if self._active_agent_requests >= self.agent_max_concurrency:
                return False
            self._active_agent_requests += 1
            return True

    async def release_agent(self) -> None:
        """Release a previously acquired agent request slot."""
        async with self._agent_lock:
            self._active_agent_requests = max(0, self._active_agent_requests - 1)


def _extract_cookie(cookie_header: str, name: str) -> str | None:
    """Extract a named cookie value from a Cookie header."""
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            if key.strip() == name:
                return value.strip()
    return None


def _is_setup_path(path: str) -> bool:
    """True only for ``/api/setup`` itself or its ``/`` descendants.

    Rejects unrelated prefixes like ``/api/setupfoo``.
    """
    if path == SETUP_API_PREFIX:
        return True
    return path.startswith(SETUP_API_PREFIX + "/")


def _is_json_request(request: Request) -> bool:
    """Return True for an application/json request, allowing charset params."""
    content_type = request.headers.get("content-type", "")
    return content_type.partition(";")[0].strip().lower() == "application/json"


class OwnerAuthMiddleware(BaseHTTPMiddleware):
    """Protect owner-data REST routes and bound concurrent agent requests.

    Accepts valid legacy Bearer header OR signed session cookie.
    """

    def __init__(self, app: object, security: WebSecurity) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.security = security

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        bearer_ok = self.security.authorize_header(request.headers.get("authorization"))
        cookie_ok = self.security.authorize_cookie(request.headers.get("cookie"))
        authenticated = bearer_ok or cookie_ok

        # Setup endpoints: never unconditionally public. Admitted only when
        # (a) local_setup_enabled is on AND the real socket peer is loopback,
        # or (b) the request carries a strictly valid owner credential
        # (Bearer OR signed session cookie), with security.enabled required
        # so --allow-unauthenticated-remote cannot enter setup.
        if _is_setup_path(path):
            local_ok = self.security.local_setup_enabled and is_loopback_request(request)
            strict_credential = self.security.enabled and (bearer_ok or cookie_ok)
            if not local_ok and not strict_credential:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Setup endpoints require local access or owner credentials"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Local no-auth setup still needs CSRF resistance. Requiring JSON
            # blocks cross-origin HTML forms and simple fetch requests.
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _is_json_request(
                request
            ):
                return JSONResponse(
                    status_code=415,
                    content={"detail": "Setup writes require application/json"},
                )
        elif path.startswith("/api/") and path not in _PUBLIC_API_PATHS and not authenticated:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid owner token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        acquired = False
        if path.startswith("/api/agent/") and request.method == "POST":
            acquired = await self.security.try_acquire_agent()
            if not acquired:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Agent is busy; retry shortly"},
                    headers={"Retry-After": "1"},
                )
        try:
            return await call_next(request)
        finally:
            if acquired:
                await self.security.release_agent()


def get_web_security(request: Request) -> WebSecurity:
    """Return application-scoped security state."""
    return request.app.state.web_security  # type: ignore[no-any-return]
