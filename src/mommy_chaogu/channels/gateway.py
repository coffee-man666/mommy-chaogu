"""Secure single-owner Weixin message gateway."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

from mommy_chaogu.channels.store import WeixinCredentials, WeixinStore
from mommy_chaogu.channels.weixin import WeixinApiError, WeixinClient

_log = logging.getLogger(__name__)


def weixin_session_id(account_id: str, sender_id: str) -> str:
    digest = hashlib.sha256(f"{account_id}:{sender_id}".encode()).hexdigest()[:24]
    return f"weixin-{digest}"


def _message_text(message: dict[str, Any]) -> str:
    items = message.get("item_list", [])
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict) or int(item.get("type", 0) or 0) != 1:
            continue
        text_item = item.get("text_item")
        if isinstance(text_item, dict):
            return str(text_item.get("text", "")).strip()
    return ""


class WeixinGateway:
    """Poll one authorized Weixin account and dispatch private text to a responder."""

    def __init__(
        self,
        *,
        client: WeixinClient,
        store: WeixinStore,
        credentials: WeixinCredentials,
        respond: Callable[[str, str], str],
    ) -> None:
        self.client = client
        self.store = store
        self.credentials = credentials
        self.respond = respond

    def run_once(self) -> int:
        state = self.store.load_state()
        payload = self.client.get_updates(
            base_url=self.credentials.base_url,
            token=self.credentials.token,
            get_updates_buf=state.get_updates_buf,
        )

        new_cursor = str(payload.get("get_updates_buf", ""))
        if new_cursor:
            state.get_updates_buf = new_cursor
            self.store.save_state(state)

        messages = payload.get("msgs", [])
        if not isinstance(messages, list):
            return 0

        handled = 0
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            message = raw
            sender = str(message.get("from_user_id", "")).strip()
            # Tencent QR login returns the scanner's user ID. It is the only default
            # principal; other contacts and group messages are denied silently.
            if sender != self.credentials.owner_user_id:
                _log.warning("ignored Weixin message from an unpaired sender")
                continue
            if str(message.get("group_id", "")).strip():
                _log.warning("ignored Weixin group message")
                continue
            if int(message.get("message_type", 0) or 0) != 1:
                continue
            text = _message_text(message)
            if not text:
                continue

            context_token = str(message.get("context_token", "")).strip()
            if context_token:
                state.context_tokens[sender] = context_token
                self.store.save_state(state)

            session_id = weixin_session_id(self.credentials.account_id, sender)
            try:
                reply = self.respond(session_id, text)
            except Exception:
                _log.exception("Weixin agent response failed")
                reply = "这次分析没有完成，请稍后再试。"
            self.client.send_text(
                base_url=self.credentials.base_url,
                token=self.credentials.token,
                to_user_id=sender,
                text=reply,
                context_token=state.context_tokens.get(sender, ""),
            )
            handled += 1
        return handled

    def run_forever(self, *, stop: Callable[[], bool] = lambda: False) -> None:
        try:
            self.client.notify(
                base_url=self.credentials.base_url,
                token=self.credentials.token,
                started=True,
            )
        except WeixinApiError:
            _log.warning("failed to notify Weixin channel start", exc_info=True)

        failures = 0
        try:
            while not stop():
                try:
                    self.run_once()
                    failures = 0
                except WeixinApiError:
                    failures += 1
                    delay = min(30, 2**failures)
                    _log.warning("Weixin polling failed; retrying in %ss", delay, exc_info=True)
                    time.sleep(delay)
        finally:
            try:
                self.client.notify(
                    base_url=self.credentials.base_url,
                    token=self.credentials.token,
                    started=False,
                )
            except WeixinApiError:
                _log.warning("failed to notify Weixin channel stop", exc_info=True)
