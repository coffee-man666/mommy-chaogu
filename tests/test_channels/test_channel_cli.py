from __future__ import annotations

from pathlib import Path

from mommy_chaogu.channels.store import WeixinCredentials, WeixinStore
from mommy_chaogu.cli_commands.channel import build_channel_parser, cmd_channel


def test_channel_parser_supports_local_state_override(tmp_path: Path) -> None:
    args = build_channel_parser().parse_args(["--state-dir", str(tmp_path), "weixin", "status"])
    assert args.state_dir == tmp_path
    assert args.channel == "weixin"
    assert args.action == "status"


def test_status_and_logout_are_local_only(tmp_path: Path, capsys: object) -> None:
    store = WeixinStore(tmp_path)
    store.save_credentials(
        WeixinCredentials(
            account_id="bot@im.bot",
            token="must-not-print",
            base_url="https://ilink.example",
            owner_user_id="owner",
        )
    )
    parser = build_channel_parser()

    status = parser.parse_args(["--state-dir", str(tmp_path), "weixin", "status"])
    assert cmd_channel(status) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "bot@im.bot" in output
    assert "must-not-print" not in output

    logout = parser.parse_args(["--state-dir", str(tmp_path), "weixin", "logout"])
    assert cmd_channel(logout) == 0
    assert store.load_credentials() is None
