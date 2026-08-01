"""Validated Web trading-style preferences.

The browser sends only a stable preset identifier. Prompt text remains a
server-owned implementation detail so it cannot replace the Agent's base
contract or be used as an arbitrary system prompt.
"""

from __future__ import annotations

from typing import Literal, cast

type TradingStylePreset = Literal["conservative", "balanced", "aggressive"]

DEFAULT_TRADING_STYLE: TradingStylePreset = "balanced"

_STYLE_CONTEXT: dict[TradingStylePreset, str] = {
    "conservative": "用户偏好稳健投资，请更多关注下行风险、止损位和资金安全。",
    "balanced": "用户偏好均衡分析，请同时呈现机会和风险。",
    "aggressive": "用户偏好积极策略，请更多关注短期动能、资金流入和爆发机会，同时完整披露风险。",
}


def parse_trading_style(value: object) -> TradingStylePreset:
    """Return a validated preset or raise ``ValueError`` for untrusted input."""
    if not isinstance(value, str) or value not in _STYLE_CONTEXT:
        raise ValueError("invalid trading style")
    return cast(TradingStylePreset, value)


def trading_style_context(preset: TradingStylePreset) -> str:
    """Build the delimited system-context addendum for one preset."""
    return f"<trading_preference>\n{_STYLE_CONTEXT[preset]}\n</trading_preference>"
