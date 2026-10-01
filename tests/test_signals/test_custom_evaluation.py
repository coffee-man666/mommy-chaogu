"""阶段五共用评估函数单测：CustomAlert + Quote → Signal。

覆盖计划验收点：
- 命中转 Signal（字段契约：rule_id/severity/trigger/threshold）
- 未命中不产信号
- 告警代码不在 Quote 集内时经 fetch_quote 补拉（非自选股告警代码会评估）
- fetch 失败容忍（单码失败不影响其他告警）
- 环境变量开关一键停用（MOMMY_ALERTS_BUILTIN_ONLY）
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.signals.custom_evaluation import (
    MOMMY_ALERTS_BUILTIN_ONLY_ENV,
    builtin_alerts_only,
    evaluate_custom_alerts,
    load_enabled_custom_alerts,
)
from mommy_chaogu.signals.types import SignalSeverity

# ---------- Helpers ----------


def _make_quote(code: str = "600519", price: str = "100.00", change_pct: str = "0") -> Quote:
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


def _make_store(tmp_path: Path) -> CustomAlertStore:
    return CustomAlertStore(tmp_path / "portfolio.db")


# ---------- evaluate_custom_alerts ----------


def test_hit_price_above_produces_signal(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add("600519", "贵州茅台", "price_above", Decimal("1600"))
    alerts = load_enabled_custom_alerts(store)

    signals = evaluate_custom_alerts(alerts, {"600519": _make_quote(price="1700.00")})

    assert len(signals) == 1
    s = signals[0]
    assert s.code == "600519"
    assert s.severity is SignalSeverity.WARNING
    assert s.rule_id == f"custom_alert_{alerts[0].id}"
    assert s.trigger_value == Decimal("1700.00")
    assert s.threshold_value == Decimal("1600")
    assert s.metrics["condition"] == "price_above"
    assert s.metrics["alert_id"] == alerts[0].id


def test_miss_produces_no_signal(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add("600519", "贵州茅台", "price_above", Decimal("1600"))
    alerts = load_enabled_custom_alerts(store)

    signals = evaluate_custom_alerts(alerts, {"600519": _make_quote(price="1500.00")})
    assert signals == []


def test_alert_code_missing_from_quotes_is_fetched(tmp_path: Path) -> None:
    """告警代码不在 Quote 集（如不在自选股 Snapshot）→ 经 fetch_quote 补拉后评估。"""
    store = _make_store(tmp_path)
    store.add("000001", "平安银行", "price_above", Decimal("10"))
    alerts = load_enabled_custom_alerts(store)

    fetched: list[str] = []

    def fetch(code: str) -> Quote | None:
        fetched.append(code)
        return _make_quote(code=code, price="10.27")

    signals = evaluate_custom_alerts(alerts, {}, fetch_quote=fetch)

    assert fetched == ["000001"]
    assert len(signals) == 1
    assert signals[0].code == "000001"


def test_fetch_failure_tolerated(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add("000001", "平安银行", "price_above", Decimal("10"))
    store.add("600519", "贵州茅台", "price_above", Decimal("1600"))
    alerts = load_enabled_custom_alerts(store)

    def fetch(code: str) -> Quote | None:
        if code == "000001":
            raise ConnectionError("simulated")
        return _make_quote(code=code, price="1700.00")

    signals = evaluate_custom_alerts(alerts, {}, fetch_quote=fetch)
    # 000001 拉失败跳过，600519 正常命中
    assert [s.code for s in signals] == ["600519"]


def test_fetch_returning_none_skips(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add("000001", "平安银行", "price_above", Decimal("10"))
    alerts = load_enabled_custom_alerts(store)

    signals = evaluate_custom_alerts(alerts, {}, fetch_quote=lambda _c: None)
    assert signals == []


def test_change_pct_condition_uses_change_pct_trigger(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add("002129", "TCL中环", "change_pct_above", Decimal("5"))
    alerts = load_enabled_custom_alerts(store)

    signals = evaluate_custom_alerts(
        alerts, {"002129": _make_quote(code="002129", change_pct="5.32")}
    )
    assert len(signals) == 1
    assert signals[0].trigger_value == Decimal("5.32")


def test_empty_alerts_short_circuit(tmp_path: Path) -> None:
    signals = evaluate_custom_alerts([], {"600519": _make_quote()})
    assert signals == []


# ---------- 环境变量开关 ----------


def test_env_switch_disables_loading(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = _make_store(tmp_path)
    store.add("600519", "贵州茅台", "price_above", Decimal("1600"))

    monkeypatch.setenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "1")
    assert builtin_alerts_only() is True
    assert load_enabled_custom_alerts(store) == []

    monkeypatch.setenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "false")
    assert builtin_alerts_only() is False
    assert len(load_enabled_custom_alerts(store)) == 1


def test_env_switch_absent_by_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, raising=False)
    assert builtin_alerts_only() is False


def test_none_store_returns_empty() -> None:
    assert load_enabled_custom_alerts(None) == []
