"""Minimal Tencent iLink Weixin client.

Protocol behavior is adapted from Tencent/openclaw-weixin (MIT, copyright Tencent):
https://github.com/Tencent/openclaw-weixin
Only QR authorization, private text polling, and text replies are implemented here.
"""

from __future__ import annotations

import base64
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import quote

import requests

from mommy_chaogu import __version__

_log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_BOT_TYPE = "3"
_LOGIN_TTL_SECONDS = 8 * 60
_REGULAR_TIMEOUT = (8.0, 20.0)
_LONG_POLL_TIMEOUT = (8.0, 40.0)


class _ResponseLike(Protocol):
    status_code: int
    text: str

    def json(self) -> object: ...


class _SessionLike(Protocol):
    def get(self, url: str, **kwargs: object) -> _ResponseLike: ...

    def post(self, url: str, **kwargs: object) -> _ResponseLike: ...


class WeixinApiError(RuntimeError):
    """A network or protocol error that never embeds credential material."""


@dataclass(frozen=True, slots=True)
class QrLoginResult:
    connected: bool
    message: str
    account_id: str = ""
    bot_token: str = ""
    base_url: str = DEFAULT_BASE_URL
    owner_user_id: str = ""
    already_connected: bool = False


def _client_version(version: str) -> int:
    numbers: list[int] = []
    for part in version.split(".")[:3]:
        digits = "".join(char for char in part if char.isdigit())
        numbers.append(int(digits or "0") & 0xFF)
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0] << 16) | (numbers[1] << 8) | numbers[2]


