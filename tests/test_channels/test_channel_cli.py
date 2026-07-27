from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mommy_chaogu.channels.store import WeixinCredentials, WeixinStore
from mommy_chaogu.cli_commands.channel import build_channel_parser, cmd_channel


def test_channel_parser_supports_local_state_override(tmp_path: Path) -> None:
    args = build_channel_parser().parse_args(["--state-dir", str(tmp_path), "weixin", "status"])
    assert args.state_dir == tmp_path
    assert args.channel == "weixin"
    assert args.action == "status"


def test_channel_parser_supports_background_lifecycle() -> None:
    parser = build_channel_parser()
    assert parser.parse_args(["weixin", "start"]).action == "start"
    assert parser.parse_args(["weixin", "stop"]).action == "stop"


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
    with patch("mommy_chaogu.cli_commands.channel.gateway_process_pid", return_value=None):
        assert cmd_channel(status) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "已授权但助手离线" in output
    assert "bot@im.bot" in output
    assert "must-not-print" not in output

    logout = parser.parse_args(["--state-dir", str(tmp_path), "weixin", "logout"])
    with patch("mommy_chaogu.cli_commands.channel.stop_gateway_process", return_value=False):
        assert cmd_channel(logout) == 0
    assert store.load_credentials() is None


def test_status_reports_live_gateway(tmp_path: Path, capsys: object) -> None:
    store = WeixinStore(tmp_path)
    store.save_credentials(
        WeixinCredentials(
            account_id="bot@im.bot",
            token="secret",
            base_url="https://ilink.example",
            owner_user_id="owner",
        )
    )
    args = build_channel_parser().parse_args(["--state-dir", str(tmp_path), "weixin", "status"])
    with patch("mommy_chaogu.cli_commands.channel.gateway_process_pid", return_value=4321):
        assert cmd_channel(args) == 0
    assert "微信助手在线：bot@im.bot（PID 4321）" in capsys.readouterr().out  # type: ignore[attr-defined]
