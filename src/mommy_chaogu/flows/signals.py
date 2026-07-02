"""资金流 ratio-based 信号规则。

为什么 ratio 而不是绝对值：
- 同样 5000万 净流入对茅台 (1.5万亿) 是 0.003%（噪声）
- 对卓胜微 (450亿) 是 0.11%（异动）
- 用 流通市值 当分母，消除大票小票偏差

ratio 含义：
- ratio = main_net / circulating_market_cap
- 例：main_net = +5000万, float_mcap = 1000亿 → ratio = 0.0005 = 5bp
- 「5min 内 ratio 上升 5bp」= 主力在 5 分钟内吃进了流通市值 0.05% 的筹码
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------- 严重度 ----------


class Severity(StrEnum):
    """信号严重度。"""

    INFO = "INFO"
    WARN = "WARN"
    CRIT = "CRIT"


# ---------- 信号 + 规则 ----------


@dataclass(frozen=True, slots=True)
class FlowSignal:
    """一条资金流信号。"""

    rule_id: str
    code: str
    name: str
    severity: Severity
    metric: str  # 触发指标的描述
    ratio: Decimal  # 当前 ratio (绝对值)
    delta_ratio: Decimal | None  # 相对上轮的变化（5min delta 类才有）
    main_net: Decimal  # 原始主力净（元）
    float_market_cap: Decimal  # 流通市值（元）
    note: str
    triggered_at: datetime = field(default_factory=_utcnow)

    def format(self) -> str:
        arrow = "↑" if self.delta_ratio is None or self.delta_ratio > 0 else "↓"
        delta_str = ""
        if self.delta_ratio is not None:
            # 用 bp 显示更直观
            bp = float(self.delta_ratio) * 10000
            delta_str = f"  Δ {arrow}{abs(bp):.1f}bp"
        ratio_bp = float(self.ratio) * 10000
        return (
            f"[{self.severity.value}] {self.code} {self.name}  "
            f"ratio {ratio_bp:+.1f}bp{delta_str}  "
            f"主力 {self.main_net / Decimal('100000000'):+.2f}亿  "
            f"流通 {self.float_market_cap / Decimal('100000000'):.0f}亿  "
            f"({self.metric})"
        )


@dataclass(frozen=True, slots=True)
class FlowRule:
    """一条 ratio-based 资金流规则。"""

    rule_id: str
    severity: Severity
    metric: Literal["delta_5min", "cumulative_daily"]
    direction: Literal["in", "out"]
    threshold_bp: Decimal  # 阈值（bp），5bp = 0.05%
    description: str

    def matches(
        self,
        *,
        ratio: Decimal,
        delta_ratio: Decimal | None,
        main_net: Decimal,
        float_market_cap: Decimal,
    ) -> bool:
        """判断当前数据是否触发本规则。"""
        threshold = self.threshold_bp / Decimal("10000")
        if self.metric == "delta_5min":
            if delta_ratio is None:
                return False
            if self.direction == "in":
                return delta_ratio > threshold and main_net > 0
            # out
            return -delta_ratio > threshold and main_net < 0
        # cumulative_daily：只比 ratio 绝对值
        if self.direction == "in":
            return ratio > threshold and main_net > 0
        return -ratio > threshold and main_net < 0


# ---------- 默认规则集 ----------


def default_rules() -> list[FlowRule]:
    """5 条默认规则（与 INTRO 表格一致）。"""
    return [
        FlowRule(
            rule_id="flow_in_spike",
            severity=Severity.WARN,
            metric="delta_5min",
            direction="in",
            threshold_bp=Decimal("5"),
            description="5min 内主力净流入 ratio 上升 > 5bp",
        ),
        FlowRule(
            rule_id="flow_in_surge",
            severity=Severity.CRIT,
            metric="delta_5min",
            direction="in",
            threshold_bp=Decimal("10"),
            description="5min 内主力净流入 ratio 上升 > 10bp",
        ),
        FlowRule(
            rule_id="flow_out_spike",
            severity=Severity.WARN,
            metric="delta_5min",
            direction="out",
            threshold_bp=Decimal("5"),
            description="5min 内主力净流出 ratio 下降 > 5bp",
        ),
        FlowRule(
            rule_id="flow_out_surge",
            severity=Severity.CRIT,
            metric="delta_5min",
            direction="out",
            threshold_bp=Decimal("10"),
            description="5min 内主力净流出 ratio 下降 > 10bp",
        ),
    ]


# ---------- 评估 ----------


@dataclass(frozen=True, slots=True)
class StockSnapshot:
    """单只股票在一轮的快照（用于 ratio 计算）。"""

    code: str
    name: str
    main_net: Decimal  # 主力净流入（元）
    float_market_cap: Decimal  # 流通市值（元）

    @property
    def ratio(self) -> Decimal:
        """主力净 / 流通市值。"""
        if self.float_market_cap == 0:
            return Decimal("0")
        return self.main_net / self.float_market_cap


def evaluate(
    current: list[StockSnapshot],
    previous: dict[str, Decimal] | None,
    rules: list[FlowRule] | None = None,
) -> list[FlowSignal]:
    """对当前快照评估所有规则，返回触发的信号。

    Args:
        current: 本轮所有股票快照
        previous: {code: 上轮 ratio}，None 表示首轮（delta 规则不会触发）
        rules: 规则集，None = default_rules()
    """
    rules = rules or default_rules()
    prev = previous or {}
    signals: list[FlowSignal] = []
    for s in current:
        if s.float_market_cap == 0:
            continue
        delta_ratio = (s.ratio - prev[s.code]) if s.code in prev else None
        for rule in rules:
            if not rule.matches(
                ratio=s.ratio,
                delta_ratio=delta_ratio,
                main_net=s.main_net,
                float_market_cap=s.float_market_cap,
            ):
                continue
            metric_label = "5min delta" if rule.metric == "delta_5min" else "当日累计"
            direction_label = "净流入" if rule.direction == "in" else "净流出"
            signals.append(
                FlowSignal(
                    rule_id=rule.rule_id,
                    code=s.code,
                    name=s.name,
                    severity=rule.severity,
                    metric=f"{metric_label}·{direction_label}>{rule.threshold_bp}bp",
                    ratio=s.ratio,
                    delta_ratio=delta_ratio,
                    main_net=s.main_net,
                    float_market_cap=s.float_market_cap,
                    note=rule.description,
                )
            )
    return signals
