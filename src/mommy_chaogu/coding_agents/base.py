"""Shared contracts and filesystem helpers for Coding Agent connectors."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mommy_chaogu.agent.research_tools import McpProfile, normalize_mcp_profile
from mommy_chaogu.config import default_user_config_dir
from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB

SERVER_NAME = "mommy-chaogu"
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ConnectionSpec:
    """Portable stdio MCP process declaration."""

    command: str
    args: list[str]
    env: dict[str, str]
    cwd: str
    profile: McpProfile

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "profile": self.profile,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ConnectionSpec:
        # A missing profile is an old connection.  Keep it least-privilege.
        return cls(
            command=str(value["command"]),
            args=[str(item) for item in value.get("args", [])],
            env={str(key): str(item) for key, item in value.get("env", {}).items()},
            cwd=str(value.get("cwd", "")),
            profile=normalize_mcp_profile(str(value.get("profile", "market-only"))),
        )


@dataclass(frozen=True)
class ConnectionStatus:
    """Machine-readable connector status used by all four adapters."""

    target: str
    state: str
    profile: McpProfile
    configured: bool
    skill_ok: bool
    managed: bool
    upgrade_hint: bool = False


class CodingAgentAdapter(Protocol):
    def register_mcp(self, spec: ConnectionSpec) -> None: ...

    def install_skill(self, source: Path) -> Path: ...

    def inspect_status(self) -> ConnectionStatus: ...

    def disconnect(self) -> None: ...


def connection_spec(
    profile: str,
    *,
    python: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> ConnectionSpec:
    """Build the same MCP spec for every Coding Agent."""
    selected = normalize_mcp_profile(profile)
    mcp_entry = which("mommy-mcp")
    if mcp_entry:
        command = str(Path(mcp_entry).resolve())
        args = ["--profile", selected]
    else:
        command = python or sys.executable
        args = ["-m", "mommy_chaogu.agent.mcp_server", "--profile", selected]
    return ConnectionSpec(
        command=command,
        args=args,
        env={
            "MOMMY_CONFIG_DIR": str(default_user_config_dir().resolve()),
            "MOMMY_MARKET_DB": str(MARKET_DB.resolve()),
            "MOMMY_PORTFOLIO_DB": str(PORTFOLIO_DB.resolve()),
            "MOMMY_AGENT_DB": str(AGENT_DB.resolve()),
            "MOMMY_REFERENCE_DB": str(REFERENCE_DB.resolve()),
        },
        cwd=str(Path.cwd().resolve()),
        profile=selected,
    )


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, check=check)
    except FileNotFoundError as exc:
        raise RuntimeError(f"没有找到 {command[0]}，请先安装并登录对应的 Coding Agent。") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(detail) from exc


def directory_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.is_dir():
        return ""
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def agent_home(target: str) -> Path:
    if target == "claude":
        override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        return Path(override).expanduser() if override else Path.home() / ".claude"
    if target == "cline":
        override = os.environ.get("CLINE_DATA_DIR", "").strip()
        base = Path(override).expanduser() if override else Path.home() / ".cline" / "data"
        return base / "settings"
    if target == "codex":
        override = os.environ.get("CODEX_HOME", "").strip()
        return Path(override).expanduser() if override else Path.home() / ".codex"
    override = os.environ.get("KIMI_CODE_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".kimi-code"


def skill_dir(target: str) -> Path:
    if target == "codex":
        override = os.environ.get("CODEX_SKILLS_DIR", "").strip()
        base = Path(override).expanduser() if override else Path.home() / ".agents" / "skills"
        return base / "mommy-research"
    return agent_home(target) / "skills" / "mommy-research"


def install_skill(
    target: str, source: Path, previous: dict[str, Any] | None, *, force: bool
) -> Path:
    destination = skill_dir(target)
    bundled_hash = directory_hash(source)
    current_hash = directory_hash(destination)
    previous_hash = str((previous or {}).get("skill_hash", ""))
    if current_hash and current_hash not in {bundled_hash, previous_hash} and not force:
        raise RuntimeError(
            f"检测到用户修改过的 Skill：{destination}。为避免覆盖，请先备份或加 --force。"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return destination


def transport_of(entry: dict[str, Any]) -> dict[str, Any]:
    transport = entry.get("transport")
    return transport if isinstance(transport, dict) else entry


def entry_matches_spec(target: str, entry: dict[str, Any], spec: ConnectionSpec) -> bool:
    transport = transport_of(entry)
    if transport.get("command") != spec.command or transport.get("args", []) != spec.args:
        return False
    if transport.get("env", {}) != spec.env:
        return False
    return target != "kimi" or entry.get("cwd") == spec.cwd


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default.copy()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"配置格式无效：{path}")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)
    path.chmod(0o600)


def previous_spec(previous: dict[str, Any] | None) -> ConnectionSpec | None:
    raw = (previous or {}).get("spec")
    return ConnectionSpec.from_dict(raw) if isinstance(raw, dict) else None


__all__ = [
    "SERVER_NAME",
    "CodingAgentAdapter",
    "ConnectionSpec",
    "ConnectionStatus",
    "agent_home",
    "connection_spec",
    "directory_hash",
    "entry_matches_spec",
    "install_skill",
    "previous_spec",
    "run_command",
    "skill_dir",
]
