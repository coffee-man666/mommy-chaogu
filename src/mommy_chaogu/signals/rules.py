"""内置告警规则集合。

每条规则：
- 一个独立类（继承 RuleBase）
- 默认 config 在类属性里
- evaluate() 纯函数：输入 Snapshot，输出 list[Signal]
- 失败不应影响其他规则（Alerter 层捕获异常）

新增规则流程：
1. 继承 RuleBase
2. 实现 _evaluate(snapshot, config) -> list[Signal]
3. 加到 default_rules() 列表
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mommy_chaogu.signals.types import Rule, RuleConfig, Signal, SignalSeverity

if TYPE_CHECKING:
    from mommy_chaogu.monitor import Snapshot


# ========== 规则基类 ==========


class RuleBase(ABC):
    """规则基类：默认 config + 包装 with_config。"""

    rule_id: str
    default_config: RuleConfig

    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or self.default_config

    @abstractmethod
    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]: ...

    def evaluate(self, snapshot: Snapshot) -> list[Signal]:
        if not self.config.enabled:
            return []
        try:
            return self._evaluate(snapshot, self.config)
        except Exception as e:
            import logging

            logging.getLogger(__name__).error(
                "rule %s evaluate failed: %s",
                self.rule_id,
                e,
            )
            return []

    def with_config(self, config: RuleConfig) -> RuleBase:
        return type(self)(config)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(rule_id={self.rule_id!r}, enabled={self.config.enabled})"


def _now() -> datetime:
    return datetime.now()


# ========== 价格类 ==========


class PriceChangeThresholdRule(RuleBase):
    """单日涨跌幅阈值。

    params:
      warning_threshold_pct: float = 3.0
      critical_threshold_pct: float = 5.0
    """

    rule_id = "price_change_threshold"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.WARNING,
        params={
            "warning_threshold_pct": 3.0,
            "critical_threshold_pct": 5.0,
        },
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        warn_pct = float(config.params.get("warning_threshold_pct", 3.0))
        crit_pct = float(config.params.get("critical_threshold_pct", 5.0))
        out: list[Signal] = []
        for row in snapshot.rows:
            pct = float(row.quote.change_pct)
            abs_pct = abs(pct)
            if abs_pct >= crit_pct:
                severity = SignalSeverity.CRITICAL
                thresh = crit_pct
            elif abs_pct >= warn_pct:
                severity = SignalSeverity.WARNING
                thresh = warn_pct
            else:
                continue
            direction = "涨" if pct > 0 else "跌"
            out.append(
                Signal(
                    timestamp=_now(),
                    code=row.quote.code,
                    name=row.quote.name,
                    rule_id=self.rule_id,
                    severity=severity,
                    title=f"{row.quote.name} {direction}幅 {pct:+.2f}% 突破 ±{thresh:.1f}%",
                    detail=(
                        f"当前价 {row.quote.price}, 涨跌 {row.quote.change:+.2f}, "
                        f"换手 {row.quote.turnover_rate or '—'}"
                    ),
                    metrics={
                        "price": float(row.quote.price),
                        "change_pct": pct,
                        "change": float(row.quote.change),
                    },
                    trigger_value=Decimal(str(pct)),
                    threshold_value=Decimal(str(thresh)),
                )
            )
        return out


class GapOpenRule(RuleBase):
    """跳空缺口：开盘相对昨收涨跌 > threshold。

    params:
      threshold_pct: float = 1.5
    """

    rule_id = "gap_open"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.WARNING,
        params={"threshold_pct": 1.5},
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        threshold = float(config.params.get("threshold_pct", 1.5))
        out: list[Signal] = []
        for row in snapshot.rows:
            q = row.quote
            if q.prev_close == 0:
                continue
            gap_pct = float((q.open - q.prev_close) / q.prev_close * 100)
            if abs(gap_pct) < threshold:
                continue
            direction = "高开" if gap_pct > 0 else "低开"
            out.append(
                Signal(
                    timestamp=_now(),
                    code=q.code,
                    name=q.name,
                    rule_id=self.rule_id,
                    severity=config.severity,
                    title=f"{q.name} 跳空{direction} {gap_pct:+.2f}%",
                    detail=(
                        f"开盘 {q.open}, 昨收 {q.prev_close}, 缺口 {q.open - q.prev_close:+.2f}"
                    ),
                    metrics={"open": float(q.open), "prev_close": float(q.prev_close)},
                    trigger_value=Decimal(str(round(gap_pct, 2))),
                    threshold_value=Decimal(str(threshold)),
                )
            )
        return out


# ========== 资金流类 ==========


class MainFlowThresholdRule(RuleBase):
    """主力净流入阈值。

    params:
      warning_threshold: Decimal = 5000万 (50_000_000)
      critical_threshold: Decimal = 2亿 (200_000_000)
      threshold_unit: str = "yuan" (默认元；可填 "wan"/"yi" 转换)
    """

    rule_id = "main_flow_threshold"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.WARNING,
        params={
            "warning_threshold_yuan": 50_000_000.0,  # 5 千万
            "critical_threshold_yuan": 200_000_000.0,  # 2 亿
        },
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        warn_yuan = float(config.params.get("warning_threshold_yuan", 5e7))
        crit_yuan = float(config.params.get("critical_threshold_yuan", 2e8))
        out: list[Signal] = []
        for row in snapshot.rows:
            flow = row.latest_flow
            if flow is None:
                continue
            amt = float(flow.main_net.amount)
            abs_amt = abs(amt)
            if abs_amt >= crit_yuan:
                severity = SignalSeverity.CRITICAL
                thresh = crit_yuan
            elif abs_amt >= warn_yuan:
                severity = SignalSeverity.WARNING
                thresh = warn_yuan
            else:
                continue
            direction = "流入" if amt > 0 else "流出"
            out.append(
                Signal(
                    timestamp=_now(),
                    code=row.quote.code,
                    name=row.quote.name,
                    rule_id=self.rule_id,
                    severity=severity,
                    title=(
                        f"{row.quote.name} 主力{direction} {float(amt) / 1e8:+.2f}亿 突破"
                        f" ±{float(thresh) / 1e8:.1f}亿"
                    ),
                    detail=(
                        f"主力 {flow.main_net.amount:+.0f}元, "
                        f"超大 {flow.super_large_net.amount:+.0f}, "
                        f"大 {flow.large_net.amount:+.0f}"
                    ),
                    metrics={"main_net": amt, "main_net_ratio": float(flow.main_net_ratio or 0)},
                    trigger_value=Decimal(str(amt)),
                    threshold_value=Decimal(str(thresh)),
                )
            )
        return out


class VolumeSurgeRule(RuleBase):
    """量比突变（量比 > 阈值）。仅看实时数据。"""

    rule_id = "volume_surge"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.WARNING,
        params={"volume_ratio_threshold": 2.0},
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        threshold = float(config.params.get("volume_ratio_threshold", 2.0))
        out: list[Signal] = []
        for row in snapshot.rows:
            vr = row.quote.volume_ratio
            if vr is None:
                continue
            v = float(vr)
            if v < threshold:
                continue
            out.append(
                Signal(
                    timestamp=_now(),
                    code=row.quote.code,
                    name=row.quote.name,
                    rule_id=self.rule_id,
                    severity=config.severity,
                    title=f"{row.quote.name} 量比 {v:.2f} 放量",
                    detail=f"量比阈值 {threshold}, 当前价 {row.quote.price}, 涨跌 {row.quote.change_pct:+.2f}%",
                    metrics={"volume_ratio": v, "price": float(row.quote.price)},
                    trigger_value=Decimal(str(v)),
                    threshold_value=Decimal(str(threshold)),
                )
            )
        return out


class TurnoverSurgeRule(RuleBase):
    """换手率突增（> 阈值）。"""

    rule_id = "turnover_surge"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.INFO,
        params={"turnover_threshold_pct": 5.0},
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        threshold = float(config.params.get("turnover_threshold_pct", 5.0))
        out: list[Signal] = []
        for row in snapshot.rows:
            tr = row.quote.turnover_rate
            if tr is None:
                continue
            v = float(tr)
            if v < threshold:
                continue
            out.append(
                Signal(
                    timestamp=_now(),
                    code=row.quote.code,
                    name=row.quote.name,
                    rule_id=self.rule_id,
                    severity=config.severity,
                    title=f"{row.quote.name} 换手 {v:.2f}% 活跃",
                    detail=f"换手阈值 {threshold}%, 价 {row.quote.price}, 涨跌 {row.quote.change_pct:+.2f}%",
                    metrics={"turnover_rate": v, "price": float(row.quote.price)},
                    trigger_value=Decimal(str(v)),
                    threshold_value=Decimal(str(threshold)),
                )
            )
        return out


# ========== 组合类 ==========


class PortfolioBreadthRule(RuleBase):
    """自选股组合涨跌面：>X% 同向触发。

    params:
      threshold_pct: float = 70.0 (百分比：70% 同向)
    """

    rule_id = "portfolio_breadth"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.INFO,
        params={"threshold_pct": 70.0},
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        if not snapshot.rows:
            return []
        threshold = float(config.params.get("threshold_pct", 70.0))
        n = len(snapshot.rows)
        n_up = sum(1 for r in snapshot.rows if r.quote.change_pct > 0)
        n_down = sum(1 for r in snapshot.rows if r.quote.change_pct < 0)
        pct_up = n_up / n * 100
        pct_down = n_down / n * 100

        if pct_up >= threshold:
            direction, count, pct = "普涨", n_up, pct_up
        elif pct_down >= threshold:
            direction, count, pct = "普跌", n_down, pct_down
        else:
            return []

        out: list[Signal] = []
        out.append(
            Signal(
                timestamp=_now(),
                code="PORTFOLIO",
                name=f"{n}只自选",
                rule_id=self.rule_id,
                severity=config.severity,
                title=f"自选股{direction} {count}/{n} = {pct:.0f}%",
                detail=(
                    f"涨 {n_up} 跌 {n_down} 平 {n - n_up - n_down}, "
                    f"主力合计 {float(snapshot.total_main_net) / 1e8:+.2f}亿"
                ),
                metrics={
                    "n_codes": n,
                    "n_up": n_up,
                    "n_down": n_down,
                    "pct_up": pct_up,
                    "pct_down": pct_down,
                },
            )
        )
        return out


class PortfolioMainFlowRule(RuleBase):
    """组合主力净流入合计超阈值。

    params:
      warning_threshold_yuan: float = 1亿
      critical_threshold_yuan: float = 5亿
    """

    rule_id = "portfolio_main_flow"
    default_config = RuleConfig(
        rule_id=rule_id,
        severity=SignalSeverity.WARNING,
        params={
            "warning_threshold_yuan": 100_000_000.0,  # 1 亿
            "critical_threshold_yuan": 500_000_000.0,  # 5 亿
        },
    )

    def _evaluate(self, snapshot: Snapshot, config: RuleConfig) -> list[Signal]:
        warn_yuan = float(config.params.get("warning_threshold_yuan", 1e8))
        crit_yuan = float(config.params.get("critical_threshold_yuan", 5e8))
        amt = float(snapshot.total_main_net)
        abs_amt = abs(amt)
        if abs_amt >= crit_yuan:
            severity = SignalSeverity.CRITICAL
            thresh = crit_yuan
        elif abs_amt >= warn_yuan:
            severity = SignalSeverity.WARNING
            thresh = warn_yuan
        else:
            return []
        direction = "流入" if amt > 0 else "流出"
        return [
            Signal(
                timestamp=_now(),
                code="PORTFOLIO",
                name=f"{snapshot.n_codes}只自选",
                rule_id=self.rule_id,
                severity=severity,
                title=f"组合主力{direction} {float(amt) / 1e8:+.2f}亿 突破 ±{float(thresh) / 1e8:.1f}亿",
                detail=(f"涨 {snapshot.n_up} 跌 {snapshot.n_down}, 总成交 {snapshot.n_codes} 只"),
                metrics={"total_main_net": amt, "n_codes": snapshot.n_codes},
                trigger_value=Decimal(str(amt)),
                threshold_value=Decimal(str(thresh)),
            )
        ]


# ========== 默认规则集合 ==========


def default_rules() -> list[Rule]:
    """返回所有内置规则的默认配置实例。"""
    return [
        PriceChangeThresholdRule(),
        GapOpenRule(),
        MainFlowThresholdRule(),
        VolumeSurgeRule(),
        TurnoverSurgeRule(),
        PortfolioBreadthRule(),
        PortfolioMainFlowRule(),
    ]


# 注册规则到 lookup 表（CLI 用）
RULES_REGISTRY: dict[str, type[Any]] = {
    cls.rule_id: cls
    for cls in [
        PriceChangeThresholdRule,
        GapOpenRule,
        MainFlowThresholdRule,
        VolumeSurgeRule,
        TurnoverSurgeRule,
        PortfolioBreadthRule,
        PortfolioMainFlowRule,
    ]
}
