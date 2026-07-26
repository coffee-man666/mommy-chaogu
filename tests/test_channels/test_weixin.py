from __future__ import annotations

import json
import stat
from pathlib import Path

from mommy_chaogu.channels.gateway import WeixinGateway
from mommy_chaogu.channels.store import WeixinCredentials, WeixinStore
from mommy_chaogu.channels.weixin import WeixinClient


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, *, gets: list[FakeResponse], posts: list[FakeResponse]) -> None:
        self.gets = gets
        self.posts = posts
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self.gets.pop(0)

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self.posts.pop(0)


def _credentials() -> WeixinCredentials:
    return WeixinCredentials(
        account_id="bot@im.bot",
        token="secret-token",
        base_url="https://ilink.example",
        owner_user_id="owner-user",
    )


def test_store_persists_credentials_privately(tmp_path: Path) -> None:
    store = WeixinStore(tmp_path)
    credentials = _credentials()
    store.save_credentials(credentials)

    assert store.load_credentials() == credentials
    assert stat.S_IMODE(store.credentials_path.stat().st_mode) == 0o600

    store.clear()
    assert store.load_credentials() is None


def test_qr_login_returns_scanner_as_local_owner() -> None:
    session = FakeSession(
        gets=[
            FakeResponse(
                {
                    "status": "confirmed",
                    "bot_token": "bot-secret",
                    "ilink_bot_id": "bot@im.bot",
                    "ilink_user_id": "scanner-user",
                    "baseurl": "https://redirect.example",
                }
            )
        ],
        posts=[FakeResponse({"qrcode": "qr-id", "qrcode_img_content": "weixin://qr"})],
    )
    shown: list[str] = []
    client = WeixinClient(session)

    result = client.login(on_qr=shown.append, sleep=lambda _seconds: None)

    assert result.connected is True
    assert result.owner_user_id == "scanner-user"
    assert result.account_id == "bot@im.bot"
    assert result.base_url == "https://redirect.example"
    assert shown == ["weixin://qr"]
    assert all("bot-secret" not in url for _, url, _ in session.calls)


def test_gateway_routes_only_owner_private_text(tmp_path: Path) -> None:
    session = FakeSession(
        gets=[],
        posts=[
            FakeResponse(
                {
                    "ret": 0,
                    "get_updates_buf": "cursor-2",
                    "msgs": [
                        {
                            "from_user_id": "intruder",
                            "message_type": 1,
                            "item_list": [{"type": 1, "text_item": {"text": "偷看持仓"}}],
                        },
                        {
                            "from_user_id": "owner-user",
                            "group_id": "group",
                            "message_type": 1,
                            "item_list": [{"type": 1, "text_item": {"text": "群聊消息"}}],
                        },
                        {
                            "from_user_id": "owner-user",
                            "message_type": 1,
                            "context_token": "context-1",
                            "item_list": [{"type": 1, "text_item": {"text": "今天怎么样"}}],
                        },
                    ],
                }
            ),
            FakeResponse({"ret": 0}),
        ],
    )
    store = WeixinStore(tmp_path)
    received: list[tuple[str, str]] = []

    def respond(session_id: str, text: str) -> str:
        received.append((session_id, text))
        return "大盘平稳"

    gateway = WeixinGateway(
        client=WeixinClient(session),
        store=store,
        credentials=_credentials(),
        respond=respond,
    )

    assert gateway.run_once() == 1
    assert len(received) == 1
    assert received[0][0].startswith("weixin-")
    assert received[0][1] == "今天怎么样"
    state = store.load_state()
    assert state.get_updates_buf == "cursor-2"
    assert state.context_tokens == {"owner-user": "context-1"}

    send_call = session.calls[-1]
    sent_json = send_call[2]["json"]
    assert isinstance(sent_json, dict)
    assert sent_json["msg"]["to_user_id"] == "owner-user"  # type: ignore[index]
    assert sent_json["msg"]["context_token"] == "context-1"  # type: ignore[index]


def test_gateway_returns_friendly_error_when_agent_fails(tmp_path: Path) -> None:
    session = FakeSession(
        gets=[],
        posts=[
            FakeResponse(
                {
                    "ret": 0,
                    "msgs": [
                        {
                            "from_user_id": "owner-user",
                            "message_type": 1,
                            "item_list": [{"type": 1, "text_item": {"text": "分析一下"}}],
                        }
                    ],
                }
            ),
            FakeResponse({"ret": 0}),
        ],
    )

    def fail(_session_id: str, _text: str) -> str:
        raise RuntimeError("provider leaked-secret")

    gateway = WeixinGateway(
        client=WeixinClient(session),
        store=WeixinStore(tmp_path),
        credentials=_credentials(),
        respond=fail,
    )

    assert gateway.run_once() == 1
    sent_json = session.calls[-1][2]["json"]
    assert isinstance(sent_json, dict)
    sent_text = sent_json["msg"]["item_list"][0]["text_item"]["text"]  # type: ignore[index]
    assert sent_text == "这次分析没有完成，请稍后再试。"
    assert "leaked-secret" not in sent_text
