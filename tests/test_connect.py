from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from mommy_chaogu.cli_commands.connect import (
    ConnectionSpec,
    _connection_spec,
    _mcp_read_timeout,
    _probe_sync,
    build_connect_parser,
    cmd_connect,
)

_REAL_WHICH = shutil.which


def _which_with_fake_kimi(name: str) -> str | None:
    return "/bin/kimi" if name == "kimi" else _REAL_WHICH(name)


def _which_with_fake_cline(name: str) -> str | None:
    return "/bin/cline" if name == "cline" else _REAL_WHICH(name)


@pytest.fixture
def isolated_homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    config = tmp_path / "mommy"
    kimi = tmp_path / "kimi"
    claude = tmp_path / "claude"
    cline = tmp_path / "clinedata"
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(config))
    monkeypatch.setenv("KIMI_CODE_HOME", str(kimi))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CLINE_DATA_DIR", str(cline))
    return config, kimi


def test_connect_parser_defaults_to_market_only() -> None:
    parser = build_connect_parser()
    args = parser.parse_args(["kimi", "--skip-test"])
    assert args.action == "kimi"
    assert args.profile == "market-only"
    assert args.skip_test is True
    assert parser.parse_args(["claude", "--profile", "personal"]).profile == "personal"


def test_connection_spec_keeps_virtualenv_python_fallback() -> None:
    with patch("mommy_chaogu.cli_commands.connect.shutil.which", return_value=None):
        spec = _connection_spec("market-only")
    assert spec.command == sys.executable
    assert spec.args[:2] == ["-m", "mommy_chaogu.agent.mcp_server"]


def test_probe_timeout_matches_mcp_sdk_major_version() -> None:
    with patch(
        "mommy_chaogu.cli_commands.connect.importlib.metadata.version", return_value="1.28.1"
    ):
        assert _mcp_read_timeout() == timedelta(seconds=15)
    with patch(
        "mommy_chaogu.cli_commands.connect.importlib.metadata.version", return_value="2.0.0"
    ):
        assert _mcp_read_timeout() == 15.0


