"""Shared contracts and filesystem helpers for Coding Agent connectors."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mommy_chaogu.agent.research_tools import McpProfile, normalize_mcp_profile
from mommy_chaogu.config import default_user_config_dir
from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB

SERVER_NAME = "mommy-chaogu"
BUNDLED_SKILL_NAMES = frozenset(
    {"mommy-onboard", "mommy-research", "mommy-strategy", "market-watch-loop"}
)
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
    """Build the same MCP spec for every Coding Agent.

    Bind the MCP process to the interpreter running the current ``mommy``
    command. A separately installed ``mommy-mcp`` may be an older release and
    must never be mixed with the current plan or bundled Skills.
    """
    selected = normalize_mcp_profile(profile)
    del which  # retained in the public signature for compatibility with existing callers
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


def skill_dir(target: str, skill_name: str = "mommy-research") -> Path:
    if not skill_name or Path(skill_name).name != skill_name:
        raise ValueError(f"无效 Skill 名称: {skill_name!r}")
    if target == "codex":
        override = os.environ.get("CODEX_SKILLS_DIR", "").strip()
        base = Path(override).expanduser() if override else Path.home() / ".agents" / "skills"
        return base / skill_name
    return agent_home(target) / "skills" / skill_name


def _previous_skill_record(
    target: str,
    previous: dict[str, Any] | None,
    skill_name: str,
) -> tuple[Path, str] | None:
    raw = (previous or {}).get("skills")
    if isinstance(raw, dict):
        item = raw.get(skill_name)
        if isinstance(item, dict) and item.get("path"):
            return Path(str(item["path"])), str(item.get("hash", ""))
    if skill_name == "mommy-research" and previous:
        return (
            Path(str(previous.get("skill_path", skill_dir(target, skill_name)))),
            str(previous.get("skill_hash", "")),
        )
    return None


def managed_skill_records(
    target: str, previous: dict[str, Any] | None
) -> dict[str, tuple[Path, str]]:
    """Return new multi-Skill state, with a v1 single-Skill fallback."""
    raw = (previous or {}).get("skills")
    records: dict[str, tuple[Path, str]] = {}
    if isinstance(raw, dict):
        for name, item in raw.items():
            if (
                isinstance(name, str)
                and Path(name).name == name
                and isinstance(item, dict)
                and item.get("path")
            ):
                records[name] = (Path(str(item["path"])), str(item.get("hash", "")))
    if not records and previous:
        legacy = _previous_skill_record(target, previous, "mommy-research")
        if legacy is not None:
            records["mommy-research"] = legacy
    return records


def managed_skills_ok(target: str, previous: dict[str, Any] | None) -> bool:
    records = managed_skill_records(target, previous)
    return BUNDLED_SKILL_NAMES.issubset(records) and all(
        directory_hash(path) == expected for path, expected in records.values()
    )


def remove_managed_skills(target: str, previous: dict[str, Any] | None) -> None:
    """Remove only unchanged Skill directories recorded in connector state."""
    for name, (path, expected_hash) in managed_skill_records(target, previous).items():
        expected_path = skill_dir(target, name)
        same_target = path.expanduser().resolve() == expected_path.expanduser().resolve()
        if (
            same_target
            and not path.is_symlink()
            and path.is_dir()
            and directory_hash(path) == expected_hash
        ):
            shutil.rmtree(path)
        elif path.exists():
            print(f"⚠ 保留已被修改的 Skill：{name}（{path}）。")


def install_skill(
    target: str, source: Path, previous: dict[str, Any] | None, *, force: bool
) -> Path:
    skill_name = source.name
    destination = skill_dir(target, skill_name)
    if destination.is_symlink():
        raise RuntimeError(f"Skill 目标是符号链接，为避免写入意外位置已停止：{destination}")
    bundled_hash = directory_hash(source)
    current_hash = directory_hash(destination)
    previous_record = _previous_skill_record(target, previous, skill_name)
    previous_hash = previous_record[1] if previous_record is not None else ""
    if current_hash and current_hash not in {bundled_hash, previous_hash} and not force:
        raise RuntimeError(
            f"检测到用户修改过的 Skill：{destination}。为避免覆盖，请先备份或加 --force。"
        )
    if current_hash == bundled_hash:
        return destination

    # Stage a complete tree before touching an existing managed copy. A plain
    # dirs_exist_ok copy leaves removed files behind, which can preserve stale
    # or contradictory Agent instructions after an upgrade.
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{skill_name}-staging-", dir=destination.parent))
    staged = staging_root / skill_name
    backup = destination.parent / f".{skill_name}-backup-{uuid.uuid4().hex}"
    had_destination = destination.is_dir()
    try:
        shutil.copytree(source, staged)
        if had_destination:
            destination.rename(backup)
        try:
            staged.rename(destination)
        except Exception:
            if had_destination and backup.is_dir() and not destination.exists():
                backup.rename(destination)
            raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    if backup.is_dir():
        try:
            shutil.rmtree(backup)
        except OSError:
            print(f"⚠ 新 Skill 已安装，但旧备份未能清理：{backup}")
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
    "BUNDLED_SKILL_NAMES",
    "SERVER_NAME",
    "CodingAgentAdapter",
    "ConnectionSpec",
    "ConnectionStatus",
    "agent_home",
    "connection_spec",
    "directory_hash",
    "entry_matches_spec",
    "install_skill",
    "managed_skill_records",
    "managed_skills_ok",
    "previous_spec",
    "remove_managed_skills",
    "run_command",
    "skill_dir",
]
