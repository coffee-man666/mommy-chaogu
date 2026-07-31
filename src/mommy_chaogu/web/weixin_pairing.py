"""App-scoped manager for browser-based Weixin QR pairing.

This module bridges the blocking ``channels.weixin.WeixinClient`` lifecycle
(QR fetch + long-poll) to async web endpoints. It keeps all secrets and
upstream IDs in process memory — never in browser/sessionStorage/logs.

Design constraints:
- Never calls ``WeixinClient.login()`` (it blocks on stdin).
- One upstream ``poll_qr_status`` per HTTP request, run in a threadpool.
- Per-attempt asyncio lock to prevent concurrent poll races.
- Bounded in-memory attempt store with auto-prune and TTL (~8 min).
- ``binded_redirect`` / redirect-host state is tracked server-side only.
- ``confirmed`` → save ``WeixinCredentials`` then ``restart_gateway_process``
  (all via threadpool). If gateway startup fails, credentials are retained.
- Secrets (qrcode_id, qrcode_url, redirect host, bot token) never leave
  the manager; responses expose only a browser-safe SVG data URL and an
  opaque ``pairing_id``.
- All blocking operations (fetch, poll, save, restart, pid, load) run via
  ``asyncio.to_thread`` so the event loop is never blocked.
- Error responses use fixed friendly messages — exception text/details are
  never returned to the browser and never logged with potentially secret
  trace content.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import secrets as _secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from mommy_chaogu.channels.weixin import DEFAULT_BASE_URL, WeixinApiError

_log = logging.getLogger(__name__)

_ATTEMPT_TTL_SECONDS = 8 * 60
_MAX_ATTEMPTS = 8

WeixinStatus = Literal[
    "waiting",
    "scanned",
    "verification_required",
    "connected",
    "already_connected",
    "expired",
    "error",
]

# Fixed friendly messages — never include exception text or secrets.
_MSG_FETCH_FAILED = "获取微信二维码失败，请重试"
_MSG_POLL_FAILED = "查询微信扫码状态失败，请重试"
_MSG_SAVE_FAILED = "微信凭据保存失败，请重试"
_MSG_GATEWAY_FAILED = "微信连接成功，但助手暂未上线（稍后可重试启动）"
_MSG_VERIFY_BLOCKED = "微信验证码错误次数过多，请稍后重试"
_MSG_QR_RENDER_FAILED = "二维码生成失败，请重试"
_MSG_NO_LOCAL_CREDS = "微信报告该账号已绑定，但本机没有可用的本地凭据"


# ---------- dependency protocols (for faking in tests) ----------


class _FetchQrProto(Protocol):
    def __call__(self, local_tokens: list[str] | None = None) -> tuple[str, str]: ...


class _PollQrProto(Protocol):
    def __call__(
        self, qrcode_id: str, *, base_url: str = ..., verify_code: str = ""
    ) -> dict[str, Any]: ...


# ---------- attempt state ----------


@dataclass(slots=True)
class _Attempt:
    """Mutable server-side state for one pairing attempt."""

    qrcode_id: str
    polling_base_url: str = DEFAULT_BASE_URL
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Cached terminal result — returned on subsequent polls without calling
    # the upstream again.
    terminal_result: PairingPollResult | None = None

    def __post_init__(self) -> None:
        if self.expires_at == 0.0:
            self.expires_at = self.created_at + _ATTEMPT_TTL_SECONDS

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at


# ---------- public result dataclass ----------


@dataclass(frozen=True, slots=True)
class PairingStartResult:
    pairing_id: str
    qr_data_url: str
    expires_in_seconds: int
    status: WeixinStatus
    message: str


@dataclass(frozen=True, slots=True)
class PairingPollResult:
    status: WeixinStatus
    message: str
    gateway_started: bool = False
    gateway_online: bool = False


# ---------- QR rendering ----------


def _render_svg_data_url(qrcode_url: str) -> str:
    """Render a browser-safe SVG data URL from the raw QR payload."""
    import qrcode
    from qrcode.image.svg import SvgPathImage

    qr = qrcode.QRCode(image_factory=SvgPathImage)
    qr.add_data(qrcode_url)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf)
    svg_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{svg_b64}"


def _safe_log(exc: Exception, *, fixed_msg: str) -> None:
    """Log a fixed message + exception class name only — never the trace or message."""
    _log.warning("%s: %s", fixed_msg, type(exc).__name__)


# ---------- manager ----------


class WeixinPairingManager:
    """App-scoped pairing-orchestration for browser QR flows.

    Constructed once in ``create_app`` and stored at
    ``app.state.weixin_pairing``. Tests inject fakes via the constructor.
    """

    def __init__(
        self,
        fetch_qr: _FetchQrProto,
        poll_qr: _PollQrProto,
        store: Any,
        *,
        save_credentials: Any,
        load_credentials: Any,
        gateway_pid_fn: Any,
        restart_gateway_fn: Any,
        ttl_seconds: int = _ATTEMPT_TTL_SECONDS,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self._fetch_qr = fetch_qr
        self._poll_qr = poll_qr
        self._store = store
        self._save_credentials = save_credentials
        self._load_credentials = load_credentials
        self._gateway_pid_fn = gateway_pid_fn
        self._restart_gateway_fn = restart_gateway_fn
        self._ttl = ttl_seconds
        self._max_attempts = max_attempts
        self._attempts: dict[str, _Attempt] = {}
        self._global_lock = asyncio.Lock()

    # ----- internal helpers (blocking-safe — callers wrap in to_thread) -----

    def _prune(self) -> None:
        """Remove expired attempts (no lock — caller holds _global_lock)."""
        now = time.monotonic()
        expired = [pid for pid, a in self._attempts.items() if now >= a.expires_at]
        for pid in expired:
            self._attempts.pop(pid, None)

    def _local_tokens_sync(self) -> list[str]:
        """Existing credential token as local_tokens hint (never exposed)."""
        creds = self._load_credentials(self._store)
        if creds is not None:
            return [creds.token]
        return []

    def _get_attempt(self, pairing_id: str) -> _Attempt | None:
        a = self._attempts.get(pairing_id)
        if a is None or a.expired:
            self._attempts.pop(pairing_id, None)
            return None
        return a

    async def _is_online(self) -> bool:
        try:
            pid = await asyncio.to_thread(self._gateway_pid_fn, self._store)
            return pid is not None
        except Exception as exc:
            _safe_log(exc, fixed_msg="Gateway PID check failed")
            return False

    # ----- public API -----

    async def start(self) -> PairingStartResult:
        """Start or restart a QR pairing attempt.

        Returns only browser-safe fields. Never exposes the raw qrcode_id,
        qrcode_url, redirect host, or any credential.
        """
        async with self._global_lock:
            self._prune()
            if len(self._attempts) >= self._max_attempts:
                return PairingStartResult(
                    pairing_id="",
                    qr_data_url="",
                    expires_in_seconds=0,
                    status="error",
                    message="配对尝试次数过多，请稍后再试",
                )

            try:
                local_tokens = await asyncio.to_thread(self._local_tokens_sync)
            except Exception as exc:
                _safe_log(exc, fixed_msg="Failed to load local credentials")
                local_tokens = []

            try:
                qrcode_id, qrcode_url = await asyncio.to_thread(self._fetch_qr, local_tokens)
            except WeixinApiError as exc:
                _safe_log(exc, fixed_msg="QR fetch failed")
                return PairingStartResult(
                    pairing_id="",
                    qr_data_url="",
                    expires_in_seconds=0,
                    status="error",
                    message=_MSG_FETCH_FAILED,
                )
            except Exception as exc:
                _safe_log(exc, fixed_msg="QR fetch failed")
                return PairingStartResult(
                    pairing_id="",
                    qr_data_url="",
                    expires_in_seconds=0,
                    status="error",
                    message=_MSG_FETCH_FAILED,
                )

            pairing_id = _secrets.token_urlsafe(18)

            # Render SVG before inserting the attempt; if rendering fails,
            # do not leave a dangling attempt in the map.
            try:
                qr_data_url = await asyncio.to_thread(_render_svg_data_url, qrcode_url)
            except Exception as exc:
                _safe_log(exc, fixed_msg="SVG render failed")
                return PairingStartResult(
                    pairing_id="",
                    qr_data_url="",
                    expires_in_seconds=0,
                    status="error",
                    message=_MSG_QR_RENDER_FAILED,
                )

            attempt = _Attempt(
                qrcode_id=qrcode_id,
                expires_at=time.monotonic() + self._ttl,
            )
            self._attempts[pairing_id] = attempt

        remaining = max(0, int(attempt.expires_at - time.monotonic()))
        return PairingStartResult(
            pairing_id=pairing_id,
            qr_data_url=qr_data_url,
            expires_in_seconds=remaining,
            status="waiting",
            message="请用微信扫描二维码",
        )

    async def poll(self, pairing_id: str, verify_code: str = "") -> PairingPollResult:
        """Perform at most one upstream poll for the given attempt.

        Returns a safe enum + friendly message. On ``confirmed``, saves
        credentials and attempts gateway restart (all via threadpool).
        """
        attempt = self._get_attempt(pairing_id)
        if attempt is None:
            return PairingPollResult(status="expired", message="二维码已过期或不存在，请重新获取")

        async with attempt.lock:
            # Re-check terminal_result under lock — another coroutine may
            # have resolved this attempt while we waited.
            if attempt.terminal_result is not None:
                return attempt.terminal_result

            if attempt.expired:
                self._attempts.pop(pairing_id, None)
                return PairingPollResult(status="expired", message="二维码已过期，请重新获取")

            # One-shot verify_code: use it for this poll only, then clear.
            poll_verify_code = ""
            if verify_code:
                poll_verify_code = verify_code

            try:
                raw = await asyncio.to_thread(
                    self._poll_qr,
                    attempt.qrcode_id,
                    base_url=attempt.polling_base_url,
                    verify_code=poll_verify_code,
                )
            except WeixinApiError as exc:
                _safe_log(exc, fixed_msg="Weixin poll error")
                return PairingPollResult(status="error", message=_MSG_POLL_FAILED)
            except Exception as exc:
                _safe_log(exc, fixed_msg="Weixin poll error")
                return PairingPollResult(status="error", message=_MSG_POLL_FAILED)

            status_str = str(raw.get("status", "wait"))
            return await self._handle_status(status_str, raw, attempt)

    # ----- status mapping -----

    async def _handle_status(
        self,
        status_str: str,
        raw: dict[str, Any],
        attempt: _Attempt,
    ) -> PairingPollResult:
        if status_str in {"wait", "scaned"}:
            return PairingPollResult(
                status="scanned" if status_str == "scaned" else "waiting",
                message="已扫码，请在手机确认" if status_str == "scaned" else "请用微信扫描二维码",
            )

        if status_str == "need_verifycode":
            return PairingPollResult(
                status="verification_required",
                message="请在输入框中填写手机微信显示的数字",
            )

        if status_str == "verify_code_blocked":
            return PairingPollResult(status="error", message=_MSG_VERIFY_BLOCKED)

        if status_str == "scaned_but_redirect":
            redirect_host = str(raw.get("redirect_host", "")).strip()
            if redirect_host:
                attempt.polling_base_url = f"https://{redirect_host}"
            return PairingPollResult(status="waiting", message="正在切换服务器，请稍候")

        if status_str == "binded_redirect":
            return await self._handle_binded_redirect(attempt)

        if status_str == "expired":
            result = PairingPollResult(status="expired", message="二维码已过期，请重新获取")
            attempt.terminal_result = result
            return result

        if status_str == "confirmed":
            return await self._finalize(raw, attempt)

        _log.warning("unknown Weixin QR login status received")
        return PairingPollResult(status="waiting", message="请用微信扫描二维码")

    async def _handle_binded_redirect(self, attempt: _Attempt) -> PairingPollResult:
        """Handle binded_redirect — check existing creds/gateway via threadpool.

        If usable local credentials exist, check the gateway PID. If offline,
        attempt a restart, then recheck. Returns truthful
        gateway_started/gateway_online.

        If no local credentials exist, returns status=error (not
        already_connected) so the UI cannot infer a usable connection.
        """
        try:
            creds = await asyncio.to_thread(self._load_credentials, self._store)
        except Exception as exc:
            _safe_log(exc, fixed_msg="Failed to load credentials for binded_redirect")
            creds = None

        if creds is None:
            attempt.terminal_result = PairingPollResult(
                status="error",
                message=_MSG_NO_LOCAL_CREDS,
            )
            return attempt.terminal_result

        # Usable local credentials exist — check gateway status.
        gateway_online = await self._is_online()
        gateway_started = False

        if not gateway_online:
            try:
                await asyncio.to_thread(self._restart_gateway_fn, self._store)
                gateway_started = True
            except Exception as exc:
                _safe_log(exc, fixed_msg="Gateway restart failed during binded_redirect")
            gateway_online = await self._is_online()

        if gateway_online:
            attempt.terminal_result = PairingPollResult(
                status="already_connected",
                message="这个微信账号已经连接过当前助手",
                gateway_started=gateway_started,
                gateway_online=True,
            )
        else:
            attempt.terminal_result = PairingPollResult(
                status="already_connected",
                message="微信已绑定，助手离线，稍后可重试启动",
                gateway_started=gateway_started,
                gateway_online=False,
            )
        return attempt.terminal_result

    async def _finalize(self, raw: dict[str, Any], attempt: _Attempt) -> PairingPollResult:
        """Save credentials on confirmed and attempt gateway restart.

        All blocking operations run via ``asyncio.to_thread``.
        """
        from mommy_chaogu.channels.store import WeixinCredentials

        account_id = str(raw.get("ilink_bot_id", "")).strip()
        token = str(raw.get("bot_token", "")).strip()
        owner_user_id = str(raw.get("ilink_user_id", "")).strip()
        base_url = str(raw.get("baseurl", "")).strip() or attempt.polling_base_url

        if not account_id or not token or not owner_user_id:
            return PairingPollResult(
                status="error",
                message="微信已确认授权，但返回的账号凭据不完整",
            )

        creds = WeixinCredentials(
            account_id=account_id,
            token=token,
            base_url=base_url,
            owner_user_id=owner_user_id,
        )
        try:
            await asyncio.to_thread(self._save_credentials, self._store, creds)
        except Exception as exc:
            _safe_log(exc, fixed_msg="Failed to save Weixin credentials")
            return PairingPollResult(status="error", message=_MSG_SAVE_FAILED)

        # Attempt gateway restart via threadpool — failures don't erase
        # valid credentials.
        gateway_started = False
        try:
            await asyncio.to_thread(self._restart_gateway_fn, self._store)
            gateway_started = True
        except Exception as exc:
            _safe_log(exc, fixed_msg="Gateway restart failed after Weixin pairing")

        gateway_online = await self._is_online()

        if gateway_online:
            result = PairingPollResult(
                status="connected",
                message="微信连接成功，助手已上线",
                gateway_started=gateway_started,
                gateway_online=True,
            )
        else:
            result = PairingPollResult(
                status="connected",
                message=_MSG_GATEWAY_FAILED,
                gateway_started=gateway_started,
                gateway_online=False,
            )
        attempt.terminal_result = result
        return result


def default_pairing_manager() -> WeixinPairingManager:
    """Build a production manager wired to real channels primitives."""
    from mommy_chaogu.channels import WeixinClient, WeixinStore
    from mommy_chaogu.channels.process import (
        gateway_process_pid,
        restart_gateway_process,
    )

    client = WeixinClient()
    store = WeixinStore()

    return WeixinPairingManager(
        fetch_qr=client.fetch_qr_code,
        poll_qr=client.poll_qr_status,
        store=store,
        save_credentials=WeixinStore.save_credentials,
        load_credentials=WeixinStore.load_credentials,
        gateway_pid_fn=gateway_process_pid,
        restart_gateway_fn=restart_gateway_process,
    )


__all__ = [
    "PairingPollResult",
    "PairingStartResult",
    "WeixinPairingManager",
    "default_pairing_manager",
]
