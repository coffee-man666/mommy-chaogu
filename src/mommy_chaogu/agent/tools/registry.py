"""工具注册表：聚合各域模块的工具定义与处理器，提供查找 + 调用。

新增工具时只需在对应域模块（quote / sector / flows / ...）的 DEFS 和
HANDLERS 中各加一项，无需改动本文件。

两个全局治理挂点：
- DEFS/HANDLERS 一致性在 import 时校验（名字手工对齐，靠注册表兜底）；
- ``call()`` 对工具结果统一截断（默认 8KB）——工具返回体是 agent
  context window 的最大单一来源（get_bars 120 根 K 线 ≈ 8-12k tokens），
  截断挂在这里对所有工具一次生效（EVALUATION-2026-07-18 T5/L2）。
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

# DEFS 与 HANDLERS 靠名字手工对齐——import 时校验，缺任何一边立即暴露，
# 而不是等 LLM 调到才发现（"未知工具"或定义缺失）。
_DEF_NAMES = {td.name for td in _TOOL_DEFINITIONS}
_HANDLER_NAMES = set(_HANDLERS)
if _DEF_NAMES != _HANDLER_NAMES:  # pragma: no cover - 配置错误时 import 即炸
    raise RuntimeError(
        "工具 DEFS/HANDLERS 不一致: "
        f"defs-only={sorted(_DEF_NAMES - _HANDLER_NAMES)}, "
        f"handlers-only={sorted(_HANDLER_NAMES - _DEF_NAMES)}"
    )

# 工具结果统一截断上限（字节）。8KB ≈ 2-4k tokens，足够单只股票的
# 报价/资金流，又能挡住 120 根 K 线 / 全量成分股这类洪水。
MAX_RESULT_BYTES = 8192


def _truncate_result(result: str, max_bytes: int = MAX_RESULT_BYTES) -> str:
    """按字节上限截断工具结果，附加截断标记（LLM 可见、可理解）。

    截断发生在 JSON 字符串层面——结果不再是合法 JSON，但截断标记
    明确告知 LLM 数据被裁过，比静默丢失尾部信息更诚实。
    """
    encoded = result.encode("utf-8")
    if len(encoded) <= max_bytes:
        return result
    cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
    omitted = len(encoded) - max_bytes
    _log.info("tool result truncated: %d bytes omitted", omitted)
    return f'{cut}... "[truncated, {omitted} bytes omitted]"'


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
            return _truncate_result(handler(self._ctx, args))
        except Exception as e:
            _log.exception("tool %s failed", name)
            return _json({"error": f"工具执行失败: {e}"})

    @staticmethod
    def tool_names() -> list[str]:
        return list(_HANDLERS.keys())
