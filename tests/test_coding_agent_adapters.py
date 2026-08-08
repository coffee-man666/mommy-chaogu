"""Shared contract tests for Claude, Kimi, Cline and Codex adapters."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.agent.research_tools import allowed_base_tool_names, allowed_research_tool_names
from mommy_chaogu.cli_commands.connect import _bundled_skill_dir
from mommy_chaogu.coding_agents import adapter_for
from mommy_chaogu.coding_agents.base import ConnectionSpec, directory_hash

TARGETS = ("claude", "kimi", "cline", "codex")


@pytest.fixture(params=TARGETS)
def adapter_case(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    target = str(request.param)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi"))
    monkeypatch.setenv("CLINE_DATA_DIR", str(tmp_path / "cline"))
    monkeypatch.setenv("CODEX_SKILLS_DIR", str(tmp_path / "codex-skills"))
    spec = ConnectionSpec(
        command="/usr/bin/python3",
        args=["-m", "mommy_chaogu.agent.mcp_server", "--profile", "personal"],
        env={
            "MOMMY_AGENT_DB": str(tmp_path / "agent.db"),
            "MOMMY_PORTFOLIO_DB": str(tmp_path / "portfolio.db"),
        },
        cwd=str(Path.cwd()),
        profile="personal",
    )
    codex_state: dict[str, Any] = {}

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if target == "codex":
            if command[2:4] == ["get", "mommy-chaogu"]:
                return subprocess.CompletedProcess(
                    command, 0 if codex_state else 1, json.dumps(codex_state), ""
                )
            if command[2] == "remove":
                codex_state.clear()
            if command[2] == "add":
                divider = command.index("--")
                env: dict[str, str] = {}
                before = command[4:divider]
                for index, value in enumerate(before):
                    if value == "--env":
                        key, item = before[index + 1].split("=", 1)
                        env[key] = item
                codex_state.update(
                    {"command": command[divider + 1], "args": command[divider + 2 :], "env": env}
                )
            return subprocess.CompletedProcess(command, 0, "", "")
        if target == "claude":
            path = Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".claude.json"
            value = json.loads(path.read_text()) if path.is_file() else {"mcpServers": {}}
            if "remove" in command:
                value["mcpServers"].pop("mommy-chaogu", None)
            else:
                divider = command.index("--")
                env = {}
                for index, item in enumerate(command[:divider]):
                    if item == "--env":
                        key, value_item = command[index + 1].split("=", 1)
                        env[key] = value_item
                value["mcpServers"]["mommy-chaogu"] = {
                    "command": command[divider + 1],
                    "args": command[divider + 2 :],
                    "env": env,
                }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_which(name: str) -> str:
        return f"/bin/{name}"

    adapter = adapter_for(
        target,
        previous=None,
        force=False,
        which=fake_which,
        command_runner=fake_run,
        entry_reader=lambda: codex_state or None,
    )
    return {
        "target": target,
        "spec": spec,
        "adapter": adapter,
        "tmp_path": tmp_path,
        "fake_run": fake_run,
        "fake_which": fake_which,
        "codex_state": codex_state,
    }


def test_unified_adapter_connection_contract(adapter_case: dict[str, Any]) -> None:
    adapter = adapter_case["adapter"]
    spec: ConnectionSpec = adapter_case["spec"]
    skill = adapter.install_skill(_bundled_skill_dir())
    adapter.register_mcp(spec)
    assert skill.is_dir()
    assert spec.profile == "personal"
    assert spec.args[-2:] == ["--profile", "personal"]
    assert {"MOMMY_AGENT_DB", "MOMMY_PORTFOLIO_DB"} <= set(spec.env)

    previous = {
        "profile": "personal",
        "spec": spec.as_dict(),
        "skill_path": str(skill),
        "skill_hash": directory_hash(skill),
    }
    connected = adapter_for(
        adapter_case["target"],
        previous=previous,
        force=False,
        which=adapter_case["fake_which"],
        command_runner=adapter_case["fake_run"],
        entry_reader=lambda: adapter_case["codex_state"] or None,
    ).inspect_status()
    assert connected.configured is True
    assert connected.profile == "personal"
    assert connected.skill_ok is True

    (skill / "SKILL.md").write_text("user modification")
    modified = adapter_for(
        adapter_case["target"],
        previous=previous,
        force=False,
        which=adapter_case["fake_which"],
        command_runner=adapter_case["fake_run"],
        entry_reader=lambda: adapter_case["codex_state"] or None,
    ).inspect_status()
    assert modified.skill_ok is False


def test_disconnect_preserves_modified_skill_and_external_servers(
    adapter_case: dict[str, Any],
) -> None:
    adapter = adapter_case["adapter"]
    spec: ConnectionSpec = adapter_case["spec"]
    skill = adapter.install_skill(_bundled_skill_dir())
    adapter.register_mcp(spec)
    previous = {
        "spec": spec.as_dict(),
        "skill_path": str(skill),
        "skill_hash": directory_hash(skill),
    }
    (skill / "SKILL.md").write_text("user modification")
    # Existing adapters only remove mommy's own entry; their config loaders keep other servers.
    adapter_for(
        adapter_case["target"],
        previous=previous,
        force=False,
        which=adapter_case["fake_which"],
        command_runner=adapter_case["fake_run"],
        entry_reader=lambda: adapter_case["codex_state"] or None,
    ).disconnect()
    assert (skill / "SKILL.md").read_text() == "user modification"


def test_unmanaged_same_name_is_not_overwritten(adapter_case: dict[str, Any]) -> None:
    target = adapter_case["target"]
    if target == "kimi":
        path = adapter_case["tmp_path"] / "kimi" / "mcp.json"
    elif target == "cline":
        path = adapter_case["tmp_path"] / "cline" / "settings" / "cline_mcp_settings.json"
    elif target == "claude":
        path = adapter_case["tmp_path"] / "claude" / ".claude.json"
    else:
        adapter_case["codex_state"]["command"] = "user-managed"
        path = None
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if target == "cline":
            value = {"mcpServers": {"mommy-chaogu": {"transport": {"command": "user-managed"}}}}
        else:
            value = {"mcpServers": {"mommy-chaogu": {"command": "user-managed"}}}
        path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match=r"非本工具管理|修改"):
        adapter_case["adapter"].register_mcp(adapter_case["spec"])


@pytest.mark.parametrize("profile", ["personal", "market-only"])
def test_profile_contract_and_market_only_isolation(profile: str) -> None:
    assert "get_quote" in allowed_base_tool_names(profile)  # type: ignore[arg-type]
    personal = allowed_research_tool_names("personal")
    market = allowed_research_tool_names("market-only")
    assert "record_research_conclusion" in personal
    assert "record_research_conclusion" not in market
    assert "research_portfolio" not in market
