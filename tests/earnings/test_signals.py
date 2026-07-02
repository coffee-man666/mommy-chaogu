"""earnings 模块 — Signals 单元测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from mommy_chaogu.earnings.signals import (
    EarningsApproachingRule,
    EarningsBeatRule,
    EarningsContext,
    EarningsMeetRule,
    EarningsMissRule,
    default_earnings_rules,
    evaluate_all,
)
from mommy_chaogu.signals.types import SignalSeverity


def make_ctx(**overrides) -> EarningsContext:
    defaults = dict(
        code="603662",
        name="柯力传感",
        period="H1 2026",
        disclosure_date=date(2026, 7, 20),
        today=date(2026, 7, 13),
        predicted_high=Decimal("217"),
        score_verdict="super_beat",
        score_confidence=Decimal("0.9"),
    )
    defaults.update(overrides)
    return EarningsContext(**defaults)


# ---------- beat ----------


def test_beat_rule_triggers():
    rule = EarningsBeatRule()
    sigs = rule.evaluate(make_ctx(score_verdict="super_beat", score_confidence=Decimal("0.9")))
    assert len(sigs) == 1
    assert sigs[0].severity == SignalSeverity.CRITICAL
    assert "超预期" in sigs[0].detail


def test_beat_rule_low_confidence_no_trigger():
    """置信度 < 0.7 不触发。"""
    rule = EarningsBeatRule()
    sigs = rule.evaluate(make_ctx(score_verdict="super_beat", score_confidence=Decimal("0.5")))
    assert len(sigs) == 0


def test_beat_rule_only_super_beat():
    """不是 super_beat 不触发。"""
    rule = EarningsBeatRule()
    sigs = rule.evaluate(make_ctx(score_verdict="beat", score_confidence=Decimal("0.9")))
    assert len(sigs) == 0


# ---------- meet ----------


def test_meet_rule_triggers_on_meet():
    rule = EarningsMeetRule()
    sigs = rule.evaluate(make_ctx(score_verdict="meet"))
    assert len(sigs) == 1
    assert sigs[0].severity == SignalSeverity.INFO


def test_meet_rule_triggers_on_beat():
    rule = EarningsMeetRule()
    sigs = rule.evaluate(make_ctx(score_verdict="beat"))
    assert len(sigs) == 1


def test_meet_rule_no_trigger_on_super_beat():
    """super_beat 由 beat rule 处理，meet rule 不应重复触发。"""
    rule = EarningsMeetRule()
    sigs = rule.evaluate(make_ctx(score_verdict="super_beat"))
    assert len(sigs) == 0


def test_meet_rule_no_trigger_on_miss():
    rule = EarningsMeetRule()
    sigs = rule.evaluate(make_ctx(score_verdict="miss"))
    assert len(sigs) == 0


# ---------- miss ----------


def test_miss_rule_triggers_on_deep_miss():
    rule = EarningsMissRule()
    sigs = rule.evaluate(make_ctx(score_verdict="deep_miss"))
    assert len(sigs) == 1
    assert sigs[0].severity == SignalSeverity.CRITICAL
    assert "低于" in sigs[0].detail


def test_miss_rule_no_trigger_on_miss():
    """普通 miss 由其他规则处理。"""
    rule = EarningsMissRule()
    sigs = rule.evaluate(make_ctx(score_verdict="miss"))
    assert len(sigs) == 0


# ---------- approaching ----------


def test_approaching_triggers_within_window():
    rule = EarningsApproachingRule()
    # today=7/13, disclosure=7/20 → T-7 → trigger
    sigs = rule.evaluate(make_ctx(today=date(2026, 7, 13), disclosure_date=date(2026, 7, 20)))
    assert len(sigs) == 1
    assert sigs[0].severity == SignalSeverity.WARNING
    assert "T-7" in sigs[0].detail


def test_approaching_triggers_with_high_growth():
    """predicted_high > 100% 触发。"""
    rule = EarningsApproachingRule()
    sigs = rule.evaluate(make_ctx(
        today=date(2026, 7, 15),
        disclosure_date=date(2026, 7, 20),
        predicted_high=Decimal("150"),
    ))
    assert len(sigs) == 1


def test_approaching_no_trigger_far_away():
    """T > 7 不触发。"""
    rule = EarningsApproachingRule()
    sigs = rule.evaluate(make_ctx(
        today=date(2026, 7, 1),
        disclosure_date=date(2026, 7, 20),  # T-19
    ))
    assert len(sigs) == 0


def test_approaching_no_trigger_low_growth():
    """predicted_high < 100% 不触发。"""
    rule = EarningsApproachingRule()
    sigs = rule.evaluate(make_ctx(
        today=date(2026, 7, 15),
        disclosure_date=date(2026, 7, 20),
        predicted_high=Decimal("50"),  # < 100
    ))
    assert len(sigs) == 0


def test_approaching_no_trigger_no_disclosure_date():
    """没披露日期不触发。"""
    rule = EarningsApproachingRule()
    sigs = rule.evaluate(make_ctx(disclosure_date=None))
    assert len(sigs) == 0


def test_approaching_fire_emoji_for_extreme():
    rule = EarningsApproachingRule()
    sigs = rule.evaluate(make_ctx(
        today=date(2026, 7, 15),
        disclosure_date=date(2026, 7, 20),
        predicted_high=Decimal("1000"),  # > 500 → 🔥
    ))
    assert "🔥" in sigs[0].detail


# ---------- factory ----------


def test_default_earnings_rules_returns_4():
    rules = default_earnings_rules()
    assert len(rules) == 4


def test_evaluate_all_runs_all_rules():
    """对 super_beat 应同时触发 beat rule。"""
    sigs = evaluate_all(make_ctx(score_verdict="super_beat", score_confidence=Decimal("0.9")))
    # 应该至少有 1 个 beat 信号
    beat_sigs = [s for s in sigs if s.rule_id == "earnings_beat"]
    assert len(beat_sigs) == 1
