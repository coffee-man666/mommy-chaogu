"""Regression coverage for safe treatment of pre-profile connections."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from mommy_chaogu.cli_commands.connect import (
    _connection_spec,
    _state_path,
    _status,
    build_connect_parser,
    cmd_connect,
)


def test_legacy_connection_without_profile_is_market_only_and_not_rewritten(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    config_dir = tmp_path / "config"
    kimi_home = tmp_path / "kimi"
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KIMI_CODE_HOME", str(kimi_home))
    spec = _connection_spec("market-only")
    kimi_home.mkdir(parents=True)
    (kimi_home / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mommy-chaogu": {
                        "command": spec.command,
                        "args": spec.args,
                        "env": spec.env,
                        "cwd": spec.cwd,
                    }
                }
            }
        )
    )
    config_dir.mkdir(parents=True)
    legacy = {
        "spec": {key: value for key, value in spec.as_dict().items() if key != "profile"},
        "skill_path": str(tmp_path / "missing-skill"),
        "skill_hash": "",
    }
    _state_path().write_text(json.dumps({"version": 1, "connections": {"kimi": legacy}}))

    assert _status("kimi") == 0
    output = capsys.readouterr().out
    assert "profile=market-only" in output
    assert "--profile personal 重连" in output
    saved = json.loads(_state_path().read_text())
    assert "profile" not in saved["connections"]["kimi"]["spec"]

    reconnect = build_connect_parser().parse_args(["kimi", "--skip-test"])
    with patch(
        "mommy_chaogu.cli_commands.connect.shutil.which",
        side_effect=lambda name: "/bin/kimi" if name == "kimi" else None,
    ):
        assert cmd_connect(reconnect) == 0
    saved = json.loads(_state_path().read_text())
    item = saved["connections"]["kimi"]
    assert item["profile"] == "market-only"
    assert item["spec"]["profile"] == "market-only"
    assert "privacy_consent_version" not in item

    upgrade = build_connect_parser().parse_args(
        ["kimi", "--profile", "personal", "--skip-test"]
    )
    with patch(
        "mommy_chaogu.cli_commands.connect.shutil.which",
        side_effect=lambda name: "/bin/kimi" if name == "kimi" else None,
    ):
        assert cmd_connect(upgrade) == 0
    upgraded = json.loads(_state_path().read_text())["connections"]["kimi"]
    assert upgraded["profile"] == "personal"
    assert upgraded["privacy_consent_version"]


def test_market_only_connection_does_not_record_personal_consent(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi"))
    args = build_connect_parser().parse_args(["kimi", "--profile", "market-only", "--skip-test"])
    with patch(
        "mommy_chaogu.cli_commands.connect.shutil.which",
        side_effect=lambda name: "/bin/kimi" if name == "kimi" else None,
    ):
        assert cmd_connect(args) == 0
    state = json.loads(_state_path().read_text())
    item = state["connections"]["kimi"]
    assert item["profile"] == "market-only"
    assert "privacy_consent_version" not in item
