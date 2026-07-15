"""Single-owner HTTP/WebSocket authentication and agent concurrency limits."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

_PUBLIC_API_PATHS = frozenset({"/api/health"})


@dataclass(slots=True)
class WebSecurity:
    """Application-scoped security state for one owner token."""

    api_token: str = ""
    ticket_ttl_seconds: int = 60
    agent_max_concurrency: int = 2
    _active_agent_requests: int = field(default=0, init=False)
    _agent_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        if self.ticket_ttl_seconds < 10 or self.ticket_ttl_seconds > 300:
            raise ValueError("WebSocket ticket TTL must be between 10 and 300 seconds")
        if self.agent_max_concurrency < 1:
            raise ValueError("Agent max concurrency must be at least 1")

    @property
    def enabled(self) -> bool:
        return bool(self.api_token)

    def authorize_header(self, authorization: str | None) -> bool:
        """Validate an HTTP Bearer token using constant-time comparison."""
        if not self.enabled:
            return True
        if not authorization or not authorization.startswith("Bearer "):
            return False
        candidate = authorization.removeprefix("Bearer ").strip()
        return bool(candidate) and secrets.compare_digest(candidate, self.api_token)

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


class OwnerAuthMiddleware(BaseHTTPMiddleware):
    """Protect owner-data REST routes and bound concurrent agent requests."""

    def __init__(self, app: object, security: WebSecurity) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.security = security

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if (
            path.startswith("/api/")
            and path not in _PUBLIC_API_PATHS
            and not self.security.authorize_header(request.headers.get("authorization"))
        ):
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
