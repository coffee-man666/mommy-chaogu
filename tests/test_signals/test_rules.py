"""告警规则单测 — 每条规则独立验证。

通过 Snapshot fixture 构造测试场景，验证：
- 触发阈值正确
- 严重度正确（warning vs critical）
- 不触发场景返回空
- 配置可改
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)
from mommy_chaogu.monitor import Snapshot, SnapshotRow
from mommy_chaogu.signals.rules import (
    GapOpenRule,
    MainFlowThresholdRule,
    PortfolioBreadthRule,
    PortfolioMainFlowRule,
    PriceChangeThresholdRule,
    RuleConfig,
    TurnoverSurgeRule,
    VolumeSurgeRule,
    default_rules,
)
from mommy_chaogu.signals.types import SignalSeverity

# ---------- Helpers ----------

def _make_quote(
    code: str = "600519",
    price: str = "100.00",
    change_pct: str = "0",
    open_p: str | None = None,
    prev_close: str | None = None,
    volume_ratio: str | None = None,
    turnover_rate: str | None = None,
) -> Quote:
    return Quote(
        code=code,
        name=f"名称{code}",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal(price),
        open=Decimal(open_p or price),
        high=Decimal(price),
        low=Decimal(price),
        prev_close=Decimal(prev_close or price),
        change=Decimal("0"),
        change_pct=Decimal(change_pct),
        volume=100000,
        turnover=Money.from_yuan(100000000),
        turnover_rate=Decimal(turnover_rate) if turnover_rate else None,
        volume_ratio=Decimal(volume_ratio) if volume_ratio else None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime.now(),
    )


def _make_flow(code: str = "600519", main_yuan: float = 0.0) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=f"名称{code}",
        timestamp=datetime.now(),
        main_net=Money.from_yuan(main_yuan),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(0),
        super_large_net=Money.from_yuan(0),
    )


def _make_snapshot(rows: list[tuple[Quote, MoneyFlow | None]]) -> Snapshot:
    """rows: [(quote, flow_or_None), ...]"""
    snap_rows: list[SnapshotRow] = []
    for q, f in rows:
        snap_rows.append(SnapshotRow(
            entry=None,  # type: ignore[arg-type]  # rule tests don't care about entry
            group_name="test",
            quote=q,
            latest_flow=f,
        ))
    return Snapshot.build(snap_rows, snapshot_id=1)


# ========== PriceChangeThresholdRule ==========

def test_price_change_above_warning() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="3.5"), None)])
    rule = PriceChangeThresholdRule()
    signals = rule.evaluate(snap)
    assert len(signals) == 1
    assert signals[0].severity == SignalSeverity.WARNING
    assert signals[0].rule_id == "price_change_threshold"
    assert "3.50%" in signals[0].title


def test_price_change_above_critical() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="6.0"), None)])
    signals = PriceChangeThresholdRule().evaluate(snap)
    assert signals[0].severity == SignalSeverity.CRITICAL


def test_price_change_negative_triggers_too() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="-4.0"), None)])
    signals = PriceChangeThresholdRule().evaluate(snap)
    assert len(signals) == 1
    assert "跌" in signals[0].title


def test_price_change_below_threshold_no_signal() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="1.0"), None)])
    assert PriceChangeThresholdRule().evaluate(snap) == []


def test_price_change_custom_threshold() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="4.5"), None)])
    cfg = RuleConfig(
        rule_id="price_change_threshold",
        params={"warning_threshold_pct": 5.0, "critical_threshold_pct": 8.0},
    )
    # 4.5% < 5% → 不触发
    assert PriceChangeThresholdRule(cfg).evaluate(snap) == []


# ========== GapOpenRule ==========

def test_gap_open_high() -> None:
    snap = _make_snapshot([(_make_quote(open_p="103.00", prev_close="100.00"), None)])
    signals = GapOpenRule().evaluate(snap)
    assert len(signals) == 1
    assert "高开" in signals[0].title
    assert "3.00%" in signals[0].title


def test_gap_open_low() -> None:
    snap = _make_snapshot([(_make_quote(open_p="98.00", prev_close="100.00"), None)])
    signals = GapOpenRule().evaluate(snap)
    assert len(signals) == 1
    assert "低开" in signals[0].title


def test_gap_open_below_threshold() -> None:
    snap = _make_snapshot([(_make_quote(open_p="101.00", prev_close="100.00"), None)])
    assert GapOpenRule().evaluate(snap) == []


def test_gap_open_zero_prev_close_skipped() -> None:
    snap = _make_snapshot([(_make_quote(open_p="100", prev_close="0"), None)])
    assert GapOpenRule().evaluate(snap) == []


# ========== MainFlowThresholdRule ==========

def test_main_flow_above_warning() -> None:
    snap = _make_snapshot([(_make_quote(), _make_flow(main_yuan=60_000_000))])
    signals = MainFlowThresholdRule().evaluate(snap)
    assert len(signals) == 1
    assert signals[0].severity == SignalSeverity.WARNING
    assert "流入" in signals[0].title


def test_main_flow_above_critical_negative() -> None:
    snap = _make_snapshot([(_make_quote(), _make_flow(main_yuan=-300_000_000))])
    signals = MainFlowThresholdRule().evaluate(snap)
    assert signals[0].severity == SignalSeverity.CRITICAL
    assert "流出" in signals[0].title


def test_main_flow_below_threshold_no_signal() -> None:
    snap = _make_snapshot([(_make_quote(), _make_flow(main_yuan=10_000_000))])
    assert MainFlowThresholdRule().evaluate(snap) == []


def test_main_flow_missing_flow_skipped() -> None:
    snap = _make_snapshot([(_make_quote(), None)])
    assert MainFlowThresholdRule().evaluate(snap) == []


# ========== VolumeSurgeRule ==========

def test_volume_surge_triggers() -> None:
    snap = _make_snapshot([(_make_quote(volume_ratio="2.5"), None)])
    signals = VolumeSurgeRule().evaluate(snap)
    assert len(signals) == 1
    assert "放量" in signals[0].title


def test_volume_surge_below_threshold() -> None:
    snap = _make_snapshot([(_make_quote(volume_ratio="1.5"), None)])
    assert VolumeSurgeRule().evaluate(snap) == []


def test_volume_surge_missing_skipped() -> None:
    snap = _make_snapshot([(_make_quote(), None)])
    assert VolumeSurgeRule().evaluate(snap) == []


# ========== TurnoverSurgeRule ==========

def test_turnover_surge_triggers() -> None:
    snap = _make_snapshot([(_make_quote(turnover_rate="6.5"), None)])
    signals = TurnoverSurgeRule().evaluate(snap)
    assert len(signals) == 1
    assert signals[0].severity == SignalSeverity.INFO


def test_turnover_surge_below() -> None:
    snap = _make_snapshot([(_make_quote(turnover_rate="3.0"), None)])
    assert TurnoverSurgeRule().evaluate(snap) == []


# ========== PortfolioBreadthRule ==========

def test_portfolio_breadth_all_up() -> None:
    snap = _make_snapshot([
        (_make_quote("1", change_pct="1"), None),
        (_make_quote("2", change_pct="2"), None),
        (_make_quote("3", change_pct="-1"), None),
    ])
    # 2/3 = 66.7% < 70% → 不触发
    assert PortfolioBreadthRule().evaluate(snap) == []


def test_portfolio_breadth_triggers_above_70pct() -> None:
    snap = _make_snapshot([
        (_make_quote("1", change_pct="1"), None),
        (_make_quote("2", change_pct="2"), None),
        (_make_quote("3", change_pct="-1"), None),
        (_make_quote("4", change_pct="3"), None),
    ])
    # 3/4 = 75% → 触发
    signals = PortfolioBreadthRule().evaluate(snap)
    assert len(signals) == 1
    assert "普涨" in signals[0].title
    assert signals[0].severity == SignalSeverity.INFO


def test_portfolio_breadth_empty() -> None:
    snap = _make_snapshot([])
    assert PortfolioBreadthRule().evaluate(snap) == []


# ========== PortfolioMainFlowRule ==========

def test_portfolio_main_flow_warning() -> None:
    snap = _make_snapshot([
        (_make_quote("1", change_pct="1"), _make_flow("1", 200_000_000)),
        (_make_quote("2", change_pct="-1"), _make_flow("2", -50_000_000)),
    ])
    # 合计 = +150_000_000 > 1亿 → warning
    signals = PortfolioMainFlowRule().evaluate(snap)
    assert len(signals) == 1
    assert signals[0].severity == SignalSeverity.WARNING
    assert signals[0].code == "PORTFOLIO"


def test_portfolio_main_flow_critical() -> None:
    snap = _make_snapshot([
        (_make_quote("1"), _make_flow("1", 1_000_000_000)),
        (_make_quote("2"), _make_flow("2", -300_000_000)),
    ])
    # 合计 = +700M > 5亿 → critical
    signals = PortfolioMainFlowRule().evaluate(snap)
    assert signals[0].severity == SignalSeverity.CRITICAL


def test_portfolio_main_flow_below() -> None:
    snap = _make_snapshot([(_make_quote("1"), _make_flow("1", 10_000_000))])
    assert PortfolioMainFlowRule().evaluate(snap) == []


# ========== Alerter ==========

def test_default_rules_returns_all_seven() -> None:
    rules = default_rules()
    assert len(rules) == 7
    ids = {r.rule_id for r in rules}
    assert "price_change_threshold" in ids
    assert "main_flow_threshold" in ids
    assert "portfolio_breadth" in ids


def test_rule_disabled_no_signal() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="6.0"), None)])
    cfg = RuleConfig(rule_id="price_change_threshold", enabled=False)
    assert PriceChangeThresholdRule(cfg).evaluate(snap) == []


def test_rule_evaluate_exception_does_not_propagate(caplog: pytest.LogCaptureFixture) -> None:
    """规则内部出错不能影响其他规则。"""

    class BrokenRule(PriceChangeThresholdRule):
        def _evaluate(self, snapshot, config):  # type: ignore[override]
            raise RuntimeError("boom")

    snap = _make_snapshot([(_make_quote(change_pct="6.0"), None)])
    broken = BrokenRule()
    signals = broken.evaluate(snap)
    assert signals == []  # 异常被吞，返回空


def test_signal_format_includes_severity_and_title() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="6.0"), None)])
    s = PriceChangeThresholdRule().evaluate(snap)[0]
    out = s.format()
    assert "CRIT" in out
    assert "涨" in out


def test_signal_format_log_one_line() -> None:
    snap = _make_snapshot([(_make_quote(change_pct="6.0"), None)])
    s = PriceChangeThresholdRule().evaluate(snap)[0]
    log_line = s.format_log()
    assert "\n" not in log_line
    assert "[2026-" in log_line


# ========== Alerter 集成 ==========

def test_alerter_evaluate_multiple_rules(tmp_path: Path) -> None:
    """Alerter 接收 Snapshot，调度多个规则，合并输出。"""
    from mommy_chaogu.signals import Alerter

    snap = _make_snapshot([
        (_make_quote("600519", change_pct="6.0"), _make_flow("600519", -300_000_000)),
        (_make_quote("000001", change_pct="1.0", volume_ratio="3.0"), None),
    ])
    alerter = Alerter.default(log_path=tmp_path / "s.log")
    signals = alerter.evaluate(snap)

    # 600519: 价格 critical + 主力 critical
    # 000001: 量比 warning
    assert len(signals) >= 3

    # 排序：critical 先
    assert signals[0].severity == SignalSeverity.CRITICAL

    # 写日志
    alerter.write_signals_log(signals)
    assert (tmp_path / "s.log").exists()
    content = (tmp_path / "s.log").read_text(encoding="utf-8")
    assert "600519" in content


def test_alerter_no_signal_returns_empty(tmp_path: Path) -> None:
    from mommy_chaogu.signals import Alerter
    # 4 只股票中 2 涨 2 跌 = 50/50，不触发任何规则
    snap = _make_snapshot([
        (_make_quote("1", change_pct="1.0"), None),
        (_make_quote("2", change_pct="-1.0"), None),
        (_make_quote("3", change_pct="0.5"), None),
        (_make_quote("4", change_pct="-0.5"), None),
    ])
    alerter = Alerter.default(log_path=tmp_path / "s.log")
    signals = alerter.evaluate(snap)
    assert signals == []
    alerter.write_signals_log(signals)
    # 空信号不写日志
    assert not (tmp_path / "s.log").exists()
