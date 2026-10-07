"""区域双端点 provider 的认证失败探测（MiniMax 国内站 / 国际站）。

MiniMax 的 key 与站点绑定：国内账号的 key 只在 ``api.minimaxi.com`` 认，
海外账号的 key 只在 ``api.minimax.io`` 认。配置表里只能放一个默认值，
另一站的用户会撞上 401——而错误信息同样是 401，不提示"你站选错了"，
用户几乎无法自查。``mommy setup`` 的验证环节应当自动探测另一站。
"""

from __future__ import annotations

from typing import Any

import pytest

from mommy_chaogu.agent import llm
from mommy_chaogu.setup import validate_llm_connection


class _AuthError(Exception):
    """模拟 OpenAI SDK 的 401。"""

    def __init__(self) -> None:
        super().__init__("Error code: 401 - {'error': {'type': 'authorized_error'}}")


class _FakeCompletions:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def create(self, **kwargs: Any) -> Any:
        if "minimax.io" not in self._base_url:
            raise _AuthError()
        return type("R", (), {"choices": [type("C", (), {"message": None})()]})()


class _FakeClient:
    def __init__(self, base_url: str) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(base_url)})()


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)


def test_alternate_base_urls_cover_both_minimax_hosts() -> None:
    assert "https://api.minimax.io/v1" in llm.ALTERNATE_BASE_URLS["minimax"]
    assert "https://api.minimaxi.com/v1" in llm.ALTERNATE_BASE_URLS["minimax"]


def test_minimax_default_base_url_is_documented(monkeypatch: pytest.MonkeyPatch) -> None:
    assert llm.resolve_base_url("minimax") == "https://api.minimaxi.com/v1"


def test_create_client_accepts_explicit_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "openai", type("M", (), {"OpenAI": _FakeOpenAI}))
    llm.create_client("minimax", "sk-test", base_url="https://api.minimax.io/v1")
    assert captured["base_url"] == "https://api.minimax.io/v1"


def test_validate_detects_wrong_region_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认站 401、备用站能通时，必须给出可执行的修复建议而不是"key 无效"。"""
    monkeypatch.setattr(
        llm,
        "create_client",
        lambda provider, key, **kw: _FakeClient(
            kw.get("base_url") or "https://api.minimaxi.com/v1"
        ),
    )
    ok, message = validate_llm_connection("minimax", "MiniMax-M3", "sk-test")
    assert ok is False
    assert "MINIMAX_BASE_URL" in message
    assert "api.minimax.io" in message
    # 不能再是那句无信息量的"key 无效"
    assert "无效" not in message


def test_validate_reports_invalid_key_when_both_hosts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm, "create_client", lambda provider, key, **kw: _FakeClient("https://nothing.invalid/v1")
    )
    ok, message = validate_llm_connection("minimax", "MiniMax-M3", "sk-bad")
    assert ok is False
    assert "无效" in message


def test_validate_passes_when_default_host_works(monkeypatch: pytest.MonkeyPatch) -> None:
    class _OK:
        def create(self, **kwargs: Any) -> Any:
            return type("R", (), {"choices": [1]})()

    monkeypatch.setattr(
        llm,
        "create_client",
        lambda provider, key, **kw: type(
            "C", (), {"chat": type("X", (), {"completions": _OK()})()}
        )(),
    )
    ok, message = validate_llm_connection("minimax", "MiniMax-M3", "sk-ok")
    assert ok is True
    assert message == "连接成功"
