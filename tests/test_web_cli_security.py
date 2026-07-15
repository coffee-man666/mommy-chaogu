"""Web CLI safe-binding behavior."""

from __future__ import annotations

from mommy_chaogu.cli import build_web_parser, cmd_web_serve


def test_web_defaults_to_loopback() -> None:
    args = build_web_parser().parse_args([])
    assert args.host == "127.0.0.1"


def test_remote_binding_requires_token(capsys: object) -> None:
    args = build_web_parser().parse_args(["--host", "0.0.0.0"])
    assert cmd_web_serve(args) == 2
    assert "MOMMY_API_TOKEN" in capsys.readouterr().err  # type: ignore[attr-defined]
