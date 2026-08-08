"""Cline MCP/Skill adapter."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from mommy_chaogu.coding_agents.base import (
    SERVER_NAME,
    ConnectionSpec,
    ConnectionStatus,
    agent_home,
    directory_hash,
    entry_matches_spec,
    install_skill,
    previous_spec,
    run_command,
    skill_dir,
)


class ClineAdapter:
    def __init__(
        self,
        target: str = "cline",
        *,
        previous: dict[str, Any] | None = None,
        force: bool = False,
        which: Any = shutil.which,
        command_runner: Any = run_command,
        **_: object,
    ) -> None:
        self.target, self.previous, self.force = target, previous, force
        self._which, self._run = which, command_runner

    @property
    def _path(self) -> Path:
        return agent_home("cline") / "cline_mcp_settings.json"

    def _load(self) -> dict[str, Any]:
        from mommy_chaogu.coding_agents.base import load_json

        value = load_json(self._path, {"mcpServers": {}})
        servers = value.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise RuntimeError(f"Cline MCP 配置的 mcpServers 必须是对象：{self._path}")
        return value

    def _entry(self) -> dict[str, Any] | None:
        value = self._load()["mcpServers"].get(SERVER_NAME)
        return value if isinstance(value, dict) else None

    def register_mcp(self, spec: ConnectionSpec) -> None:
        if self._which("cline") is None:
            raise RuntimeError("没有找到 cline，请先安装 Cline CLI。")
        config = self._load()
        current = self._entry()
        if current is not None and self.previous is None and not self.force:
            raise RuntimeError(f"Cline 中已存在非本工具管理的 {SERVER_NAME}")
        if current is not None and self.previous is not None and not self.force:
            old = previous_spec(self.previous)
            if old is None or not entry_matches_spec("cline", current, old):
                raise RuntimeError("检测到 Cline MCP 配置已被修改；为避免覆盖请加 --force。")
        config["mcpServers"][SERVER_NAME] = {
            "transport": {
                "type": "stdio",
                "command": spec.command,
                "args": spec.args,
                "env": spec.env,
            }
        }
        from mommy_chaogu.coding_agents.base import save_json

        save_json(self._path, config)

    def install_skill(self, source: Path) -> Path:
        return install_skill("cline", source, self.previous, force=self.force)

    def inspect_status(self) -> ConnectionStatus:
        old, current = previous_spec(self.previous), self._entry()
        configured = (
            old is not None and current is not None and entry_matches_spec("cline", current, old)
        )
        path = Path(str((self.previous or {}).get("skill_path", skill_dir("cline"))))
        skill_ok = bool(self.previous) and directory_hash(path) == str(
            (self.previous or {}).get("skill_hash", "")
        )
        profile = old.profile if old else "market-only"
        return ConnectionStatus(
            "cline",
            "已连接" if configured else ("配置已修改" if current else "配置缺失"),
            profile,
            configured,
            skill_ok,
            self.previous is not None,
            profile == "market-only",
        )

    def disconnect(self) -> None:
        config, current, old = self._load(), self._entry(), previous_spec(self.previous)
        if current is not None and old is not None and entry_matches_spec("cline", current, old):
            del config["mcpServers"][SERVER_NAME]
            from mommy_chaogu.coding_agents.base import save_json

            save_json(self._path, config)
        elif current is not None:
            print("⚠ 保留已被修改的 Cline MCP 配置。")
        path = Path(str((self.previous or {}).get("skill_path", skill_dir("cline"))))
        if path.is_dir() and directory_hash(path) == str(
            (self.previous or {}).get("skill_hash", "")
        ):
            shutil.rmtree(path)
