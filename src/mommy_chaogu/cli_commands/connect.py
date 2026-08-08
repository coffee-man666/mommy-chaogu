"""CLI orchestration for connecting external Coding Agents."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mommy_chaogu.agent.research_tools import (
    DEFAULT_MCP_PROFILE,
    normalize_mcp_profile,
)
from mommy_chaogu.coding_agents import adapter_for
from mommy_chaogu.coding_agents.base import (
    SERVER_NAME,
    ConnectionSpec,
    ConnectionStatus,
    connection_spec,
    directory_hash,
    previous_spec,
    skill_dir,
)
from mommy_chaogu.config import default_user_config_dir

STATE_VERSION = 1
PRIVACY_CONSENT_VERSION = "2026-08-07.personal-v1"


class ConnectError(RuntimeError):
    """User-facing connector error."""


def build_connect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mommy-connect",
        description="把本地投研能力连接到 Claude Code、Kimi Code、Cline 或 Codex",
    )
    action = parser.add_subparsers(dest="action", required=True)
    for target in ("claude", "kimi", "cline", "codex"):
        connect = action.add_parser(target, help=f"连接 {_display_name(target)}")
        connect.add_argument(
            "--profile",
            choices=("market-only", "personal"),
            default=None,
            help="隐私权限：personal（默认）或 market-only",
        )
        connect.add_argument("--force", action="store_true", help="替换同名的非托管配置或 Skill")
        connect.add_argument("--skip-test", action="store_true", help="安装后跳过 MCP 连通测试")
    status = action.add_parser("status", help="查看连接状态")
    status.add_argument("target", nargs="?", choices=("claude", "kimi", "cline", "codex"))
    disconnect = action.add_parser("disconnect", help="断开连接并删除托管的 Skill")
    disconnect.add_argument("target", choices=("claude", "kimi", "cline", "codex", "all"))
    test = action.add_parser("test", help="启动 MCP 并检查可用工具")
    test.add_argument("target", choices=("claude", "kimi", "cline", "codex"))
    return parser


def _display_name(target: str) -> str:
    return {"claude": "Claude Code", "kimi": "Kimi Code", "cline": "Cline", "codex": "Codex"}[
        target
    ]


def _state_path() -> Path:
    return default_user_config_dir() / "connections.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"version": STATE_VERSION, "connections": {}}
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConnectError(f"连接状态文件损坏：{path}（{exc}）") from exc
    if not isinstance(value, dict) or not isinstance(value.get("connections", {}), dict):
        raise ConnectError(f"连接状态文件格式无效：{path}")
    value.setdefault("version", STATE_VERSION)
    return value


def _save_state(state: dict[str, Any]) -> None:
    import json

    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)
    path.chmod(0o600)


def _bundled_skill_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "bundled_skills" / "mommy-research"


# Compatibility helpers retained for callers importing the old connector internals.
def _connection_spec(profile: str) -> ConnectionSpec:
    return connection_spec(profile, which=shutil.which)


def _skill_dir(target: str) -> Path:
    return skill_dir(target)


def _resolve_profile(profile: str | None, current_profile: str | None = None) -> str:
    """Resolve a profile without silently widening an existing connection.

    New connections still default to ``personal``.  Once a connection exists,
    omitting ``--profile`` preserves its current scope; changing a prior
    ``market-only`` choice therefore requires an explicit
    ``--profile personal``.
    """
    if profile:
        return normalize_mcp_profile(profile)
    if current_profile is not None:
        selected = normalize_mcp_profile(current_profile)
        if selected == "market-only" and sys.stdin.isatty():
            print("当前连接保持 market-only；如需个人记忆，请显式使用 --profile personal。")
        return selected
    if sys.stdin.isatty():
        print("选择投研数据范围：")
        print("  1) personal（默认）：开放与任务相关的持仓 / 自选 / 记忆")
        print("  2) market-only：只看公共行情，不读个人数据")
        try:
            choice = input("请输入 1 或 2 [1]: ").strip() or "1"
        except EOFError:
            choice = "1"
        return "personal" if choice == "1" else "market-only"
    return DEFAULT_MCP_PROFILE


async def _probe(spec: ConnectionSpec) -> list[str]:
    process_env = dict(os.environ)
    process_env.update(spec.env)
    params = StdioServerParameters(
        command=spec.command, args=spec.args, env=process_env, cwd=spec.cwd
    )
    async with asyncio.timeout(20):
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(
                read_stream, write_stream, read_timeout_seconds=_mcp_read_timeout()
            ) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]


def _mcp_read_timeout() -> Any:
    major = int(importlib.metadata.version("mcp").partition(".")[0])
    return 15.0 if major >= 2 else timedelta(seconds=15)


def _probe_sync(spec: ConnectionSpec) -> list[str]:
    try:
        return asyncio.run(_probe(spec))
    except Exception as exc:
        raise ConnectError(f"MCP 连通测试失败：{exc}") from exc


def _adapter(target: str, previous: dict[str, Any] | None, *, force: bool) -> Any:
    return adapter_for(target, previous=previous, force=force, which=shutil.which)


def _connect(target: str, profile: str | None, *, force: bool, skip_test: bool) -> int:
    state = _load_state()
    connections: dict[str, Any] = state["connections"]
    previous = connections.get(target)
    if previous is not None and not isinstance(previous, dict):
        raise ConnectError(f"{target} 的连接状态格式损坏")
    try:
        old_spec = previous_spec(previous)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectError(f"{target} 的连接状态格式损坏：{exc}") from exc
    selected = _resolve_profile(profile, old_spec.profile if old_spec is not None else None)
    spec = _connection_spec(selected)
    adapter = _adapter(target, previous, force=force)
    try:
        current_status: ConnectionStatus = adapter.inspect_status()
        if not force and previous is None and current_status.state != "配置缺失":
            raise ConnectError(
                f"{_display_name(target)} 中已存在非本工具管理的 {SERVER_NAME}；如需替换请加 --force。"
            )
        if not force and previous is not None and current_status.state == "配置已修改":
            raise ConnectError(f"检测到 {target} MCP 配置已被修改；为避免覆盖请加 --force。")
        skill_path = adapter.install_skill(_bundled_skill_dir())
        adapter.register_mcp(spec)
    except ConnectError:
        raise
    except (RuntimeError, OSError, ValueError) as exc:
        raise ConnectError(str(exc)) from exc

    item: dict[str, Any] = {
        "profile": spec.profile,
        "spec": spec.as_dict(),
        "skill_path": str(skill_path),
        "skill_hash": directory_hash(skill_path),
        "connected_at": datetime.now(UTC).isoformat(),
        "personal_capabilities": spec.profile == "personal",
    }
    if spec.profile == "personal":
        item["privacy_consent_version"] = PRIVACY_CONSENT_VERSION
    connections[target] = item
    _save_state(state)

    print(f"✅ 已连接 {_display_name(target)}（profile: {spec.profile}）")
    print(f"   投研 Skill：{skill_path}")
    if skip_test:
        print(f"   已跳过连通测试；稍后可运行 `mommy connect test {target}`。")
    else:
        names = _probe_sync(spec)
        print(f"   MCP 连通正常：已发现 {len(names)} 个工具。")
    if spec.profile == "market-only":
        print("   当前为 market-only：未开放持仓、自选和历史记忆；可用 --profile personal 重连。")
    else:
        print("   ⚠ personal 模式：被调用的个人数据会进入当前模型上下文。")
    print(f"   重新启动 {_display_name(target)} 后即可使用。")
    return 0


def _status(target: str | None) -> int:
    state = _load_state()
    targets = [target] if target else ["claude", "kimi", "cline", "codex"]
    for name in targets:
        item = state["connections"].get(name)
        if not isinstance(item, dict):
            print(f"{name}: 未连接")
            continue
        try:
            status: ConnectionStatus = _adapter(name, item, force=False).inspect_status()
        except (RuntimeError, OSError, ValueError) as exc:
            raise ConnectError(str(exc)) from exc
        profile = status.profile
        personal = "读取/写回开启" if profile == "personal" else "个人数据隔离"
        upgrade = " · 可用 --profile personal 重连" if status.upgrade_hint else ""
        skill = "正常" if status.skill_ok else "缺失或已修改"
        print(
            f"{name}: {status.state} · profile={profile} · 记忆/个人数据={personal}{upgrade} · Skill={skill}"
        )
    return 0


def _disconnect(target: str) -> int:
    state = _load_state()
    names = ["claude", "kimi", "cline", "codex"] if target == "all" else [target]
    for name in names:
        item = state["connections"].get(name)
        if not isinstance(item, dict):
            print(f"{name}: 没有由 mommy connect 管理的连接，未修改外部配置。")
            continue
        try:
            _adapter(name, item, force=False).disconnect()
        except (RuntimeError, OSError, ValueError) as exc:
            raise ConnectError(str(exc)) from exc
        state["connections"].pop(name, None)
        print(f"✅ 已断开 {_display_name(name)}。")
    _save_state(state)
    return 0


def _test(target: str) -> int:
    state = _load_state()
    item = state["connections"].get(target)
    if not isinstance(item, dict) or not isinstance(item.get("spec"), dict):
        raise ConnectError(f"{target} 尚未连接")
    spec = ConnectionSpec.from_dict(item["spec"])
    names = _probe_sync(spec)
    required = {
        "get_memory_context",
        "get_portfolio",
        "research_portfolio",
        "record_research_conclusion",
    }
    if spec.profile == "personal":
        missing = sorted(required - set(names))
        if missing:
            raise ConnectError(f"personal MCP 缺少必需工具：{', '.join(missing)}")
    print(f"✅ {target} MCP 正常：{len(names)} 个工具")
    print("   " + ", ".join(names))
    return 0


# Compatibility wrapper used by older callers and unit tests.
def _register_codex(spec: ConnectionSpec, previous: dict[str, Any] | None, *, force: bool) -> None:
    import shutil

    from mommy_chaogu.coding_agents.codex import CodexAdapter

    CodexAdapter(
        previous=previous,
        force=force,
        which=shutil.which,
        command_runner=_run_command,
        entry_reader=_codex_entry,
    ).register_mcp(spec)


def _codex_entry() -> dict[str, Any] | None:
    import json
    import shutil

    binary = shutil.which("codex")
    if binary is None:
        return None
    result = _run_command([binary, "mcp", "get", SERVER_NAME, "--json"], check=False)
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _run_command(command: list[str], *, check: bool = True) -> Any:
    import subprocess

    try:
        return subprocess.run(command, text=True, capture_output=True, check=check)
    except FileNotFoundError as exc:
        raise ConnectError(f"没有找到 {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ConnectError((exc.stderr or exc.stdout or str(exc)).strip()) from exc


def cmd_connect(args: argparse.Namespace) -> int:
    try:
        if args.action in {"claude", "kimi", "cline", "codex"}:
            return _connect(
                args.action, args.profile, force=bool(args.force), skip_test=bool(args.skip_test)
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
    raise SystemExit(cmd_connect(build_connect_parser().parse_args()))


__all__ = ["ConnectError", "ConnectionSpec", "build_connect_parser", "cmd_connect", "main_connect"]
