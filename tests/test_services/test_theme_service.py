"""ThemeService 批量行情与部分失败测试。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from mommy_chaogu.services.theme_service import (
    THEME_FLOW_MAX_ATTEMPTS,
    THEME_FLOW_MAX_STOCKS,
    THEME_QUOTE_BATCH_SIZE,
    ThemeService,
)


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


def _flow(code: str, amount: Decimal) -> SimpleNamespace:
    """当日资金流记录，字段对齐 MoneyFlow（只需要 main_net）。"""
    return SimpleNamespace(
        code=code,
        name=f"股票{code}",
        timestamp=datetime(2026, 8, 15, 15, 0),
        main_net=SimpleNamespace(amount=amount),
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


def test_get_theme_quotes_fills_main_net_inflow_from_money_flow() -> None:
    adapter = MagicMock()
    adapter.get_quotes.side_effect = lambda codes: [_quote(code) for code in codes]
    # 000001 无资金流数据（返回空列表），其余正常
    adapter.get_today_money_flow.side_effect = lambda code: (
        [] if code == "000001" else [_flow(code, Decimal("123.45"))]
    )
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(3)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    assert [i["main_net_inflow"] for i in items] == [
        Decimal("123.45"),
        None,
        Decimal("123.45"),
    ]
    # 其他字段不受影响
    assert all(i["price"] == Decimal("10") for i in items)
    assert all(i["error"] is None for i in items)


def test_get_theme_quotes_money_flow_failure_keeps_other_fields() -> None:
    adapter = MagicMock()
    adapter.get_quotes.side_effect = lambda codes: [_quote(code) for code in codes]
    adapter.get_today_money_flow.side_effect = RuntimeError("flow upstream down")
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(3)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    # 单只资金流失败静默置 None，行情等其他字段照常
    assert all(i["main_net_inflow"] is None for i in items)
    assert all(i["price"] == Decimal("10") for i in items)
    assert all(i["error"] is None for i in items)


def test_get_theme_quotes_caps_money_flow_lookups() -> None:
    adapter = MagicMock()
    adapter.get_quotes.side_effect = lambda codes: [_quote(code) for code in codes]
    adapter.get_today_money_flow.return_value = [_flow("x", Decimal("1"))]
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(51)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    # 资金流无批量接口，填充按主题顺序截断到代表股上限
    assert adapter.get_today_money_flow.call_count == THEME_FLOW_MAX_STOCKS
    assert adapter.get_today_money_flow.call_args_list[0].args[0] == "000000"
    filled = [i for i in items if i["main_net_inflow"] is not None]
    assert len(filled) == THEME_FLOW_MAX_STOCKS
    assert all(i["main_net_inflow"] == Decimal("1") for i in filled)


def test_get_theme_quotes_failed_flow_does_not_consume_fill_slot() -> None:
    """失败/空数据的股票不占填充名额：排在前面的失败由后面的股票补上。"""
    adapter = MagicMock()
    adapter.get_quotes.side_effect = lambda codes: [_quote(code) for code in codes]
    # 前两只失败（一空一异常），其余正常
    adapter.get_today_money_flow.side_effect = lambda code: (
        (_ for _ in ()).throw(RuntimeError("boom"))
        if code == "000000"
        else []
        if code == "000001"
        else [_flow(code, Decimal("7"))]
    )
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(THEME_FLOW_MAX_STOCKS + 2)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    filled = [i for i in items if i["main_net_inflow"] is not None]
    # 12 只候选：前 2 只失败不占名额，填满 10 只（000002–000011）
    assert len(filled) == THEME_FLOW_MAX_STOCKS
    assert adapter.get_today_money_flow.call_count == THEME_FLOW_MAX_STOCKS + 2


def test_get_theme_quotes_attempt_ceiling_bounds_upstream_requests() -> None:
    """持续失败时总请求数被 THEME_FLOW_MAX_ATTEMPTS 封顶（N+1 防护）。"""
    adapter = MagicMock()
    adapter.get_quotes.side_effect = lambda codes: [_quote(code) for code in codes]
    adapter.get_today_money_flow.side_effect = RuntimeError("flow upstream down")
    service = ThemeService(adapter=adapter)
    service.get_theme = lambda _theme_id: _theme(51)  # type: ignore[method-assign]

    items = service.get_theme_quotes("test")

    assert adapter.get_today_money_flow.call_count == THEME_FLOW_MAX_ATTEMPTS
    assert all(i["main_net_inflow"] is None for i in items)
