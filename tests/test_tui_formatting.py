"""Tests for tui/services/formatting.py — all formatting helpers.

Covers format_amount, format_change_pct, format_price, format_flow,
change_arrow, change_color with Decimal / float / int / None inputs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from mommy_chaogu.tui.services.formatting import (  # type: ignore[import-untyped]
    change_arrow,
    change_color,
    format_amount,
    format_change_pct,
    format_flow,
    format_price,
)

# ---------------------------------------------------------------------------
# format_amount — 万/亿/raw
# ---------------------------------------------------------------------------


class TestFormatAmount:
    @pytest.mark.parametrize(
        "val,expected",
        [
            (Decimal("1234567890"), "12.3亿"),
            (Decimal("100000000"), "1.0亿"),
            (Decimal("99999999"), "10000.0万"),
            (Decimal("150000000"), "1.5亿"),
        ],
    )
    def test_yi(self, val: Decimal, expected: str) -> None:
        assert format_amount(val) == expected

    @pytest.mark.parametrize(
        "val,expected",
        [
            (Decimal("12345"), "1.2万"),
            (Decimal("10000"), "1.0万"),
            (Decimal("99999"), "10.0万"),
            (Decimal("50000"), "5.0万"),
        ],
    )
    def test_wan(self, val: Decimal, expected: str) -> None:
        assert format_amount(val) == expected

    @pytest.mark.parametrize(
        "val,expected",
        [
            (Decimal("9999"), "9999.00"),
            (Decimal("100"), "100.00"),
            (Decimal("0"), "0.00"),
        ],
    )
    def test_raw(self, val: Decimal, expected: str) -> None:
        assert format_amount(val) == expected

    def test_float_input(self) -> None:
        assert format_amount(123_456_789.0) == "1.2亿"
        assert format_amount(15000.0) == "1.5万"
        assert format_amount(42.5) == "42.50"

    def test_int_input(self) -> None:
        assert format_amount(200_000_000) == "2.0亿"
        assert format_amount(30000) == "3.0万"
        assert format_amount(99) == "99.00"

    def test_negative(self) -> None:
        assert format_amount(Decimal("-230000000")) == "-2.3亿"
        assert format_amount(Decimal("-50000")) == "-5.0万"
        assert format_amount(-123.0) == "-123.00"

    def test_none(self) -> None:
        assert format_amount(None) == "—"


# ---------------------------------------------------------------------------
# format_change_pct — always signed
# ---------------------------------------------------------------------------


class TestFormatChangePct:
    @pytest.mark.parametrize(
        "val,expected",
        [
            (Decimal("2.31"), "+2.31%"),
            (Decimal("0.5"), "+0.50%"),
            (Decimal("10"), "+10.00%"),
        ],
    )
    def test_positive(self, val: Decimal, expected: str) -> None:
        assert format_change_pct(val) == expected

    @pytest.mark.parametrize(
        "val,expected",
        [
            (Decimal("-0.52"), "-0.52%"),
            (Decimal("-5.23"), "-5.23%"),
            (Decimal("-10"), "-10.00%"),
        ],
    )
    def test_negative(self, val: Decimal, expected: str) -> None:
        assert format_change_pct(val) == expected

    def test_zero(self) -> None:
        assert format_change_pct(Decimal("0")) == "+0.00%"
        assert format_change_pct(0.0) == "+0.00%"

    def test_float(self) -> None:
        assert format_change_pct(3.14) == "+3.14%"
        assert format_change_pct(-2.5) == "-2.50%"

    def test_none(self) -> None:
        assert format_change_pct(None) == "—"


# ---------------------------------------------------------------------------
# format_price — two decimal places
# ---------------------------------------------------------------------------


class TestFormatPrice:
    def test_decimal(self) -> None:
        assert format_price(Decimal("87.45")) == "87.45"
        assert format_price(Decimal("1680.00")) == "1680.00"

    def test_float(self) -> None:
        assert format_price(12.345) == "12.35"
        assert format_price(0.0) == "0.00"

    def test_int(self) -> None:
        assert format_price(100) == "100.00"

    def test_none(self) -> None:
        assert format_price(None) == "—"


# ---------------------------------------------------------------------------
# format_flow — signed amount
# ---------------------------------------------------------------------------


class TestFormatFlow:
    def test_positive(self) -> None:
        assert format_flow(Decimal("230000000")) == "+2.3亿"
        assert format_flow(15000.0) == "+1.5万"

    def test_negative(self) -> None:
        assert format_flow(Decimal("-80000000")) == "-8000.0万"
        assert format_flow(Decimal("-230000000")) == "-2.3亿"
        assert format_flow(-50000.0) == "-5.0万"

    def test_zero(self) -> None:
        assert format_flow(Decimal("0")) == "+0.00"
        assert format_flow(0.0) == "+0.00"

    def test_small(self) -> None:
        assert format_flow(Decimal("1234")) == "+1234.00"

    def test_none(self) -> None:
        assert format_flow(None) == "—"


# ---------------------------------------------------------------------------
# change_arrow — ▲ ▼ —
# ---------------------------------------------------------------------------


class TestChangeArrow:
    def test_positive(self) -> None:
        assert change_arrow(Decimal("1.5")) == "▲"
        assert change_arrow(0.01) == "▲"
        assert change_arrow(100) == "▲"

    def test_negative(self) -> None:
        assert change_arrow(Decimal("-0.52")) == "▼"
        assert change_arrow(-0.01) == "▼"

    def test_zero(self) -> None:
        assert change_arrow(Decimal("0")) == "—"
        assert change_arrow(0.0) == "—"

    def test_none(self) -> None:
        assert change_arrow(None) == "—"


# ---------------------------------------------------------------------------
# change_color — red/green/dim (A股: 红涨绿跌)
# ---------------------------------------------------------------------------


class TestChangeColor:
    def test_positive_red(self) -> None:
        assert change_color(Decimal("2.31")) == "red"
        assert change_color(0.01) == "red"
        assert change_color(100) == "red"

    def test_negative_green(self) -> None:
        assert change_color(Decimal("-0.52")) == "green"
        assert change_color(-5.23) == "green"

    def test_zero_dim(self) -> None:
        assert change_color(Decimal("0")) == "dim"
        assert change_color(0.0) == "dim"

    def test_none_dim(self) -> None:
        assert change_color(None) == "dim"
