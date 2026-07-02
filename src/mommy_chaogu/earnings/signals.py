"""earnings 模块 — 信号规则。

4 条规则（详见 docs/EARNINGS-HANDBOOK.md）：
1. earnings_beat：actual > predicted_high → BUY
2. earnings_meet：在预测区间内 → HOLD
3. earnings_miss：actual < predicted_low → SELL
4. earnings_approaching：T-7 披露日临近 + 高弹性 → ALERT

设计：与 signals/rules.py 类似，但 evaluate() 输入是 EarningsContext（不是 Snapshot）。
所以这里定义一个独立的 EarningsRule Protocol，不混入主 signals/ 协议的 Snapshot 类型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Protocol, runtime_checkable

from mommy_chaogu.signals.types import RuleConfig, Signal, SignalSeverity


@dataclass(slots=True)
class EarningsContext:
    """信号规则的输入上下文。"""

    code: str
    name: str
    period: str
    disclosure_date: date | None   # None = 不知道日期
    today: date
    predicted_high: Decimal | None
    score_verdict: str | None      # SUPER_BEAT/BEAT/MEET/MISS/DEEP_MISS/UNKNOWN
    score_confidence: Decimal | None

    @property
    def now(self) -> datetime:
        """today 转 datetime（Signal 需要 datetime 类型）。"""
        return datetime.combine(self.today, time())


@runtime_checkable
class EarningsRule(Protocol):
    """earnings 信号规则的 Protocol。

    与 mommy_chaogu.signals.types.Rule 不同：这里 evaluate() 接受 EarningsContext，
    而不是 Snapshot（行情快照）。
    """

    name: str
    config: RuleConfig

    def evaluate(self, ctx: EarningsContext) -> list[Signal]: ...


# ---------- 规则 1: earnings_beat ----------


@dataclass(slots=True)
class EarningsBeatRule:
    """actual > predicted_high → BUY 信号。"""

    name: str = "earnings_beat"
    config: RuleConfig = field(
        default_factory=lambda: RuleConfig(
            rule_id="earnings_beat",
            severity=SignalSeverity.CRITICAL,
            params={},
        )
    )

    def evaluate(self, ctx: EarningsContext) -> list[Signal]:
        if ctx.score_verdict != "super_beat":
            return []
        if ctx.score_confidence is None or ctx.score_confidence < Decimal("0.7"):
            return []

        msg = (
            f"🎯 {ctx.name}({ctx.code}) 超预期！"
            f"预测上限 {ctx.predicted_high}%，"
            f"置信度 {ctx.score_confidence:.0%}"
        )
        return [
            Signal(
                timestamp=ctx.now,
                code=ctx.code,
                name=ctx.name,
                rule_id=self.name,
                severity=self.config.severity,
                title=f"{ctx.name} 超预期",
                detail=msg,
                metrics={
                    "predicted_high": str(ctx.predicted_high),
                    "confidence": str(ctx.score_confidence),
                    "verdict": ctx.score_verdict or "",
                },
                trigger_value=ctx.score_confidence,
                threshold_value=ctx.predicted_high,
            )
        ]


# ---------- 规则 2: earnings_meet ----------


@dataclass(slots=True)
class EarningsMeetRule:
    """actual 在预测区间内 → HOLD（中性信号）。"""

    name: str = "earnings_meet"
    config: RuleConfig = field(
        default_factory=lambda: RuleConfig(
            rule_id="earnings_meet",
            severity=SignalSeverity.INFO,
            params={},
        )
    )

    def evaluate(self, ctx: EarningsContext) -> list[Signal]:
        if ctx.score_verdict not in ("beat", "meet"):
            return []
        msg = (
            f"📊 {ctx.name}({ctx.code}) 符合预期 "
            f"({ctx.score_verdict})"
        )
        return [
            Signal(
                timestamp=ctx.now,
                code=ctx.code,
                name=ctx.name,
                rule_id=self.name,
                severity=self.config.severity,
                title=f"{ctx.name} 符合预期",
                detail=msg,
                metrics={"verdict": ctx.score_verdict or ""},
            )
        ]


# ---------- 规则 3: earnings_miss ----------


@dataclass(slots=True)
class EarningsMissRule:
    """actual < predicted_low → SELL 信号。"""

    name: str = "earnings_miss"
    config: RuleConfig = field(
        default_factory=lambda: RuleConfig(
            rule_id="earnings_miss",
            severity=SignalSeverity.CRITICAL,
            params={},
        )
    )

    def evaluate(self, ctx: EarningsContext) -> list[Signal]:
        if ctx.score_verdict != "deep_miss":
            return []
        msg = (
            f"⚠️ {ctx.name}({ctx.code}) 大幅低于预期！"
            f"实际增速低于预测下限"
        )
        return [
            Signal(
                timestamp=ctx.now,
                code=ctx.code,
                name=ctx.name,
                rule_id=self.name,
                severity=self.config.severity,
                title=f"{ctx.name} 大幅低于预期",
                detail=msg,
                metrics={"verdict": ctx.score_verdict or ""},
            )
        ]


# ---------- 规则 4: earnings_approaching ----------


@dataclass(slots=True)
class EarningsApproachingRule:
    """T-7 内 + predicted_high > 100% → ALERT（强催化将至）。"""

    name: str = "earnings_approaching"
    config: RuleConfig = field(
        default_factory=lambda: RuleConfig(
            rule_id="earnings_approaching",
            severity=SignalSeverity.WARNING,
            params={"threshold_high": 100.0, "days_before": 7},
        )
    )

    def evaluate(self, ctx: EarningsContext) -> list[Signal]:
        if ctx.disclosure_date is None or ctx.predicted_high is None:
            return []
        threshold_high = Decimal(str(self.config.params.get("threshold_high", 100)))
        days_before = int(self.config.params.get("days_before", 7))

        days_to = (ctx.disclosure_date - ctx.today).days
        if not (0 < days_to <= days_before):
            return []
        if ctx.predicted_high < threshold_high:
            return []

        emoji = "🔥" if ctx.predicted_high >= 500 else "⚡" if ctx.predicted_high >= 200 else "📈"
        msg = (
            f"{emoji} {ctx.name}({ctx.code}) {ctx.period} 业绩披露临近 "
            f"(T-{days_to})，预测上限 +{ctx.predicted_high}%"
        )
        return [
            Signal(
                timestamp=ctx.now,
                code=ctx.code,
                name=ctx.name,
                rule_id=self.name,
                severity=self.config.severity,
                title=f"{ctx.name} 业绩披露临近 T-{days_to}",
                detail=msg,
                metrics={
                    "days_to_disclosure": days_to,
                    "predicted_high": str(ctx.predicted_high),
                },
                trigger_value=Decimal(days_to),
                threshold_value=Decimal(days_before),
            )
        ]


# ---------- 工厂函数 ----------


def default_earnings_rules() -> list[EarningsRule]:
    """返回所有 4 条规则的列表。"""
    return [
        EarningsBeatRule(),
        EarningsMeetRule(),
        EarningsMissRule(),
        EarningsApproachingRule(),
    ]


def evaluate_all(ctx: EarningsContext, rules: list[EarningsRule] | None = None) -> list[Signal]:
    """对给定 ctx 跑全部规则，返回触发的 signal 列表。"""
    if rules is None:
        rules = default_earnings_rules()
    signals: list[Signal] = []
    for rule in rules:
        signals.extend(rule.evaluate(ctx))
    return signals
