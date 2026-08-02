"""Validated Web trading-style preferences.

Preference text is built server-side from the stored user preferences
(``/api/preferences``) so clients cannot replace the Agent's base contract
or inject an arbitrary system prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from mommy_chaogu.preferences import HOLD_PERIOD_TO_DAYS

type TradingStylePreset = Literal["conservative", "balanced", "aggressive"]

DEFAULT_TRADING_STYLE: TradingStylePreset = "balanced"

_STYLE_CONTEXT: dict[TradingStylePreset, str] = {
    "conservative": "用户偏好稳健投资，请更多关注下行风险、止损位和资金安全。",
    "balanced": "用户偏好均衡分析，请同时呈现机会和风险。",
    "aggressive": "用户偏好积极策略，请更多关注短期动能、资金流入和爆发机会，同时完整披露风险。",
}

_HOLD_PERIOD_LABEL = {"short": "短线", "swing": "波段", "long": "中长线"}

_DRAWDOWN_CONTEXT = {
    "low": "对回撤不敏感，可正常呈现波动。",
    "medium": "对回撤中等敏感，提示风险时给出缓冲参考。",
    "high": "对回撤高度敏感，请优先提示回撤和下行风险。",
}

_SEVERITY_LABEL = {"info": "提示", "warning": "警告", "critical": "严重"}


def parse_trading_style(value: object) -> TradingStylePreset:
    """Return a validated preset or raise ``ValueError`` for untrusted input."""
    if not isinstance(value, str) or value not in _STYLE_CONTEXT:
        raise ValueError("invalid trading style")
    return cast(TradingStylePreset, value)


def trading_style_context(preset: TradingStylePreset) -> str:
    """Build the delimited system-context addendum for one preset."""
    return f"<trading_preference>\n{_STYLE_CONTEXT[preset]}\n</trading_preference>"


def preference_context(prefs: Mapping[str, Any]) -> str:
    """Build the delimited system-context addendum from stored preferences.

    一块 ``<trading_preference>`` 内含：交易风格 + 持有周期（含派生默认持有天数）
    + 回撤敏感度 + 通知/关注摘要。非法/缺失字段回落到默认值。
    """
    style = prefs.get("style")
    style_text = _STYLE_CONTEXT.get(style, _STYLE_CONTEXT[DEFAULT_TRADING_STYLE])

    period = prefs.get("holding_period")
    period_label = _HOLD_PERIOD_LABEL.get(period, _HOLD_PERIOD_LABEL["swing"])
    days = HOLD_PERIOD_TO_DAYS.get(period, HOLD_PERIOD_TO_DAYS["swing"])
    period_text = f"持有周期偏好{period_label}，默认持有约 {days} 天。"

    sensitivity = prefs.get("drawdown_sensitivity")
    drawdown_text = _DRAWDOWN_CONTEXT.get(sensitivity, _DRAWDOWN_CONTEXT["medium"])

    min_severity = prefs.get("notify_min_severity")
    severity_label = _SEVERITY_LABEL.get(min_severity, _SEVERITY_LABEL["warning"])
    watched = prefs.get("watched_rules") or []
    watch_text = "关注全部信号规则" if not watched else f"仅关注 {len(watched)} 条信号规则"
    windows = prefs.get("reminder_windows") or []
    window_text = "任意时间接收提醒" if not windows else "仅在设定的提醒时段接收通知"
    notify_text = f"通知偏好：{severity_label} 及以上，{watch_text}，{window_text}。"

    lines = [style_text, period_text, drawdown_text, notify_text]
    return "<trading_preference>\n" + "\n".join(lines) + "\n</trading_preference>"
