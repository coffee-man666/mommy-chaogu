"""信号数据契约 + Rule 协议。

设计原则：
- Signal 是不可变 dataclass（frozen + slots），便于哈希/缓存
- Rule 是 Protocol（runtime_checkable），方便 mock 测试
- RuleConfig 把规则参数和元数据集中管理
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mommy_chaogu.monitor import Snapshot


class SignalSeverity(StrEnum):
    """告警严重程度（妈妈易懂的三档）。"""
    INFO = "info"          # 日常观察（组合涨跌幅分布等）
    WARNING = "warning"    # 需要关注
    CRITICAL = "critical"  # 建议行动


# 严重程度对应的 emoji（输出时用）
SEVERITY_EMOJI: dict[SignalSeverity, str] = {
    SignalSeverity.INFO: "📊",
    SignalSeverity.WARNING: "⚠️ ",
    SignalSeverity.CRITICAL: "🔴",
}

SEVERITY_LABEL: dict[SignalSeverity, str] = {
    SignalSeverity.INFO: "INFO",
    SignalSeverity.WARNING: "WARN",
    SignalSeverity.CRITICAL: "CRIT",
}


@dataclass(frozen=True, slots=True)
class Signal:
    """一条告警信号。

    一条 Signal 对应一个标的在一个时间点的某条规则触发结果。
    """
    timestamp: datetime
    code: str
    name: str
    rule_id: str
    severity: SignalSeverity
    title: str          # 短标题（适合控制台 + 通知）："茅台涨超 5%"
    detail: str         # 详情（适合日志）：当前价、涨跌额、量能等
    metrics: dict[str, Any] = field(default_factory=dict)
    # 触发该信号的具体阈值（用于审计 / debug）
    trigger_value: Decimal | None = None
    threshold_value: Decimal | None = None

    def format(self) -> str:
        """控制台格式。"""
        emoji = SEVERITY_EMOJI[self.severity]
        label = SEVERITY_LABEL[self.severity]
        return f"{emoji} {label:<5} {self.title}  | {self.detail}"

    def format_log(self) -> str:
        """日志单行紧凑格式。"""
        emoji = SEVERITY_EMOJI[self.severity]
        label = SEVERITY_LABEL[self.severity]
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{ts}] {emoji} {label:<5} {self.code} {self.name} {self.title} | {self.detail}"


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """单条规则的配置。

    - enabled: 全局开关
    - severity: 触发时的默认严重度（规则可在 evaluate 时升级）
    - params: 规则特定的参数字典（threshold、window、...）
    """
    rule_id: str
    enabled: bool = True
    severity: SignalSeverity = SignalSeverity.WARNING
    params: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Rule(Protocol):
    """告警规则接口契约。"""

    rule_id: str
    default_config: RuleConfig
    config: RuleConfig  # 当前生效配置

    def evaluate(self, snapshot: Snapshot) -> list[Signal]:
        """对一次快照评估，返回触发的信号列表（无触发返回空）。"""
        ...

    def with_config(self, config: RuleConfig) -> Rule:
        """返回用新 config 包装的规则实例（不变性）。"""
        ...
