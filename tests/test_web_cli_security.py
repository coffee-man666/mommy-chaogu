"""Web CLI safe-binding behavior."""

from __future__ import annotations

import pytest

from mommy_chaogu.cli import build_web_parser, cmd_web_serve


def test_web_defaults_to_loopback() -> None:
    args = build_web_parser().parse_args([])
    assert args.host == "127.0.0.1"


@pytest.mark.parametrize("value", ["invalid", "0", "65536"])
def test_web_invalid_environment_port_falls_back(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PORT", value)
    assert build_web_parser().parse_args([]).port == 8000


def test_web_defaults_to_environment_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    assert build_web_parser().parse_args([]).port == 8080


def test_explicit_web_port_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    assert build_web_parser().parse_args(["--port", "9000"]).port == 9000


def test_remote_binding_requires_token(capsys: object) -> None:
    args = build_web_parser().parse_args(["--host", "0.0.0.0"])
    assert cmd_web_serve(args) == 2
    assert "MOMMY_API_TOKEN" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_remote_bind_disables_local_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-loopback bind must never expose setup endpoints without a token."""
    captured: dict[str, object] = {}
    monkeypatch.setenv("MOMMY_API_TOKEN", "owner-secret")
    monkeypatch.setattr(
        "mommy_chaogu.web.create_app",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)

    args = build_web_parser().parse_args(["--host", "0.0.0.0"])
    assert cmd_web_serve(args) == 0
    assert captured["local_setup_enabled"] is False


def test_allow_unauthenticated_remote_still_disables_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--allow-unauthenticated-remote must NOT make setup reachable over the wire."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "mommy_chaogu.web.create_app",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)

    args = build_web_parser().parse_args(["--host", "0.0.0.0", "--allow-unauthenticated-remote"])
    assert cmd_web_serve(args) == 0
    assert captured["api_token"] == ""
    assert captured["local_setup_enabled"] is False


def test_loopback_ignores_configured_token_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("MOMMY_API_TOKEN", "configured-for-remote")
    monkeypatch.setattr(
        "mommy_chaogu.web.create_app",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)

    args = build_web_parser().parse_args([])
    assert cmd_web_serve(args) == 0
    assert captured["api_token"] == ""
    # loopback bind enables the local setup wizard without an owner token
    assert captured["local_setup_enabled"] is True


def test_loopback_can_explicitly_require_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("MOMMY_API_TOKEN", "configured-for-remote")
    monkeypatch.setattr(
        "mommy_chaogu.web.create_app",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)

    args = build_web_parser().parse_args(["--require-auth"])
    assert cmd_web_serve(args) == 0
    assert captured["api_token"] == "configured-for-remote"
    # loopback still enables setup even when auth is on
    assert captured["local_setup_enabled"] is True
