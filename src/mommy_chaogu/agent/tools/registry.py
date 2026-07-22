"""工具注册表：聚合各域模块的工具定义与处理器，提供查找 + 调用。

新增工具时只需在对应域模块（quote / sector / flows / ...）的 DEFS 和
HANDLERS 中各加一项，无需改动本文件。
"""

from __future__ import annotations

import logging
from typing import Any

from mommy_chaogu.agent.tools import (
    alerts,
    bars,
    flows,
    holdings,
    intel,
    memory,
    quote,
    sector,
    themes,
)
from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json

_log = logging.getLogger(__name__)

# 域模块聚合顺序即 definitions() 的输出顺序
_MODULES = (quote, sector, flows, bars, holdings, intel, alerts, memory, themes)

_TOOL_DEFINITIONS: list[ToolDef] = [td for m in _MODULES for td in m.DEFS]

_HANDLERS: dict[str, ToolHandler] = {name: h for m in _MODULES for name, h in m.HANDLERS.items()}

_TOOL_MAP: dict[str, ToolDef] = {td.name: td for td in _TOOL_DEFINITIONS}


class ToolRegistry:
    """工具注册表：查找工具定义 + 执行工具调用。"""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    def definitions(self) -> list[dict[str, Any]]:
        """返回 OpenAI function-calling 格式的 tool definitions。"""
        return [td.to_openai_dict() for td in _TOOL_DEFINITIONS]

    def call(self, name: str, args: dict[str, Any]) -> str:
        """执行工具调用，返回 JSON 字符串结果。

        工具不存在或执行抛异常时不抛出，返回 ``{"error": ...}`` JSON——
        调用方（WorkflowExecutor / AgentService）需检查 payload 判断成败。
        """
        handler = _HANDLERS.get(name)
        if handler is None:
            return _json({"error": f"未知工具: {name}"})
        try:
            return handler(self._ctx, args)
        except Exception as e:
            _log.exception("tool %s failed", name)
            return _json({"error": f"工具执行失败: {e}"})

    @staticmethod
    def tool_names() -> list[str]:
        return list(_HANDLERS.keys())
