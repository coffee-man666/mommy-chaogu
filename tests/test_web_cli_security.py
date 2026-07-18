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