def _json_object(response: _ResponseLike, label: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        raise WeixinApiError(f"{label} 请求失败（HTTP {response.status_code}）")
    try:
        value = response.json()
    except ValueError as exc:
        raise WeixinApiError(f"{label} 返回了无效数据") from exc
    if not isinstance(value, dict):
        raise WeixinApiError(f"{label} 返回格式不正确")
    return cast(dict[str, Any], value)


class WeixinClient:
    """Blocking iLink client designed for a local background process."""

    def __init__(self, session: _SessionLike | None = None) -> None:
        self._session = session if session is not None else cast(_SessionLike, requests.Session())

    @property
    def base_info(self) -> dict[str, str]:
        return {
            "channel_version": __version__,
            "bot_agent": f"MommyChaogu/{__version__}",
        }

    def _common_headers(self) -> dict[str, str]:
        return {
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": str(_client_version(__version__)),
        }

    def _headers(self, token: str = "") -> dict[str, str]:
        random_uin = str(secrets.randbits(32)).encode("ascii")
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(random_uin).decode("ascii"),
            **self._common_headers(),
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _url(base_url: str, endpoint: str) -> str:
        return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    def _get(self, label: str, url: str, **kwargs: object) -> _ResponseLike:
        try:
            return self._session.get(url, **kwargs)
        except requests.RequestException as exc:
            raise WeixinApiError(f"{label}网络连接失败") from exc

    def _post(self, label: str, url: str, **kwargs: object) -> _ResponseLike:
        try:
            return self._session.post(url, **kwargs)
        except requests.RequestException as exc:
            raise WeixinApiError(f"{label}网络连接失败") from exc

    def fetch_qr_code(self, local_tokens: list[str] | None = None) -> tuple[str, str]:
        response = self._post(
            "获取微信二维码",
            self._url(
                DEFAULT_BASE_URL,
                f"ilink/bot/get_bot_qrcode?bot_type={quote(DEFAULT_BOT_TYPE)}",
            ),
            json={"local_token_list": (local_tokens or [])[-10:]},
            headers=self._headers(),
            timeout=_REGULAR_TIMEOUT,
        )
        raw = _json_object(response, "获取微信二维码")
        qrcode_id = str(raw.get("qrcode", "")).strip()
        qrcode_url = str(raw.get("qrcode_img_content", "")).strip()
        if not qrcode_id or not qrcode_url:
            raise WeixinApiError("微信服务没有返回可用二维码")
        return qrcode_id, qrcode_url

    def poll_qr_status(
        self,
        qrcode_id: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        verify_code: str = "",
    ) -> dict[str, Any]:
        endpoint = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode_id)}"
        if verify_code:
            endpoint += f"&verify_code={quote(verify_code)}"
        response = self._get(
            "查询微信扫码状态",
            self._url(base_url, endpoint),
            headers=self._common_headers(),
            timeout=_LONG_POLL_TIMEOUT,
        )
        return _json_object(response, "查询微信扫码状态")

    def login(
        self,
        *,
        on_qr: Callable[[str], None],
        read_verify_code: Callable[[str], str] = input,
        timeout_seconds: float = _LOGIN_TTL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        local_tokens: list[str] | None = None,
    ) -> QrLoginResult:
        """Display/refresh QR codes and wait until the scanner confirms authorization."""
        deadline = time.monotonic() + max(timeout_seconds, 10)
        verify_code = ""
        polling_base_url = DEFAULT_BASE_URL
        refreshes = 0
        qrcode_id, qrcode_url = self.fetch_qr_code(local_tokens)
        on_qr(qrcode_url)

        while time.monotonic() < deadline:
            status_raw = self.poll_qr_status(
                qrcode_id,
                base_url=polling_base_url,
                verify_code=verify_code,
            )
            status = str(status_raw.get("status", "wait"))
            if status in {"wait", "scaned"}:
                if status == "scaned":
                    verify_code = ""
                sleep(1)
                continue
            if status == "need_verifycode":
                verify_code = read_verify_code("请输入手机微信显示的数字：").strip()
                continue
            if status == "verify_code_blocked":
                raise WeixinApiError("微信验证码错误次数过多，请稍后重试")
            if status == "scaned_but_redirect":
                redirect_host = str(status_raw.get("redirect_host", "")).strip()
                if redirect_host:
                    polling_base_url = f"https://{redirect_host}"
                sleep(1)
                continue
            if status == "binded_redirect":
                return QrLoginResult(
                    connected=False,
                    already_connected=True,
                    message="这个微信账号已经连接过当前助手",
                )
            if status == "expired":
                refreshes += 1
                if refreshes >= 3:
                    raise WeixinApiError("微信二维码多次过期，请重新运行登录命令")
                qrcode_id, qrcode_url = self.fetch_qr_code(local_tokens)
                on_qr(qrcode_url)
                polling_base_url = DEFAULT_BASE_URL
                verify_code = ""
                continue
            if status == "confirmed":
                account_id = str(status_raw.get("ilink_bot_id", "")).strip()
                token = str(status_raw.get("bot_token", "")).strip()
                owner_user_id = str(status_raw.get("ilink_user_id", "")).strip()
                base_url = str(status_raw.get("baseurl", "")).strip() or polling_base_url
                if not account_id or not token or not owner_user_id:
                    raise WeixinApiError("微信已确认授权，但返回的账号凭据不完整")
                return QrLoginResult(
                    connected=True,
                    message="微信连接成功",
                    account_id=account_id,
                    bot_token=token,
                    base_url=base_url,
                    owner_user_id=owner_user_id,
                )
            _log.warning("unknown Weixin QR login status: %s", status)
            sleep(1)

        raise WeixinApiError("等待微信扫码超时，请重新运行登录命令")

    def get_updates(
        self,
        *,
        base_url: str,
        token: str,
        get_updates_buf: str,
    ) -> dict[str, Any]:
        response = self._post(
            "接收微信消息",
            self._url(base_url, "ilink/bot/getupdates"),
            json={"get_updates_buf": get_updates_buf, "base_info": self.base_info},
            headers=self._headers(token),
            timeout=_LONG_POLL_TIMEOUT,
        )
        raw = _json_object(response, "接收微信消息")
        ret = int(raw.get("ret", 0) or 0)
        errcode = int(raw.get("errcode", 0) or 0)
        if ret or errcode:
            raise WeixinApiError(f"接收微信消息失败（ret={ret}, errcode={errcode}）")
        return raw

    def send_text(
        self,
        *,
        base_url: str,
        token: str,
        to_user_id: str,
        text: str,
        context_token: str = "",
    ) -> None:
        for chunk in _text_chunks(text):
            body = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": f"mommy-{uuid.uuid4().hex}",
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": chunk}}],
                    "context_token": context_token or None,
                },
                "base_info": self.base_info,
            }
            response = self._post(
                "发送微信消息",
                self._url(base_url, "ilink/bot/sendmessage"),
                json=body,
                headers=self._headers(token),
                timeout=_REGULAR_TIMEOUT,
            )
            raw = _json_object(response, "发送微信消息")
            if int(raw.get("ret", 0) or 0):
                raise WeixinApiError("发送微信消息失败")

    def notify(self, *, base_url: str, token: str, started: bool) -> None:
        endpoint = "ilink/bot/msg/notifystart" if started else "ilink/bot/msg/notifystop"
        response = self._post(
            "更新微信连接状态",
            self._url(base_url, endpoint),
            json={"base_info": self.base_info},
            headers=self._headers(token),
            timeout=_REGULAR_TIMEOUT,
        )
        _json_object(response, "更新微信连接状态")


def _text_chunks(text: str, limit: int = 1800) -> list[str]:
    normalized = text.strip() or "（没有生成可显示的内容）"
    return [normalized[start : start + limit] for start in range(0, len(normalized), limit)]