def test_kimi_connect_preserves_other_servers_and_installs_skill(
    isolated_homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config_home, kimi_home = isolated_homes
    kimi_home.mkdir(parents=True)
    (kimi_home / "mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"url": "https://example.test/mcp"}}}),
        encoding="utf-8",
    )
    args = build_connect_parser().parse_args(["kimi", "--skip-test"])
    with patch("mommy_chaogu.cli_commands.connect.shutil.which", side_effect=_which_with_fake_kimi):
        assert cmd_connect(args) == 0

    mcp = json.loads((kimi_home / "mcp.json").read_text(encoding="utf-8"))
    assert "github" in mcp["mcpServers"]
    mommy = mcp["mcpServers"]["mommy-chaogu"]
    assert mommy["args"][-2:] == ["--profile", "market-only"]
    assert "MOMMY_AGENT_DB" in mommy["env"]
    assert (kimi_home / "skills" / "mommy-research" / "SKILL.md").is_file()

    state = json.loads((config_home / "connections.json").read_text(encoding="utf-8"))
    assert state["connections"]["kimi"]["profile"] == "market-only"
    assert "默认未开放持仓" in capsys.readouterr().out


def test_cline_connect_installs_skill_and_mcp(
    isolated_homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config_home, _ = isolated_homes
    cline_settings = Path(os.environ["CLINE_DATA_DIR"]) / "settings"
    args = build_connect_parser().parse_args(["cline", "--skip-test"])
    with patch(
        "mommy_chaogu.cli_commands.connect.shutil.which", side_effect=_which_with_fake_cline
    ):
        assert cmd_connect(args) == 0

    mcp = json.loads((cline_settings / "cline_mcp_settings.json").read_text(encoding="utf-8"))
    assert "mommy-chaogu" in mcp["mcpServers"]
    transport = mcp["mcpServers"]["mommy-chaogu"]["transport"]
    assert transport["type"] == "stdio"
    assert transport["args"][-2:] == ["--profile", "market-only"]
    assert "MOMMY_AGENT_DB" in transport["env"]
    assert (cline_settings / "skills" / "mommy-research" / "SKILL.md").is_file()

    state = json.loads((config_home / "connections.json").read_text(encoding="utf-8"))
    assert state["connections"]["cline"]["profile"] == "market-only"


def test_cline_disconnect_removes_managed_entry(isolated_homes: tuple[Path, Path]) -> None:
    connect = build_connect_parser().parse_args(["cline", "--skip-test"])
    with patch(
        "mommy_chaogu.cli_commands.connect.shutil.which", side_effect=_which_with_fake_cline
    ):
        assert cmd_connect(connect) == 0

    disconnect = build_connect_parser().parse_args(["disconnect", "cline"])
    assert cmd_connect(disconnect) == 0

    cline_settings = Path(os.environ["CLINE_DATA_DIR"]) / "settings"
    after = json.loads((cline_settings / "cline_mcp_settings.json").read_text(encoding="utf-8"))
    assert "mommy-chaogu" not in after["mcpServers"]
    assert not (cline_settings / "skills" / "mommy-research").exists()


def test_kimi_connect_does_not_overwrite_unmanaged_server_without_force(
    isolated_homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, kimi_home = isolated_homes
    kimi_home.mkdir(parents=True)
    (kimi_home / "mcp.json").write_text(
        json.dumps({"mcpServers": {"mommy-chaogu": {"command": "custom"}}}),
        encoding="utf-8",
    )
    args = build_connect_parser().parse_args(["kimi", "--skip-test"])
    with patch("mommy_chaogu.cli_commands.connect.shutil.which", side_effect=_which_with_fake_kimi):
        assert cmd_connect(args) == 2
    assert "非本工具管理" in capsys.readouterr().err


def test_disconnect_removes_only_managed_kimi_entries(isolated_homes: tuple[Path, Path]) -> None:
    _, kimi_home = isolated_homes
    connect = build_connect_parser().parse_args(["kimi", "--skip-test"])
    with patch("mommy_chaogu.cli_commands.connect.shutil.which", side_effect=_which_with_fake_kimi):
        assert cmd_connect(connect) == 0
    config = json.loads((kimi_home / "mcp.json").read_text(encoding="utf-8"))
    config["mcpServers"]["github"] = {"url": "https://example.test/mcp"}
    (kimi_home / "mcp.json").write_text(json.dumps(config), encoding="utf-8")

    disconnect = build_connect_parser().parse_args(["disconnect", "kimi"])
    assert cmd_connect(disconnect) == 0

    after = json.loads((kimi_home / "mcp.json").read_text(encoding="utf-8"))
    assert "mommy-chaogu" not in after["mcpServers"]
    assert "github" in after["mcpServers"]
    assert not (kimi_home / "skills" / "mommy-research").exists()


def test_disconnect_preserves_unmanaged_kimi_entry(
    isolated_homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, kimi_home = isolated_homes
    kimi_home.mkdir(parents=True)
    path = kimi_home / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"mommy-chaogu": {"command": "custom"}}}),
        encoding="utf-8",
    )
    disconnect = build_connect_parser().parse_args(["disconnect", "kimi"])
    assert cmd_connect(disconnect) == 0
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["mcpServers"]["mommy-chaogu"]["command"] == "custom"
    assert "未修改外部配置" in capsys.readouterr().out


def test_probe_lists_profile_scoped_tools(tmp_path: Path) -> None:
    spec = ConnectionSpec(
        command=sys.executable,
        args=["-m", "mommy_chaogu.agent.mcp_server", "--profile", "market-only"],
        env={
            "MOMMY_CONFIG_DIR": str(tmp_path / "config"),
            "MOMMY_MARKET_DB": str(tmp_path / "market.db"),
            "MOMMY_PORTFOLIO_DB": str(tmp_path / "portfolio.db"),
            "MOMMY_AGENT_DB": str(tmp_path / "agent.db"),
            "MOMMY_REFERENCE_DB": str(tmp_path / "reference.db"),
            "AGENT_PROVIDER": "",
            "AGENT_MODEL": "",
            "DEEPSEEK_API_KEY": "",
            "OPENAI_API_KEY": "",
            "MOONSHOT_API_KEY": "",
            "ZAI_API_KEY": "",
            "MINIMAX_API_KEY": "",
        },
        cwd=str(Path.cwd()),
        profile="market-only",
    )
    names = _probe_sync(spec)
    assert "research_stock" in names
    assert "get_quote" in names
    assert "get_portfolio" not in names
    assert "record_research_conclusion" not in names
