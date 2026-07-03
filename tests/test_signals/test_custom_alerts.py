"""CustomAlertStore + CustomAlert.evaluate 单测。

验证：
- add / list_all / list_for_code / remove CRUD
- evaluate 四种条件的触发 + 不触发
- 持久化（关闭重开 store 数据仍在）
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType
from mommy_chaogu.signals.custom_alerts import (
    CustomAlert,
    CustomAlertNotFoundError,
    CustomAlertStore,
    InvalidConditionError,
)

# ---------- Helpers ----------


def _make_quote(
    code: str = "600519",
    price: str = "100.00",
    change_pct: str = "0",
) -> Quote:
    return Quote(
        code=code,
        name=f"名称{code}",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal(price),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        prev_close=Decimal(price),
        change=Decimal("0"),
        change_pct=Decimal(change_pct),
        volume=100000,
        turnover=Money.from_yuan(100000000),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime.now(),
    )


# ========== Store CRUD ==========


def test_add_and_list(tmp_path: Path) -> None:
    store = CustomAlertStore(tmp_path / "test.db")
    alert = store.add("600519", "贵州茅台", "price_below", Decimal("1600"))
    assert alert.id is not None
    assert alert.code == "600519"
    assert alert.condition == "price_below"
    assert alert.threshold == Decimal("1600")
    assert alert.enabled is True

    alerts = store.list_all()
    assert len(alerts) == 1
    assert alerts[0].code == "600519"


def test_remove(tmp_path: Path) -> None:
    store = CustomAlertStore(tmp_path / "test.db")
    alert = store.add("600519", "贵州茅台", "price_above", Decimal("1600"))
    assert len(store.list_all()) == 1

    store.remove(alert.id)  # type: ignore[arg-type]
    assert len(store.list_all()) == 0

    # remove again → error
    with pytest.raises(CustomAlertNotFoundError):
        store.remove(alert.id)  # type: ignore[arg-type]


def test_list_for_code(tmp_path: Path) -> None:
    store = CustomAlertStore(tmp_path / "test.db")
    store.add("600519", "贵州茅台", "price_above", Decimal("1600"))
    store.add("600519", "贵州茅台", "price_below", Decimal("1500"))
    store.add("000001", "平安银行", "price_above", Decimal("10"))

    maotai = store.list_for_code("600519")
    assert len(maotai) == 2

    bank = store.list_for_code("000001")
    assert len(bank) == 1

    empty = store.list_for_code("999999")
    assert empty == []


def test_invalid_condition_raises(tmp_path: Path) -> None:
    store = CustomAlertStore(tmp_path / "test.db")
    with pytest.raises(InvalidConditionError):
        store.add("600519", "贵州茅台", "invalid_condition", Decimal("100"))


# ========== evaluate ==========


def test_evaluate_price_above() -> None:
    alert = CustomAlert(
        code="600519", name="贵州茅台",
        condition="price_above", threshold=Decimal("1600"),
    )
    # triggered: price 1700 > 1600
    assert CustomAlertStore.evaluate(alert, _make_quote(price="1700.00")) is True
    # not triggered: price 1500 < 1600
    assert CustomAlertStore.evaluate(alert, _make_quote(price="1500.00")) is False
    # boundary: price exactly 1600 → not triggered (strict >)
    assert CustomAlertStore.evaluate(alert, _make_quote(price="1600.00")) is False


def test_evaluate_price_below() -> None:
    alert = CustomAlert(
        code="600519", name="贵州茅台",
        condition="price_below", threshold=Decimal("1600"),
    )
    assert CustomAlertStore.evaluate(alert, _make_quote(price="1500.00")) is True
    assert CustomAlertStore.evaluate(alert, _make_quote(price="1700.00")) is False


def test_evaluate_change_pct_above() -> None:
    alert = CustomAlert(
        code="600519", name="贵州茅台",
        condition="change_pct_above", threshold=Decimal("5"),
    )
    assert CustomAlertStore.evaluate(alert, _make_quote(change_pct="6.0")) is True
    assert CustomAlertStore.evaluate(alert, _make_quote(change_pct="3.0")) is False


def test_evaluate_change_pct_below() -> None:
    alert = CustomAlert(
        code="600519", name="贵州茅台",
        condition="change_pct_below", threshold=Decimal("-5"),
    )
    assert CustomAlertStore.evaluate(alert, _make_quote(change_pct="-6.0")) is True
    assert CustomAlertStore.evaluate(alert, _make_quote(change_pct="-3.0")) is False


def test_evaluate_disabled_returns_false() -> None:
    alert = CustomAlert(
        code="600519", name="贵州茅台",
        condition="price_above", threshold=Decimal("1600"),
        enabled=False,
    )
    assert CustomAlertStore.evaluate(alert, _make_quote(price="2000.00")) is False


# ========== 持久化 ==========


def test_persistence(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    store = CustomAlertStore(db)
    store.add("600519", "贵州茅台", "price_below", Decimal("1600"))
    store.add("000001", "平安银行", "change_pct_above", Decimal("3"))
    assert len(store.list_all()) == 2

    # 关闭后重开
    store2 = CustomAlertStore(db)
    alerts = store2.list_all()
    assert len(alerts) == 2
    codes = {a.code for a in alerts}
    assert codes == {"600519", "000001"}
