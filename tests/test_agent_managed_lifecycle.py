"""Trust-focused tests for the lean Agent-managed lifecycle CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mommy_chaogu.cli_commands.agent_managed import (
    connect_payload,
    detect_payload,
    doctor_payload,
    plan_payload,
    repair_payload,
    run_agent_managed,
)
from mommy_chaogu.cli_commands.connect import ConnectError
from mommy_chaogu.coding_agents.base import ConnectionSpec


def _spec(profile: str = "market-only") -> ConnectionSpec:
    return ConnectionSpec(
        command="/usr/bin/python3",
        args=["-m", "mommy_chaogu.agent.mcp_server", "--profile", profile],
        env={},
        cwd="/tmp/project",
        profile=profile,  # type: ignore[arg-type]
    )


def _previous(profile: str = "market-only") -> dict[str, object]:
    return {"profile": profile, "spec": _spec(profile).as_dict(), "skills": {}}


def _healthy_tools(profile: str = "market-only") -> list[str]:
    tools = ["get_quote", "research_market_brief", "research_us_market", "research_stock"]
    if profile == "personal":
        tools.extend(
            [
                "get_memory_context",
                "research_portfolio",
                "record_research_conclusion",
                "strategy_save",
                "strategy_list",
                "strategy_get",
                "strategy_archive",
                "strategy_prepare_application",
                "strategy_prepare_monitor",
                "strategy_activate_monitor",
            ]
        )
    return tools


def _skill_checks() -> list[dict[str, object]]:
    return [
        {"name": name, "status": "ok", "path": f"/skills/{name}", "managed": True}
        for name in ("mommy-onboard", "mommy-research", "mommy-strategy")
    ]


def test_detect_explains_the_toolbox_without_claiming_generic_managed_support() -> None:
    with (
        patch(
            "mommy_chaogu.cli_commands.agent_managed._state_connections",
            return_value={},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._host_status",
            side_effect=lambda host, _connections: {
                "host": host,
                "installed": False,
                "configured": False,
            },
        ),
    ):
        result = detect_payload()

    assert result["product"]["positioning"] == "可由宿主 Agent 编排的本地投研工具箱"
    assert result["managed_connection_hosts"] == ["claude", "kimi", "cline", "codex"]
    assert result["generic_mcp_available"] is False
    assert result["portable_stdio_mcp_available"] is True
    assert result["auto_candidates"] == []
    assert "不会把其他 MCP Agent 伪装成已支持" in result["message"]


def test_plan_is_read_only_and_shows_every_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SKILLS_DIR", str(tmp_path / "skills"))
    with (
        patch(
            "mommy_chaogu.cli_commands.agent_managed.detect_payload",
            return_value={"auto_selected": "codex", "auto_candidates": ["codex"]},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._connection_spec",
            return_value=_spec("market-only"),
        ),
    ):
        result = plan_payload("auto", "market-only")

    assert result["ok"] is True
    assert result["requires_user_confirmation"] is True
    changes = result["changes"]
    assert isinstance(changes, dict)
    assert str(changes["connection_state_target"]).endswith("connections.json")
    skills = changes["skills"]
    assert isinstance(skills, list)
    assert [item["name"] for item in skills] == [
        "mommy-onboard",
        "mommy-research",
        "mommy-strategy",
        "market-watch-loop",
    ]
    privacy = result["privacy"]
    assert isinstance(privacy, dict)
    assert privacy["personal_data_available"] is False
    assert not (tmp_path / "skills").exists()


def test_doctor_runs_real_probe_and_enforces_requested_timeout() -> None:
    previous = _previous("personal")
    with (
        patch("mommy_chaogu.cli_commands.agent_managed._resolve_host", return_value="kimi"),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._state_connections",
            return_value={"kimi": previous},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._host_status",
            return_value={"configured": True, "state": "已连接"},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._skill_checks",
            return_value=_skill_checks(),
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._probe_sync",
            return_value=_healthy_tools("personal"),
        ) as probe,
    ):
        result = doctor_payload("auto", 3.5)

    probe.assert_called_once_with(_spec("personal"), timeout_seconds=3.5)
    checks = {item["name"]: item for item in result["checks"]}
    assert result["ok"] is True
    assert checks["mcp_initialize_and_list_tools"]["status"] == "ok"
    assert checks["live_market_data"]["status"] == "not_checked"
    # Two-layer completion: installation is available, an investing goal is not.
    assert result["integration_available"] is True
    assert result["investing_goal_complete"] is False
    assert "不得把这条目标当成安装前置条件强制询问" in result["investing_goal_completion_rule"]
    assert "自定义指标或组合流程的一次受支持执行" in result["exploration_examples"]


def test_doctor_never_infers_mcp_health_from_configuration_only() -> None:
    previous = _previous()
    with (
        patch("mommy_chaogu.cli_commands.agent_managed._resolve_host", return_value="kimi"),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._state_connections",
            return_value={"kimi": previous},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._host_status",
            return_value={"configured": True, "state": "已连接"},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._skill_checks",
            return_value=_skill_checks(),
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._probe_sync",
            side_effect=ConnectError("MCP initialize 超时"),
        ),
    ):
        result = doctor_payload("kimi", 1.0)

    checks = {item["name"]: item for item in result["checks"]}
    assert result["ok"] is False
    assert checks["mcp_initialize_and_list_tools"]["status"] == "failed"
    assert checks["privacy_boundary"]["status"] == "not_checked"
    assert "mcp_initialize_and_list_tools" in result["blocking_checks"]


def test_market_only_doctor_fails_on_private_tool_leak() -> None:
    previous = _previous()
    with (
        patch("mommy_chaogu.cli_commands.agent_managed._resolve_host", return_value="codex"),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._state_connections",
            return_value={"codex": previous},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._host_status",
            return_value={"configured": True, "state": "已连接"},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._skill_checks",
            return_value=_skill_checks(),
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._probe_sync",
            return_value=[*_healthy_tools(), "strategy_save"],
        ),
    ):
        result = doctor_payload("codex", 20.0)

    checks = {item["name"]: item for item in result["checks"]}
    assert result["ok"] is False
    assert result["integration_available"] is False
    assert checks["privacy_boundary"]["status"] == "failed"
    assert checks["privacy_boundary"]["unexpected_private_tools"] == ["strategy_save"]


def test_connect_uses_existing_connector_then_requires_real_doctor() -> None:
    calls: list[tuple[str, str, bool, bool]] = []

    def fake_connect(host: str, profile: str, *, force: bool, skip_test: bool) -> int:
        calls.append((host, profile, force, skip_test))
        print("human connector output that must not leak into JSON")
        return 0

    with (
        patch("mommy_chaogu.cli_commands.agent_managed._resolve_host", return_value="codex"),
        patch("mommy_chaogu.cli_commands.agent_managed._connect", side_effect=fake_connect),
        patch(
            "mommy_chaogu.cli_commands.agent_managed.doctor_payload",
            return_value={"ok": False, "blocking_checks": ["mcp_initialize_and_list_tools"]},
        ),
    ):
        result = connect_payload("auto", "market-only", 2.0)

    assert calls == [("codex", "market-only", False, True)]
    assert result["configuration_written"] is True
    assert result["connected"] is False
    assert result["ok"] is False
    assert "不能宣称连接成功" in str(result["message"])


def test_repair_preserves_modified_skill_instead_of_forcing() -> None:
    previous = _previous()
    modified = [
        {
            "name": "mommy-strategy",
            "status": "modified",
            "path": "/skills/mommy-strategy",
            "managed": True,
        }
    ]
    with (
        patch("mommy_chaogu.cli_commands.agent_managed._resolve_host", return_value="kimi"),
        patch(
            "mommy_chaogu.cli_commands.agent_managed.doctor_payload",
            return_value={"ok": False},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._state_connections",
            return_value={"kimi": previous},
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._skill_checks",
            return_value=modified,
        ),
        patch(
            "mommy_chaogu.cli_commands.agent_managed._host_status",
            return_value={"state": "已连接"},
        ),
        patch("mommy_chaogu.cli_commands.agent_managed._connect") as connect,
    ):
        result = repair_payload("kimi", 20.0, apply=True)

    assert result["ok"] is False
    assert result["applied"] is False
    assert result["fixes"][0]["safe_to_apply"] is False
    connect.assert_not_called()


def test_invalid_json_cli_arguments_return_one_machine_error() -> None:
    result, exit_code = run_agent_managed(["plan", "--host", "unknown", "--json"])

    assert exit_code == 2
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
