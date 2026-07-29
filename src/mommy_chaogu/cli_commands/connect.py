"""One-command integration with external coding agents."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, NoReturn

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mommy_chaogu.agent.research_tools import McpProfile, normalize_mcp_profile
from mommy_chaogu.config import default_user_config_dir
from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB

SERVER_NAME = "mommy-chaogu"
STATE_VERSION = 1


@dataclass(frozen=True)
class ConnectionSpec:
    """Portable stdio MCP process declaration persisted by the connector."""

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
        return cls(
            command=str(value["command"]),
            args=[str(item) for item in value.get("args", [])],
            env={str(key): str(item) for key, item in value.get("env", {}).items()},
            cwd=str(value.get("cwd", "")),
            profile=normalize_mcp_profile(str(value.get("profile", "market-only"))),
        )


class ConnectError(RuntimeError):
    """User-facing connector error."""


def build_connect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mommy-connect",
        description="把本地投研能力连接到 Claude Code 或 Kimi Code",
    )
    action = parser.add_subparsers(dest="action", required=True)
    for target in ("claude", "kimi"):
        connect = action.add_parser(target, help=f"连接 {target.title()} Code")
        connect.add_argument(
            "--profile",
            choices=("market-only", "personal"),
            default="market-only",
            help="market-only 默认不开放持仓和记忆；personal 明确开放个人数据",
        )
        connect.add_argument("--force", action="store_true", help="替换同名的非托管配置或 Skill")
        connect.add_argument("--skip-test", action="store_true", help="安装后跳过 MCP 连通测试")

    status = action.add_parser("status", help="查看连接状态")
    status.add_argument("target", nargs="?", choices=("claude", "kimi"))

    disconnect = action.add_parser("disconnect", help="断开连接并删除托管的 Skill")
    disconnect.add_argument("target", choices=("claude", "kimi", "all"))

    test = action.add_parser("test", help="启动 MCP 并检查可用工具")
    test.add_argument("target", choices=("claude", "kimi"))
    return parser


def _state_path() -> Path:
    return default_user_config_dir() / "connections.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"version": STATE_VERSION, "connections": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectError(f"连接状态文件损坏：{path}（{exc}）") from exc
    if not isinstance(value, dict) or not isinstance(value.get("connections", {}), dict):
        raise ConnectError(f"连接状态文件格式无效：{path}")
    value.setdefault("version", STATE_VERSION)
    value.setdefault("connections", {})
    return value


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)
    path.chmod(0o600)


def _bundled_skill_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "bundled_skills" / "mommy-research"


def _agent_home(target: str) -> Path:
    if target == "claude":
        override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        return Path(override).expanduser() if override else Path.home() / ".claude"
    override = os.environ.get("KIMI_CODE_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".kimi-code"


def _skill_dir(target: str) -> Path:
    return _agent_home(target) / "skills" / "mommy-research"


def _directory_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.is_dir():
        return ""
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _install_skill(
    target: str, previous: dict[str, Any] | None, *, force: bool
) -> tuple[Path, str]:
    source = _bundled_skill_dir()
    if not (source / "SKILL.md").is_file():
        raise ConnectError(f"安装包缺少 mommy-research Skill：{source}")
    destination = _skill_dir(target)
    bundled_hash = _directory_hash(source)
    current_hash = _directory_hash(destination)
    previous_hash = str((previous or {}).get("skill_hash", ""))
    if current_hash and current_hash not in {bundled_hash, previous_hash} and not force:
        raise ConnectError(
            f"检测到用户修改过的 Skill：{destination}。为避免覆盖，请先备份或加 --force。"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    installed_hash = _directory_hash(destination)
    return destination, installed_hash


def _connection_spec(profile: str) -> ConnectionSpec:
    selected = normalize_mcp_profile(profile)
    mcp_entry = shutil.which("mommy-mcp")
    if mcp_entry:
        command = str(Path(mcp_entry).resolve())
        args = ["--profile", selected]
    else:
        # Keep the virtualenv path. Resolving its Python symlink to the base
        # interpreter would drop the environment's site-packages.
        command = sys.executable
        args = ["-m", "mommy_chaogu.agent.mcp_server", "--profile", selected]
    cwd = str(Path.cwd().resolve())
    env = {
        "MOMMY_CONFIG_DIR": str(default_user_config_dir().resolve()),
        "MOMMY_MARKET_DB": str(MARKET_DB.resolve()),
        "MOMMY_PORTFOLIO_DB": str(PORTFOLIO_DB.resolve()),
        "MOMMY_AGENT_DB": str(AGENT_DB.resolve()),
        "MOMMY_REFERENCE_DB": str(REFERENCE_DB.resolve()),
    }
    return ConnectionSpec(
        command=command,
        args=args,
        env=env,
        cwd=cwd,
        profile=selected,
    )


def _run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, check=check)
    except FileNotFoundError as exc:
        raise ConnectError(f"没有找到 {command[0]}，请先安装并登录对应的 Coding Agent。") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ConnectError(detail) from exc


def _claude_exists(binary: str) -> bool:
    result = _run_command([binary, "mcp", "get", SERVER_NAME], check=False)
    return result.returncode == 0


def _claude_config_path() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


def _current_mcp_entry(target: str) -> dict[str, Any] | None:
    if target == "kimi":
        entry = _load_kimi_config()["mcpServers"].get(SERVER_NAME)
        return entry if isinstance(entry, dict) else None
    path = _claude_config_path()
    if not path.is_file():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectError(f"Claude Code 配置损坏：{path}（{exc}）") from exc
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
        raise ConnectError(f"Claude Code 配置的 mcpServers 格式无效：{path}")
    entry = config["mcpServers"].get(SERVER_NAME)
    return entry if isinstance(entry, dict) else None


def _entry_matches_spec(target: str, entry: dict[str, Any], spec: ConnectionSpec) -> bool:
    if entry.get("command") != spec.command or entry.get("args", []) != spec.args:
        return False
    if entry.get("env", {}) != spec.env:
        return False
    return target != "kimi" or entry.get("cwd") == spec.cwd


def _preflight(target: str, previous: dict[str, Any] | None, *, force: bool) -> None:
    binary = shutil.which(target)
    if binary is None:
        raise ConnectError(f"没有找到 {target}，请先安装并登录 {target.title()} Code。")
    if target == "claude":
        exists = _claude_exists(binary)
    else:
        exists = SERVER_NAME in _load_kimi_config()["mcpServers"]
    if exists and previous is None and not force:
        raise ConnectError(
            f"{target.title()} Code 中已存在非本工具管理的 {SERVER_NAME}；如需替换请加 --force。"
        )
    if exists and previous is not None and not force:
        raw_spec = previous.get("spec")
        current = _current_mcp_entry(target)
        if not isinstance(raw_spec, dict) or current is None:
            raise ConnectError(f"无法确认现有 {target} 配置仍由 mommy connect 管理；请加 --force。")
        if not _entry_matches_spec(target, current, ConnectionSpec.from_dict(raw_spec)):
            raise ConnectError(f"检测到 {target} MCP 配置已被修改；为避免覆盖请加 --force。")


def _claude_add_command(binary: str, spec: ConnectionSpec) -> list[str]:
    command = [binary, "mcp", "add", "--scope", "user", SERVER_NAME]
    for key, value in spec.env.items():
        command.extend(["--env", f"{key}={value}"])
    command.extend(["--", spec.command, *spec.args])
    return command


def _register_claude(
    spec: ConnectionSpec,
    previous: dict[str, Any] | None,
    *,
    force: bool,
) -> None:
    binary = shutil.which("claude")
    if binary is None:
        raise ConnectError("没有找到 claude，请先安装并登录 Claude Code。")
    exists = _claude_exists(binary)
    if exists and previous is None and not force:
        raise ConnectError(f"Claude Code 中已存在非托管的 {SERVER_NAME}")
    old_spec = None
    if previous and isinstance(previous.get("spec"), dict):
        old_spec = ConnectionSpec.from_dict(previous["spec"])
    if exists:
        _run_command([binary, "mcp", "remove", "--scope", "user", SERVER_NAME])
    try:
        _run_command(_claude_add_command(binary, spec))
    except ConnectError:
        if old_spec is not None:
            _run_command(_claude_add_command(binary, old_spec), check=False)
        raise


def _kimi_config_path() -> Path:
    return _agent_home("kimi") / "mcp.json"


def _load_kimi_config() -> dict[str, Any]:
    path = _kimi_config_path()
    if not path.is_file():
        return {"mcpServers": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectError(f"Kimi MCP 配置损坏：{path}（{exc}）") from exc
    if not isinstance(value, dict):
        raise ConnectError(f"Kimi MCP 配置格式无效：{path}")
    servers = value.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConnectError(f"Kimi MCP 配置的 mcpServers 必须是对象：{path}")
    return value


def _save_kimi_config(config: dict[str, Any]) -> None:
    path = _kimi_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)
    path.chmod(0o600)


def _register_kimi(
    spec: ConnectionSpec,
    previous: dict[str, Any] | None,
    *,
    force: bool,
) -> None:
    if shutil.which("kimi") is None:
        raise ConnectError("没有找到 kimi，请先安装并登录 Kimi Code。")
    config = _load_kimi_config()
    servers: dict[str, Any] = config["mcpServers"]
    if SERVER_NAME in servers and previous is None and not force:
        raise ConnectError(f"Kimi Code 中已存在非托管的 {SERVER_NAME}")
    servers[SERVER_NAME] = {
        "command": spec.command,
        "args": spec.args,
        "env": spec.env,
        "cwd": spec.cwd,
        "enabled": True,
        "startupTimeoutMs": 30000,
        "toolTimeoutMs": 60000,
    }
    _save_kimi_config(config)


async def _probe(spec: ConnectionSpec) -> list[str]:
    process_env = dict(os.environ)
    process_env.update(spec.env)
    params = StdioServerParameters(
        command=spec.command,
        args=spec.args,
        env=process_env,
        cwd=spec.cwd,
    )
    async with asyncio.timeout(20):
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=15),
            ) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]


def _probe_sync(spec: ConnectionSpec) -> list[str]:
    try:
        return asyncio.run(_probe(spec))
    except Exception as exc:
        raise ConnectError(f"MCP 连通测试失败：{exc}") from exc


def _connect(target: str, profile: str, *, force: bool, skip_test: bool) -> int:
    state = _load_state()
    connections: dict[str, Any] = state["connections"]
    previous = connections.get(target)
    if previous is not None and not isinstance(previous, dict):
        raise ConnectError(f"{target} 的连接状态格式损坏")

    _preflight(target, previous, force=force)
    spec = _connection_spec(profile)
    skill_path, skill_hash = _install_skill(target, previous, force=force)
    if target == "claude":
        _register_claude(spec, previous, force=force)
    else:
        _register_kimi(spec, previous, force=force)

    connections[target] = {
        "profile": spec.profile,
        "spec": spec.as_dict(),
        "skill_path": str(skill_path),
        "skill_hash": skill_hash,
    }
    _save_state(state)

    print(f"✅ 已连接 {target.title()} Code（profile: {spec.profile}）")
    print(f"   投研 Skill：{skill_path}")
    if skip_test:
        print("   已跳过连通测试；稍后可运行 `mommy connect test " + target + "`。")
    else:
        names = _probe_sync(spec)
        print(f"   MCP 连通正常：已发现 {len(names)} 个工具。")
    if spec.profile == "market-only":
        print("   默认未开放持仓、自选和历史记忆。")
    else:
        print("   ⚠ personal 模式：被调用的个人数据会进入当前模型上下文。")
    print(f"   重新启动 {target.title()} Code 后即可使用。")
    return 0


def _status(target: str | None) -> int:
    state = _load_state()
    connections: dict[str, Any] = state["connections"]
    targets = [target] if target else ["claude", "kimi"]
    for name in targets:
        item = connections.get(name)
        if not isinstance(item, dict):
            print(f"{name}: 未连接")
            continue
        current = _current_mcp_entry(name)
        raw_spec = item.get("spec")
        configured = (
            current is not None
            and isinstance(raw_spec, dict)
            and _entry_matches_spec(name, current, ConnectionSpec.from_dict(raw_spec))
        )
        skill_ok = _directory_hash(Path(str(item.get("skill_path", "")))) == str(
            item.get("skill_hash", "")
        )
        state_text = "已连接" if configured else ("配置已修改" if current else "配置缺失")
        skill_text = "正常" if skill_ok else "缺失或已修改"
        print(f"{name}: {state_text} · profile={item.get('profile')} · Skill={skill_text}")
    return 0


def _disconnect_one(target: str, state: dict[str, Any]) -> None:
    connections: dict[str, Any] = state["connections"]
    item = connections.get(target)
    if not isinstance(item, dict):
        print(f"{target}: 没有由 mommy connect 管理的连接，未修改外部配置。")
        return

    if target == "claude":
        binary = shutil.which("claude")
        current = _current_mcp_entry("claude")
        raw_spec = item.get("spec")
        matches = (
            isinstance(raw_spec, dict)
            and current is not None
            and _entry_matches_spec("claude", current, ConnectionSpec.from_dict(raw_spec))
        )
        if binary and matches:
            _run_command([binary, "mcp", "remove", "--scope", "user", SERVER_NAME])
        elif current is not None:
            print("⚠ 保留已被修改的 Claude MCP 配置。")
    else:
        config = _load_kimi_config()
        servers: dict[str, Any] = config["mcpServers"]
        current = servers.get(SERVER_NAME)
        raw_spec = item.get("spec")
        matches = (
            isinstance(current, dict)
            and isinstance(raw_spec, dict)
            and _entry_matches_spec("kimi", current, ConnectionSpec.from_dict(raw_spec))
        )
        if matches:
            del servers[SERVER_NAME]
            _save_kimi_config(config)
        elif current is not None:
            print("⚠ 保留已被修改的 Kimi MCP 配置。")

    skill = Path(str(item.get("skill_path", "")))
    expected_hash = str(item.get("skill_hash", ""))
    if skill.is_dir() and _directory_hash(skill) == expected_hash:
        shutil.rmtree(skill)
    elif skill.exists():
        print(f"⚠ 保留已被修改的 Skill：{skill}")
    connections.pop(target, None)
    print(f"✅ 已断开 {target.title()} Code。")


def _disconnect(target: str) -> int:
    state = _load_state()
    targets = ["claude", "kimi"] if target == "all" else [target]
    for name in targets:
        _disconnect_one(name, state)
    _save_state(state)
    return 0


def _test(target: str) -> int:
    state = _load_state()
    item = state["connections"].get(target)
    if not isinstance(item, dict) or not isinstance(item.get("spec"), dict):
        raise ConnectError(f"{target} 尚未连接")
    spec = ConnectionSpec.from_dict(item["spec"])
    names = _probe_sync(spec)
    print(f"✅ {target} MCP 正常：{len(names)} 个工具")
    print("   " + ", ".join(names))
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    try:
        if args.action in {"claude", "kimi"}:
            return _connect(
                args.action,
                args.profile,
                force=bool(args.force),
                skip_test=bool(args.skip_test),
            )
        if args.action == "status":
            return _status(args.target)
        if args.action == "disconnect":
            return _disconnect(args.target)
        if args.action == "test":
            return _test(args.target)
    except ConnectError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    return 2


def main_connect() -> NoReturn:
    parser = build_connect_parser()
    raise SystemExit(cmd_connect(parser.parse_args()))


__all__ = [
    "ConnectError",
    "ConnectionSpec",
    "build_connect_parser",
    "cmd_connect",
    "main_connect",
]
