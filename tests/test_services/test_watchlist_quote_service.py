"""WatchlistQuoteService：批量报价 + 资金流 join 的统一实现。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.services.watchlist_quote_service import WatchlistQuoteService


def _flow(main_net_yuan: str) -> Any:
    return SimpleNamespace(main_net=SimpleNamespace(amount=Decimal(main_net_yuan), currency="CNY"))


class FakeAdapter:
    """duck-typed adapter：预设报价与资金流，可注入失败。"""

    def __init__(
        self,
        quotes: dict[str, Any] | None = None,
        flows: dict[str, Any] | None = None,
        quotes_raise: bool = False,
        flow_fail_codes: set[str] | None = None,
    ) -> None:
        self._quotes = quotes or {}
        self._flows = flows or {}
        self._quotes_raise = quotes_raise
        self._flow_fail = flow_fail_codes or set()

    def get_quotes(self, codes: list[str]) -> list[Any]:
        if self._quotes_raise:
            raise RuntimeError("上游不可用")
        return [self._quotes[c] for c in codes if c in self._quotes]

    def get_today_money_flow(self, code: str) -> list[Any]:
        if code in self._flow_fail:
            raise RuntimeError("单只资金流失败")
        if code in self._flows:
            return [self._flows[code]]
        return []

    def format_source_label(self) -> str:
        return "腾讯 实时"


def _quote(code: str, name: str, price: str, change_pct: str) -> Any:
    return SimpleNamespace(
        code=code,
        name=name,
        price=Decimal(price),
        change_pct=Decimal(change_pct),
        change=Decimal("0.5"),
    )


def test_fetch_joins_quotes_and_flows_in_order() -> None:
    adapter = FakeAdapter(
        quotes={
            "600519": _quote("600519", "贵州茅台", "1500", "1.2"),
            "000001": _quote("000001", "平安银行", "10", "-0.5"),
        },
        flows={"600519": _flow("300000000")},
    )
    rows = WatchlistQuoteService(adapter).fetch(["600519", "000001"])
    assert [r["code"] for r in rows] == ["600519", "000001"]  # 顺序保持
    assert rows[0]["name"] == "贵州茅台"
    assert rows[0]["price"] == Decimal("1500")
    assert rows[0]["main_flow"] is not None and rows[0]["main_flow"].amount == Decimal("300000000")
    assert rows[1]["main_flow"] is None  # 无资金流数据 → None 而不是报错
    assert "quote_unavailable" not in rows[0]


def test_fetch_records_source_label() -> None:
    svc = WatchlistQuoteService(FakeAdapter(quotes={"600519": _quote("600519", "茅", "1", "0")}))
    svc.fetch(["600519"])
    assert svc.last_source_label == "腾讯 实时"


def test_batch_quote_failure_returns_placeholder_rows() -> None:
    """批量报价整体失败 → 每个 code 一条占位行，资金流照常 join。"""
    adapter = FakeAdapter(quotes_raise=True, flows={"600519": _flow("-50000000")})
    rows = WatchlistQuoteService(adapter).fetch(["600519", "000001"])
    assert len(rows) == 2
    assert all(r.get("quote_unavailable") is True for r in rows)
    assert rows[0]["price"] is None
    assert rows[0]["main_flow"] is not None and rows[0]["main_flow"].amount == Decimal("-50000000")
    assert rows[1]["main_flow"] is None


def test_partial_flow_failure_does_not_break_rows() -> None:
    """单只资金流失败只影响该 code 的 main_flow，报价行照常返回。"""
    adapter = FakeAdapter(
        quotes={
            "600519": _quote("600519", "茅", "10", "1"),
            "000001": _quote("000001", "平", "10", "-1"),
        },
        flows={"600519": _flow("1000000")},
        flow_fail_codes={"000001"},
    )
    rows = WatchlistQuoteService(adapter).fetch(["600519", "000001"])
    assert len(rows) == 2
    assert rows[0]["main_flow"] is not None
    assert rows[1]["main_flow"] is None
    assert rows[1]["price"] == Decimal("10")


def test_none_adapter_or_empty_codes_returns_empty() -> None:
    svc = WatchlistQuoteService(None)
    assert svc.fetch(["600519"]) == []
    assert WatchlistQuoteService(FakeAdapter()).fetch([]) == []


def test_flow_worker_cap_is_four() -> None:
    """并发上限常量与设计一致（防打爆上游）。"""
    from mommy_chaogu.services.watchlist_quote_service import FLOW_MAX_WORKERS

    assert FLOW_MAX_WORKERS == 4
