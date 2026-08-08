"""Coding Agent adapters used by ``mommy connect``."""

from typing import Any, cast

from mommy_chaogu.coding_agents.base import (
    CodingAgentAdapter,
    ConnectionSpec,
    ConnectionStatus,
)
from mommy_chaogu.coding_agents.claude import ClaudeAdapter
from mommy_chaogu.coding_agents.cline import ClineAdapter
from mommy_chaogu.coding_agents.codex import CodexAdapter
from mommy_chaogu.coding_agents.kimi import KimiAdapter


def adapter_for(target: str, **kwargs: Any) -> CodingAgentAdapter:
    adapters: dict[str, Any] = {
        "claude": ClaudeAdapter,
        "kimi": KimiAdapter,
        "cline": ClineAdapter,
        "codex": CodexAdapter,
    }
    try:
        return cast(CodingAgentAdapter, adapters[target](target=target, **kwargs))
    except KeyError as exc:
        raise ValueError(f"未知 Coding Agent: {target}") from exc


__all__ = [
    "ClaudeAdapter",
    "ClineAdapter",
    "CodexAdapter",
    "CodingAgentAdapter",
    "ConnectionSpec",
    "ConnectionStatus",
    "KimiAdapter",
    "adapter_for",
]
