"""Lean, machine-readable lifecycle commands for an external host Agent.

This module intentionally reuses the established connector and MCP server.  It
does not introduce a second capability runtime or declare onboarding complete:
the first interpreted, evidence-backed research result remains a host-Agent and
user interaction.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from mommy_chaogu.agent.research_tools import (
    allowed_base_tool_names,
    allowed_research_tool_names,
)
from mommy_chaogu.cli_commands.connect import (
    ConnectError,
    _adapter,
    _bundled_skill_dirs,
    _connect,
    _connection_spec,
    _load_state,
    _probe_sync,
    _state_path,
)
from mommy_chaogu.coding_agents.base import (
    agent_home,
    directory_hash,
    managed_skill_records,
    previous_spec,
    skill_dir,
)
from mommy_chaogu.version import __version__

SUPPORTED_HOSTS = ("claude", "kimi", "cline", "codex")
_PERSONAL_REQUIRED_TOOLS = {
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
}
_MARKET_ONLY_ALLOWED_TOOLS = allowed_base_tool_names("market-only") | allowed_research_tool_names(
    "market-only"
)
_PUBLIC_REQUIRED_TOOLS = {
    "get_quote",
    "research_market_brief",
    "research_us_market",
    "research_stock",
}


class AgentManagedError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class _MachineParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise AgentManagedError("invalid_arguments", message)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _envelope(command: str, *, ok: bool, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "command": command,
        "ok": ok,
        "app_version": __version__,
        "generated_at": _timestamp(),
        **payload,
    }


def _emit(payload: dict[str, Any], exit_code: int) -> NoReturn:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(exit_code)


def _state_connections() -> dict[str, Any]:
    state = _load_state()
    connections = state.get("connections", {})
    if not isinstance(connections, dict):
        raise AgentManagedError("state_invalid", "连接状态格式无效")
    return connections


def _host_version(executable: str | None) -> str | None:
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:200] if result.returncode == 0 and value else None


def _host_status(host: str, connections: dict[str, Any]) -> dict[str, Any]:
    item = connections.get(host)
    previous = item if isinstance(item, dict) else None
    executable = shutil.which(host)
    result: dict[str, Any] = {
        "host": host,
        "display_name": {
            "claude": "Claude Code",
            "kimi": "Kimi Code",
            "cline": "Cline",
            "codex": "Codex",
        }[host],
        "executable": executable,
        "version": _host_version(executable),
        "installed": executable is not None,
        "managed_connection": previous is not None,
        "configured": False,
        "skills_ok": False,
        "profile": previous.get("profile") if previous else None,
    }
    try:
        status = _adapter(host, previous, force=False).inspect_status()
        skill_details = _skill_checks(host, previous) if previous is not None else []
        result.update(
            {
                "configured": status.configured,
                "skills_ok": bool(skill_details)
                and all(item["status"] == "ok" for item in skill_details),
                "skills": skill_details,
                "profile": status.profile if previous else None,
                "state": status.state,
            }
        )
    except (OSError, RuntimeError, ValueError) as exc:
        result["state"] = "diagnostic_failed"
        result["diagnostic_error"] = str(exc)
    return result


def detect_payload() -> dict[str, Any]:
    connections = _state_connections()
    hosts = [_host_status(host, connections) for host in SUPPORTED_HOSTS]
    candidates = [item["host"] for item in hosts if item["configured"]]
    if not candidates:
        candidates = [item["host"] for item in hosts if item["installed"]]
    return _envelope(
        "agent.detect",
        ok=True,
        hosts=hosts,
        auto_candidates=candidates,
        auto_selected=candidates[0] if len(candidates) == 1 else None,
        selection_required=len(candidates) != 1,
        generic_mcp_available=True,
        message=(
            "检测到唯一宿主，可使用 --host auto。"
            if len(candidates) == 1
            else "请从 auto_candidates 中明确选择宿主；不会猜测要修改哪个 Agent。"
        ),
    )


def _resolve_host(requested: str) -> str:
    if requested != "auto":
        return requested
    detected = detect_payload()
    selected = detected.get("auto_selected")
    if isinstance(selected, str):
        return selected
    candidates = detected.get("auto_candidates", [])
    if not candidates:
        raise AgentManagedError(
            "host_not_found",
            "没有检测到受支持的 Agent CLI；仍可手动把 mommy-mcp 注册到任意 MCP host。",
        )
    raise AgentManagedError(
        "host_ambiguous",
        "检测到多个 Agent，必须明确指定 --host。",
        details={"candidates": candidates},
    )


def _configuration_target(host: str) -> str:
    if host == "claude":
        override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        return str((Path(override).expanduser() if override else Path.home()) / ".claude.json")
    if host == "kimi":
        return str(agent_home("kimi") / "mcp.json")
    if host == "cline":
        return str(agent_home("cline") / "cline_mcp_settings.json")
    return "Codex user MCP registry (managed by `codex mcp add/remove`)"


def plan_payload(host: str, profile: str) -> dict[str, Any]:
    selected = _resolve_host(host)
    spec = _connection_spec(profile)
    skills = [
        {
            "name": source.name,
            "source": str(source),
            "destination": str(skill_dir(selected, source.name)),
        }
        for source in _bundled_skill_dirs()
    ]
    return _envelope(
        "agent.plan",
        ok=True,
        host=selected,
        profile=spec.profile,
        requires_user_confirmation=True,
        changes={
            "configuration_target": _configuration_target(selected),
            "connection_state_target": str(_state_path()),
            "mcp_server": {
                "name": "mommy-chaogu",
                "command": spec.command,
                "args": spec.args,
                "cwd": spec.cwd,
                "environment_keys": sorted(spec.env),
            },
            "skills": skills,
        },
        privacy={
            "personal_data_available": spec.profile == "personal",
            "strategy_cards_available": spec.profile == "personal",
            "description": (
                "只开放公共市场数据；不会读取持仓、记忆或本地策略卡。"
                if spec.profile == "market-only"
                else "可按任务读取本机持仓、记忆和策略卡；写入仍需对应的明确确认。"
            ),
            "external_agent_is_only_reasoner": True,
            "internal_llm_key_required": False,
        },
        next_command=f"mommy agent connect --host {selected} --profile {spec.profile} --json",
    )


def _skill_checks(host: str, previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    recorded = managed_skill_records(host, previous)
    bundled = {source.name: source for source in _bundled_skill_dirs()}
    checks: list[dict[str, Any]] = []
    for name, source in bundled.items():
        installed_path, recorded_hash = recorded.get(name, (skill_dir(host, name), ""))
        installed_hash = directory_hash(installed_path)
        bundled_hash = directory_hash(source)
        if not installed_path.is_dir():
            status = "missing"
        elif recorded_hash and installed_hash != recorded_hash:
            status = "modified"
        elif installed_hash != bundled_hash:
            status = "update_available"
        else:
            status = "ok"
        checks.append(
            {
                "name": name,
                "status": status,
                "path": str(installed_path),
                "managed": bool(recorded_hash),
            }
        )
    return checks


def doctor_payload(host: str, timeout_seconds: float) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise AgentManagedError("invalid_timeout", "--timeout 必须大于 0")
    selected = _resolve_host(host)
    connections = _state_connections()
    item = connections.get(selected)
    previous = item if isinstance(item, dict) else None
    status = _host_status(selected, connections)
    checks: list[dict[str, Any]] = [
        {
            "name": "managed_connection",
            "status": "ok" if previous is not None else "failed",
            "message": "已找到 mommy 管理的连接状态" if previous else "尚未建立托管连接",
        },
        {
            "name": "host_configuration",
            "status": "ok" if status["configured"] else "failed",
            "message": str(status.get("state", "配置状态未知")),
        },
    ]
    skill_checks = _skill_checks(selected, previous)
    checks.append(
        {
            "name": "skill_integrity",
            "status": "ok" if all(item["status"] == "ok" for item in skill_checks) else "failed",
            "skills": skill_checks,
        }
    )

    tool_names: list[str] = []
    spec = previous_spec(previous)
    if spec is None or not status["configured"]:
        checks.extend(
            [
                {
                    "name": "mcp_initialize_and_list_tools",
                    "status": "not_checked",
                    "message": "没有可验证的已配置 MCP 连接。",
                },
                {
                    "name": "privacy_boundary",
                    "status": "not_checked",
                    "message": "只有真实列出工具后才能验证权限边界。",
                },
            ]
        )
    else:
        try:
            tool_names = _probe_sync(spec, timeout_seconds=timeout_seconds)
            missing = sorted(_PUBLIC_REQUIRED_TOOLS - set(tool_names))
            if spec.profile == "personal":
                missing.extend(sorted(_PERSONAL_REQUIRED_TOOLS - set(tool_names)))
            checks.append(
                {
                    "name": "mcp_initialize_and_list_tools",
                    "status": "ok" if not missing else "failed",
                    "message": "已真实完成 MCP initialize 与 tools/list。",
                    "tool_count": len(tool_names),
                    "missing_required_tools": missing,
                }
            )
            leaked = (
                sorted(set(tool_names) - _MARKET_ONLY_ALLOWED_TOOLS)
                if spec.profile == "market-only"
                else []
            )
            checks.append(
                {
                    "name": "privacy_boundary",
                    "status": "ok" if not leaked else "failed",
                    "profile": spec.profile,
                    "unexpected_private_tools": leaked,
                }
            )
        except ConnectError as exc:
            checks.extend(
                [
                    {
                        "name": "mcp_initialize_and_list_tools",
                        "status": "failed",
                        "message": str(exc),
                    },
                    {
                        "name": "privacy_boundary",
                        "status": "not_checked",
                        "message": "MCP 探针失败，不能推断权限边界正常。",
                    },
                ]
            )

    checks.append(
        {
            "name": "live_market_data",
            "status": "not_checked",
            "message": (
                "doctor 不用固定标的伪装用户价值。请先询问用户想研究的股票或观点，"
                "再调用对应 research_* 工具并解释结果。"
            ),
        }
    )
    blocking = [item["name"] for item in checks if item["status"] == "failed"]
    return _envelope(
        "doctor",
        ok=not blocking,
        host=selected,
        profile=spec.profile if spec else None,
        timeout_seconds=timeout_seconds,
        checks=checks,
        blocking_checks=blocking,
        discovered_tools=tool_names,
        onboarding_complete=False,
        onboarding_completion_rule=(
            "连接和 doctor 不是完成事件；宿主 Agent 必须询问用户的真实目标，调用相关 "
            "research_*，解释证据与缺口，并让用户确认结果有用。"
        ),
        next_actions=(
            [f"运行 `mommy agent repair --host {selected} --json` 查看安全修复建议。"]
            if blocking
            else [
                "询问用户：第一次想研究哪只股票、哪个市场问题或哪段投资观点？",
                "调用与目标匹配的 research_stock / research_market_brief / research_us_market。",
                "用自然语言解释事实、推断、时间戳和数据缺口；不要只展示工具 JSON。",
            ]
        ),
    )


def connect_payload(host: str, profile: str, timeout_seconds: float) -> dict[str, Any]:
    selected = _resolve_host(host)
    # JSON mode must remain one object on stdout. Capture the established human connector output.
    human_output = io.StringIO()
    with contextlib.redirect_stdout(human_output):
        _connect(selected, profile, force=False, skip_test=True)
    diagnosed = doctor_payload(selected, timeout_seconds)
    return _envelope(
        "agent.connect",
        ok=bool(diagnosed["ok"]),
        host=selected,
        profile=profile,
        configuration_written=True,
        connected=bool(diagnosed["ok"]),
        doctor=diagnosed,
        restart_required=True,
        message=(
            "连接与真实 MCP 探针已完成；重启宿主 Agent 后，继续第一次用户指定的研究。"
            if diagnosed["ok"]
            else "配置已写入，但真实 MCP 探针未通过；请按 doctor 结果修复，不能宣称连接成功。"
        ),
    )


def repair_payload(host: str, timeout_seconds: float, *, apply: bool) -> dict[str, Any]:
    selected = _resolve_host(host)
    diagnosed = doctor_payload(selected, timeout_seconds)
    if diagnosed["ok"]:
        return _envelope(
            "agent.repair",
            ok=True,
            host=selected,
            applied=False,
            fixes=[],
            message="没有需要修复的阻塞项。",
        )

    connections = _state_connections()
    previous = connections.get(selected)
    if not isinstance(previous, dict):
        return _envelope(
            "agent.repair",
            ok=False,
            host=selected,
            applied=False,
            fixes=[
                {
                    "id": "connect",
                    "safe_to_apply": False,
                    "message": "尚未连接。先运行 agent plan 并让用户确认修改范围。",
                }
            ],
            next_command=f"mommy agent plan --host {selected} --profile market-only --json",
        )

    skill_checks = _skill_checks(selected, previous)
    modified = [item for item in skill_checks if item["status"] == "modified"]
    host_state = _host_status(selected, connections)
    if modified or host_state.get("state") == "配置已修改":
        return _envelope(
            "agent.repair",
            ok=False,
            host=selected,
            applied=False,
            fixes=[
                {
                    "id": "preserve-user-changes",
                    "safe_to_apply": False,
                    "message": (
                        "检测到用户修改过的 MCP 配置或 Skill；自动修复会覆盖内容，已停止。"
                    ),
                    "modified_skills": [item["name"] for item in modified],
                }
            ],
        )

    fix = {
        "id": "restore-managed-connection",
        "safe_to_apply": True,
        "message": "重新写入同一 privacy profile 的托管配置，并安装当前内置 Skills。",
    }
    if not apply:
        return _envelope(
            "agent.repair",
            ok=False,
            host=selected,
            applied=False,
            fixes=[fix],
            next_command=f"mommy agent repair --host {selected} --apply --json",
        )

    spec = previous_spec(previous)
    profile = spec.profile if spec else str(previous.get("profile", "market-only"))
    human_output = io.StringIO()
    with contextlib.redirect_stdout(human_output):
        _connect(selected, profile, force=False, skip_test=True)
    after = doctor_payload(selected, timeout_seconds)
    return _envelope(
        "agent.repair",
        ok=bool(after["ok"]),
        host=selected,
        applied=True,
        applied_fix=fix,
        doctor=after,
    )


def _parser() -> argparse.ArgumentParser:
    parser = _MachineParser(prog="mommy agent", description="Agent-managed JSON lifecycle")
    commands = parser.add_subparsers(dest="managed_action", required=True)
    detect = commands.add_parser("detect", help="检测可连接的宿主 Agent")
    detect.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    for name in ("plan", "connect", "doctor", "status", "repair"):
        command = commands.add_parser(name)
        command.add_argument("--host", choices=("auto", *SUPPORTED_HOSTS), default="auto")
        command.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
        if name in {"connect", "doctor", "status", "repair"}:
            command.add_argument("--timeout", type=float, default=20.0)
        if name in {"plan", "connect"}:
            command.add_argument(
                "--profile", choices=("market-only", "personal"), default="market-only"
            )
        if name == "repair":
            command.add_argument("--apply", action="store_true")
    return parser


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    action = str(args.managed_action)
    if action == "detect":
        return detect_payload(), 0
    if action == "plan":
        return plan_payload(args.host, args.profile), 0
    if action == "connect":
        payload = connect_payload(args.host, args.profile, args.timeout)
        return payload, 0 if payload["ok"] else 1
    if action in {"doctor", "status"}:
        payload = doctor_payload(args.host, args.timeout)
        if action == "status":
            payload["command"] = "agent.status"
        return payload, 0 if payload["ok"] else 1
    if action == "repair":
        payload = repair_payload(args.host, args.timeout, apply=bool(args.apply))
        return payload, 0 if payload["ok"] else 1
    raise AgentManagedError("unknown_action", f"未知操作: {action}")


def run_agent_managed(argv: list[str]) -> tuple[dict[str, Any], int]:
    try:
        args = _parser().parse_args(argv)
        return _run(args)
    except AgentManagedError as exc:
        return (
            _envelope(
                "agent.lifecycle",
                ok=False,
                error={"code": exc.code, "message": str(exc), "details": exc.details},
            ),
            2,
        )
    except (ConnectError, OSError, RuntimeError, ValueError) as exc:
        return (
            _envelope(
                "agent.lifecycle",
                ok=False,
                error={"code": "operation_failed", "message": str(exc)},
            ),
            2,
        )


def main_agent_managed(argv: list[str] | None = None) -> NoReturn:
    import sys

    payload, exit_code = run_agent_managed(list(sys.argv[1:] if argv is None else argv))
    _emit(payload, exit_code)


def main_doctor() -> NoReturn:
    try:
        parser = _MachineParser(prog="mommy doctor", description="真实检查 Agent/MCP 连接")
        parser.add_argument("--host", choices=("auto", *SUPPORTED_HOSTS), default="auto")
        parser.add_argument("--timeout", type=float, default=20.0)
        parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
        args = parser.parse_args()
        payload = doctor_payload(args.host, args.timeout)
        _emit(payload, 0 if payload["ok"] else 1)
    except AgentManagedError as exc:
        _emit(
            _envelope(
                "doctor",
                ok=False,
                error={"code": exc.code, "message": str(exc), "details": exc.details},
            ),
            2,
        )
    except (ConnectError, OSError, RuntimeError, ValueError) as exc:
        _emit(
            _envelope(
                "doctor",
                ok=False,
                error={"code": "operation_failed", "message": str(exc)},
            ),
            2,
        )


__all__ = [
    "SUPPORTED_HOSTS",
    "connect_payload",
    "detect_payload",
    "doctor_payload",
    "main_agent_managed",
    "main_doctor",
    "plan_payload",
    "repair_payload",
    "run_agent_managed",
]
