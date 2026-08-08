"""Codex CLI MCP/Skill adapter."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from mommy_chaogu.coding_agents.base import (
    SERVER_NAME,
    ConnectionSpec,
    ConnectionStatus,
    directory_hash,
    entry_matches_spec,
    install_skill,
    previous_spec,
    run_command,
    skill_dir,
)


class CodexAdapter:
    def __init__(
        self,
        target: str = "codex",
        *,
        previous: dict[str, Any] | None = None,
        force: bool = False,
        which: Any = shutil.which,
        command_runner: Any = run_command,
        entry_reader: Any = None,
        **_: object,
    ) -> None:
        self.target, self.previous, self.force = target, previous, force
        self._which, self._run, self._entry_reader = which, command_runner, entry_reader

    def _entry(self) -> dict[str, Any] | None:
        if self._entry_reader is not None:
            value = self._entry_reader()
            return value if isinstance(value, dict) else None
        binary = self._which("codex")
        if binary is None:
            return None
        result = self._run([binary, "mcp", "get", SERVER_NAME, "--json"], check=False)
        if result.returncode != 0:
            return None
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def register_mcp(self, spec: ConnectionSpec) -> None:
        binary = self._which("codex")
        if binary is None:
            raise RuntimeError("没有找到 codex，请先安装 Codex CLI。")
        current, old = self._entry(), previous_spec(self.previous)
        if current is not None and self.previous is None and not self.force:
            raise RuntimeError(f"Codex 中已存在非本工具管理的 {SERVER_NAME}")
        if (
            current is not None
            and old is not None
            and not self.force
            and not entry_matches_spec("codex", current, old)
        ):
            raise RuntimeError("检测到 Codex MCP 配置已被修改；为避免覆盖请加 --force。")
        if current is not None:
            self._run([binary, "mcp", "remove", SERVER_NAME])
        command = [binary, "mcp", "add", SERVER_NAME]
        for key, value in spec.env.items():
            command.extend(["--env", f"{key}={value}"])
        try:
            self._run([*command, "--", spec.command, *spec.args])
        except RuntimeError:
            if old is not None:
                restore = [binary, "mcp", "add", SERVER_NAME]
                for key, value in old.env.items():
                    restore.extend(["--env", f"{key}={value}"])
                self._run([*restore, "--", old.command, *old.args], check=False)
            raise

    def install_skill(self, source: Path) -> Path:
        return install_skill("codex", source, self.previous, force=self.force)

    def inspect_status(self) -> ConnectionStatus:
        old, current = previous_spec(self.previous), self._entry()
        configured = (
            old is not None and current is not None and entry_matches_spec("codex", current, old)
        )
        path = Path(str((self.previous or {}).get("skill_path", skill_dir("codex"))))
        skill_ok = bool(self.previous) and directory_hash(path) == str(
            (self.previous or {}).get("skill_hash", "")
        )
        profile = old.profile if old else "market-only"
        return ConnectionStatus(
            "codex",
            "已连接" if configured else ("配置已修改" if current else "配置缺失"),
            profile,
            configured,
            skill_ok,
            self.previous is not None,
            profile == "market-only",
        )

    def disconnect(self) -> None:
        current, old, binary = self._entry(), previous_spec(self.previous), self._which("codex")
        if (
            current is not None
            and old is not None
            and binary
            and entry_matches_spec("codex", current, old)
        ):
            self._run([binary, "mcp", "remove", SERVER_NAME])
        elif current is not None:
            print("⚠ 保留已被修改的 Codex MCP 配置。")
        path = Path(str((self.previous or {}).get("skill_path", skill_dir("codex"))))
        if path.is_dir() and directory_hash(path) == str(
            (self.previous or {}).get("skill_hash", "")
        ):
            shutil.rmtree(path)
