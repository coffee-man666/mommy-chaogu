"""flows.signals 单测 — ratio-based 资金流规则评估。

覆盖：
- default_rules() 默认规则集
- FlowRule.matches() 四种方向 × 边界
- StockSnapshot.ratio 计算（含 float_market_cap=0 防护）
- evaluate() 多轮评估 + 首轮不触发 delta 规则
- FlowSignal.format() 输出格式
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from mommy_chaogu.flows.signals import (
    FlowRule,
    FlowSignal,
    Severity,
    StockSnapshot,
    default_rules,
    evaluate,
)

# ---------- Helpers ----------


def _snapshot(
    code: str = "600519",
    name: str = "茅台",
    main_net: str = "50000000",
    float_mcap: str = "100000000000",
) -> StockSnapshot:
    return StockSnapshot(
        code=code,
        name=name,
        main_net=Decimal(main_net),
        float_market_cap=Decimal(float_mcap),
    )


# ========== default_rules ==========


def test_default_rules_count_and_ids() -> None:
    rules = default_rules()
    assert len(rules) == 4
    ids = {r.rule_id for r in rules}
    assert ids == {"flow_in_spike", "flow_in_surge", "flow_out_spike", "flow_out_surge"}


def test_default_rules_all_delta_5min() -> None:
    for r in default_rules():
        assert r.metric == "delta_5min"


def test_default_rules_severity_mapping() -> None:
    by_id = {r.rule_id: r for r in default_rules()}
    assert by_id["flow_in_spike"].severity == Severity.WARN
    assert by_id["flow_in_surge"].severity == Severity.CRIT
    assert by_id["flow_out_spike"].severity == Severity.WARN
    assert by_id["flow_out_surge"].severity == Severity.CRIT


def test_default_rules_thresholds() -> None:
    by_id = {r.rule_id: r for r in default_rules()}
    assert by_id["flow_in_spike"].threshold_bp == Decimal("5")
    assert by_id["flow_in_surge"].threshold_bp == Decimal("10")
    assert by_id["flow_out_spike"].threshold_bp == Decimal("5")
    assert by_id["flow_out_surge"].threshold_bp == Decimal("10")


def test_default_rules_directions() -> None:
    by_id = {r.rule_id: r for r in default_rules()}
    assert by_id["flow_in_spike"].direction == "in"
    assert by_id["flow_out_spike"].direction == "out"


# ========== FlowRule.matches — delta_5min ==========


def _delta_in_rule(bp: str = "5") -> FlowRule:
    return FlowRule(
        rule_id="t",
        severity=Severity.WARN,
        metric="delta_5min",
        direction="in",
        threshold_bp=Decimal(bp),
        description="",
    )


def _delta_out_rule(bp: str = "5") -> FlowRule:
    return FlowRule(
        rule_id="t",
        severity=Severity.WARN,
        metric="delta_5min",
        direction="out",
        threshold_bp=Decimal(bp),
        description="",
    )


def test_delta_in_matches_above_threshold() -> None:
    # delta_ratio = 0.0006 = 6bp > 5bp, main_net > 0
    assert _delta_in_rule().matches(
        ratio=Decimal("0.001"),
        delta_ratio=Decimal("0.0006"),
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_delta_in_not_matches_at_threshold() -> None:
    # delta_ratio == 5bp 恰好等于阈值（严格 >），不触发
    assert not _delta_in_rule().matches(
        ratio=Decimal("0.001"),
        delta_ratio=Decimal("0.0005"),
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_delta_in_not_matches_negative_main_net() -> None:
    # main_net < 0 即使 delta_ratio 很大也不触发 in 规则
    assert not _delta_in_rule().matches(
        ratio=Decimal("0.001"),
        delta_ratio=Decimal("0.0006"),
        main_net=Decimal("-50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_delta_in_not_matches_none_delta() -> None:
    assert not _delta_in_rule().matches(
        ratio=Decimal("0.001"),
        delta_ratio=None,
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_delta_out_matches_above_threshold() -> None:
    # delta_ratio = -0.0006 → -delta_ratio = 0.0006 = 6bp > 5bp, main_net < 0
    assert _delta_out_rule().matches(
        ratio=Decimal("-0.001"),
        delta_ratio=Decimal("-0.0006"),
        main_net=Decimal("-50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_delta_out_not_matches_positive_main_net() -> None:
    # main_net > 0 不触发 out
    assert not _delta_out_rule().matches(
        ratio=Decimal("-0.001"),
        delta_ratio=Decimal("-0.0006"),
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


# ========== FlowRule.matches — cumulative_daily ==========


def _cum_in_rule(bp: str = "5") -> FlowRule:
    return FlowRule(
        rule_id="t",
        severity=Severity.WARN,
        metric="cumulative_daily",
        direction="in",
        threshold_bp=Decimal(bp),
        description="",
    )


def _cum_out_rule(bp: str = "5") -> FlowRule:
    return FlowRule(
        rule_id="t",
        severity=Severity.WARN,
        metric="cumulative_daily",
        direction="out",
        threshold_bp=Decimal(bp),
        description="",
    )


def test_cumulative_in_matches() -> None:
    # ratio = 0.001 = 10bp > 5bp, main_net > 0
    assert _cum_in_rule().matches(
        ratio=Decimal("0.001"),
        delta_ratio=Decimal("0.0006"),
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_cumulative_in_ignores_delta_ratio() -> None:
    # cumulative_daily 不看 delta_ratio，只看 ratio 绝对值
    assert _cum_in_rule().matches(
        ratio=Decimal("0.001"),
        delta_ratio=None,
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_cumulative_out_matches() -> None:
    assert _cum_out_rule().matches(
        ratio=Decimal("-0.001"),
        delta_ratio=None,
        main_net=Decimal("-50000000"),
        float_market_cap=Decimal("100000000000"),
    )


def test_cumulative_out_not_matches_positive_main_net() -> None:
    # ratio 为负但 main_net 为正 → 不触发 out
    assert not _cum_out_rule().matches(
        ratio=Decimal("-0.001"),
        delta_ratio=None,
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
    )


# ========== StockSnapshot.ratio ==========


def test_snapshot_ratio_normal() -> None:
    s = _snapshot(main_net="50000000", float_mcap="100000000000")
    # 5e7 / 1e11 = 5e-4 = 5bp
    assert s.ratio == Decimal("0.0005")


def test_snapshot_ratio_zero_float_mcap() -> None:
    s = StockSnapshot(code="x", name="n", main_net=Decimal("100"), float_market_cap=Decimal("0"))
    assert s.ratio == Decimal("0")


def test_snapshot_ratio_negative() -> None:
    s = _snapshot(main_net="-50000000", float_mcap="100000000000")
    assert s.ratio == Decimal("-0.0005")


# ========== evaluate ==========


def test_evaluate_first_round_no_delta_signals() -> None:
    """首轮（previous=None）：delta_5min 规则不会触发。"""
    snap = [_snapshot(main_net="50000000", float_mcap="100000000000")]
    signals = evaluate(snap, previous=None)
    # 默认规则全是 delta_5min，首轮无 delta → 空列表
    assert signals == []


def test_evaluate_second_round_triggers_in_spike() -> None:
    snap = [_snapshot(main_net="50000000", float_mcap="100000000000")]
    prev = {"600519": Decimal("0")}  # 上轮 ratio=0
    signals = evaluate(snap, previous=prev)
    # delta = 0.0005 = 5bp，严格 > 5bp 不触发 spike(5)
    # 但 main_net=5e7, ratio=5bp 恰好阈值 → 不触发
    assert signals == []


def test_evaluate_second_round_triggers_in_spike_above_threshold() -> None:
    # main_net=6e7, float=1e11 → ratio=6bp, delta=6bp > 5bp → 触发 flow_in_spike
    snap = [_snapshot(main_net="60000000", float_mcap="100000000000")]
    prev = {"600519": Decimal("0")}
    signals = evaluate(snap, previous=prev)
    assert len(signals) == 1
    assert signals[0].rule_id == "flow_in_spike"
    assert signals[0].severity == Severity.WARN
    assert signals[0].delta_ratio == Decimal("0.0006")


def test_evaluate_triggers_in_surge_critical() -> None:
    # delta = 12bp → 触发 spike(5) + surge(10)
    snap = [_snapshot(main_net="120000000", float_mcap="100000000000")]
    prev = {"600519": Decimal("0")}
    signals = evaluate(snap, previous=prev)
    ids = {s.rule_id for s in signals}
    assert ids == {"flow_in_spike", "flow_in_surge"}
    surge = next(s for s in signals if s.rule_id == "flow_in_surge")
    assert surge.severity == Severity.CRIT


def test_evaluate_out_direction() -> None:
    snap = [_snapshot(main_net="-120000000", float_mcap="100000000000")]
    prev = {"600519": Decimal("0")}
    signals = evaluate(snap, previous=prev)
    ids = {s.rule_id for s in signals}
    assert ids == {"flow_out_spike", "flow_out_surge"}


def test_evaluate_skips_zero_float_mcap() -> None:
    snap = [
        StockSnapshot(code="z", name="z", main_net=Decimal("100"), float_market_cap=Decimal("0")),
    ]
    prev: dict[str, Decimal] = {}
    assert evaluate(snap, previous=prev) == []


def test_evaluate_uses_custom_rules() -> None:
    snap = [_snapshot(main_net="60000000", float_mcap="100000000000")]
    prev = {"600519": Decimal("0")}
    custom = [
        FlowRule(
            rule_id="custom",
            severity=Severity.INFO,
            metric="cumulative_daily",
            direction="in",
            threshold_bp=Decimal("1"),
            description="custom rule",
        )
    ]
    signals = evaluate(snap, previous=prev, rules=custom)
    assert len(signals) == 1
    assert signals[0].rule_id == "custom"
    assert signals[0].severity == Severity.INFO
    assert "当日累计" in signals[0].metric
    assert "净流入" in signals[0].metric


def test_evaluate_metric_labels() -> None:
    snap = [_snapshot(main_net="60000000", float_mcap="100000000000")]
    prev = {"600519": Decimal("0")}
    signals = evaluate(snap, previous=prev)
    assert "5min delta" in signals[0].metric
    assert "净流入" in signals[0].metric
    assert ">5bp" in signals[0].metric


def test_evaluate_signal_carries_snapshot_data() -> None:
    snap = [_snapshot(code="000001", name="平安", main_net="60000000", float_mcap="100000000000")]
    prev = {"000001": Decimal("0")}
    signals = evaluate(snap, previous=prev)
    sig = signals[0]
    assert sig.code == "000001"
    assert sig.name == "平安"
    assert sig.main_net == Decimal("60000000")
    assert sig.float_market_cap == Decimal("100000000000")
    assert sig.ratio == Decimal("0.0006")


# ========== FlowSignal.format ==========


def test_signal_format_no_delta() -> None:
    sig = FlowSignal(
        rule_id="x",
        code="600519",
        name="茅台",
        severity=Severity.WARN,
        metric="当日累计·净流入>5bp",
        ratio=Decimal("0.001"),
        delta_ratio=None,
        main_net=Decimal("50000000"),
        float_market_cap=Decimal("100000000000"),
        note="",
    )
    out = sig.format()
    assert "[WARN]" in out
    assert "600519" in out
    assert "茅台" in out
    assert "10.0bp" in out  # ratio 0.001 = 10bp
    assert "0.50亿" in out  # 5e7 = 0.5亿
    assert "1000亿" in out  # 流通市值
    # delta_ratio=None 不显示 Δ
    assert "Δ" not in out


def test_signal_format_positive_delta() -> None:
    sig = FlowSignal(
        rule_id="x",
        code="600519",
        name="茅台",
        severity=Severity.CRIT,
        metric="5min delta·净流入>10bp",
        ratio=Decimal("0.0012"),
        delta_ratio=Decimal("0.0006"),
        main_net=Decimal("60000000"),
        float_market_cap=Decimal("100000000000"),
        note="",
    )
    out = sig.format()
    assert "[CRIT]" in out
    assert "Δ" in out
    assert "↑" in out
    assert "6.0bp" in out  # delta 0.0006 = 6bp


def test_signal_format_negative_delta() -> None:
    sig = FlowSignal(
        rule_id="x",
        code="600519",
        name="茅台",
        severity=Severity.WARN,
        metric="5min delta·净流出>5bp",
        ratio=Decimal("-0.0006"),
        delta_ratio=Decimal("-0.0006"),
        main_net=Decimal("-60000000"),
        float_market_cap=Decimal("100000000000"),
        note="",
    )
    out = sig.format()
    assert "↓" in out
    assert "6.0bp" in out


def test_signal_triggered_at_defaults_to_now() -> None:
    sig = FlowSignal(
        rule_id="x",
        code="c",
        name="n",
        severity=Severity.INFO,
        metric="m",
        ratio=Decimal("0"),
        delta_ratio=None,
        main_net=Decimal("0"),
        float_market_cap=Decimal("1"),
        note="",
    )
    assert isinstance(sig.triggered_at, datetime)


# ========== 多股票 evaluate ==========


def test_evaluate_multiple_stocks() -> None:
    snap = [
        _snapshot(code="000001", name="A", main_net="60000000", float_mcap="100000000000"),
        _snapshot(code="000002", name="B", main_net="-60000000", float_mcap="100000000000"),
        _snapshot(code="000003", name="C", main_net="1000000", float_mcap="100000000000"),
    ]
    prev = {"000001": Decimal("0"), "000002": Decimal("0"), "000003": Decimal("0")}
    signals = evaluate(snap, previous=prev)
    codes = {s.code for s in signals}
    # 000001: delta 6bp in → spike; 000002: delta -6bp out → spike; 000003: delta 0.1bp 不触发
    assert "000001" in codes
    assert "000002" in codes
    assert "000003" not in codes
