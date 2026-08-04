"""ThemeService 批量行情与部分失败测试。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from mommy_chaogu.services.theme_service import THEME_QUOTE_BATCH_SIZE, ThemeService


def _quote(code: str) -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        price=Decimal("10"),
        change_pct=Decimal("1.5"),
        volume=100,
        turnover_rate=Decimal("0.2"),
        pe_dynamic=Decimal("12"),
        extra={},
    )


def _theme(size: int) -> dict[str, object]:
    return {
        "name": "测试主题",
        "stocks": [{"code": f"{index:06d}", "name": f"股票{index}"} for index in range(size)],
    }


def test_get_theme_quotes_batches_and_preserves_order() -> None:
    adapter = MagicMock()
    adapter.get_quotes.side_effect = lambda codes: [_quote(code) for code in codes]
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(51)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    assert len(items) == 51
    assert adapter.get_quotes.call_count == 2
    assert adapter.get_quotes.call_args_list[0].args[0] == [f"{i:06d}" for i in range(50)]
    assert adapter.get_quotes.call_args_list[1].args[0] == ["000050"]
    assert [item["code"] for item in items[:3]] == ["000000", "000001", "000002"]
    assert all(item["price"] == Decimal("10") for item in items)


def test_get_theme_quotes_keeps_other_batches_when_one_fails() -> None:
    adapter = MagicMock()
    adapter.get_quotes.side_effect = [
        TimeoutError("upstream timeout"),
        [_quote("000050")],
    ]
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(THEME_QUOTE_BATCH_SIZE + 1)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    assert len(items) == THEME_QUOTE_BATCH_SIZE + 1
    assert items[0]["price"] is None
    assert "upstream timeout" in str(items[0]["error"])
    assert items[-1]["price"] == Decimal("10")
    assert items[-1]["error"] is None
