"""格式化工具（§8）。

数字格式化统一走这里：金额归一为 万/亿，涨跌幅恒带符号，颜色搭配 ▲/▼/—。
"""

from __future__ import annotations

from decimal import Decimal


def format_amount(val: Decimal | float | int | None) -> str:
    """金额归一：>= 亿用"亿"，>= 万用"万"，否则原值。"""
    if val is None:
        return "—"
    v = float(val)
    if abs(v) >= 1_0000_0000:
        return f"{v / 1_0000_0000:.1f}亿"
    if abs(v) >= 1_0000:
        return f"{v / 1_0000:.1f}万"
    return f"{v:.2f}"


def format_change_pct(val: Decimal | float | None) -> str:
    """涨跌幅：恒带符号，保留两位小数。"""
    if val is None:
        return "—"
    v = float(val)
    return f"{v:+.2f}%"


def format_price(val: Decimal | float | None) -> str:
    """价格：保留两位小数。"""
    if val is None:
        return "—"
    return f"{float(val):.2f}"


def format_flow(val: Decimal | float | None) -> str:
    """资金流：带符号金额。"""
    if val is None:
        return "—"
    v = float(val)
    sign = "+" if v >= 0 else ""
    return f"{sign}{format_amount(abs(v))}"


def change_arrow(val: Decimal | float | None) -> str:
    """涨跌箭头：▲ ▼ —"""
    if val is None:
        return "—"
    v = float(val)
    if v > 0:
        return "▲"
    if v < 0:
        return "▼"
    return "—"


def change_color(val: Decimal | float | None) -> str:
    """涨跌颜色（A股约定：红涨绿跌）。"""
    if val is None:
        return "dim"
    v = float(val)
    if v > 0:
        return "red"  # A股红涨
    if v < 0:
        return "green"  # A股绿跌
    return "dim"
