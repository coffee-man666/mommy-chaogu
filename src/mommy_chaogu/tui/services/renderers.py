"""agent 工具结果 → 对话内富卡片分发（§1.2④）。

按工具名渲染：get_quote → 报价卡、get_money_flow_today → 资金流卡、
get_bars → 迷你 K 线表（≤10 行）、get_prediction_history → 预测卡；
其余工具返回 None，对话流只显示工具行的文本 digest。

结果超过 8KB 会被 agent 层截断（尾部带 "[truncated, N bytes omitted]"），
截断后不再是合法 JSON——is_truncated 供工具行追加「（结果过大已截断）」。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from textual.widgets import Static

from mommy_chaogu.tui.widgets import cards

TRUNCATED_MARK = "[truncated"
_log = logging.getLogger(__name__)


def is_truncated(result: str) -> bool:
    """工具结果是否被 agent 层截断（>8KB）。"""
    return TRUNCATED_MARK in result


def render_tool_result(name: str, result: str, theme: str = "dark") -> Static | None:
    """按工具名分发渲染富卡片。

    返回 None 的情形：非 JSON、{"error": ...}、被截断、无卡片映射——
    调用方只显示工具行 digest。
    """
    data = _parse(result)
    if data is None:
        return None
    try:
        if name == "get_quote" and isinstance(data, dict):
            return cards.quote_card(data, theme)
        if name == "get_money_flow_today":
            if isinstance(data, dict):
                return cards.flow_tool_card(data, theme)
            if isinstance(data, list):
                return cards.flow_multi_card(data, theme)
        if name == "get_bars" and isinstance(data, list):
            return cards.bars_card(data, theme)
        if name == "get_prediction_history" and isinstance(data, list):
            return cards.predictions_tool_card(data, theme)
    except Exception as e:
        _log.warning("工具结果卡片渲染失败 (%s): %s", name, e)
        return None
    return None


def _parse(result: str) -> Any | None:
    """解析工具结果 JSON；截断 / 非 JSON / error 形态返回 None。"""
    if is_truncated(result):
        return None
    try:
        data: Any = json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and "error" in data:
        return None
    return data
