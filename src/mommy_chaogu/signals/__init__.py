"""signals 包：监控告警信号。

提供：
- Signal / SignalSeverity / RuleConfig：信号数据契约
- Rule：抽象规则接口（Protocol）
- Alerter：规则调度 + 信号评估
- rules：内置规则集合
"""

from mommy_chaogu.signals.alerter import Alerter
from mommy_chaogu.signals.rules import (
    GapOpenRule,
    MainFlowThresholdRule,
    PortfolioBreadthRule,
    PortfolioMainFlowRule,
    PriceChangeThresholdRule,
    TurnoverSurgeRule,
    VolumeSurgeRule,
    default_rules,
)
from mommy_chaogu.signals.store import SignalStore
from mommy_chaogu.signals.types import (
    Rule,
    RuleConfig,
    Signal,
    SignalSeverity,
)

__all__ = [
    "Alerter",
    "GapOpenRule",
    "MainFlowThresholdRule",
    "PortfolioBreadthRule",
    "PortfolioMainFlowRule",
    "PriceChangeThresholdRule",
    "Rule",
    "RuleConfig",
    "Signal",
    "SignalSeverity",
    "SignalStore",
    "TurnoverSurgeRule",
    "VolumeSurgeRule",
    "default_rules",
]
