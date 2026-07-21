"""Alerter 服务：规则调度 + 信号评估 + 信号日志。

职责：
1. 接收 Snapshot，对所有启用的规则跑 evaluate
2. 收集 Signal，按严重度排序
3. 输出控制台 + 追加 signals.log
4. 单条规则失败不影响整体（已在 RuleBase 里 try/except）

依赖倒置：
- 不依赖具体 Adapter，只接收 Snapshot
- 不依赖 CLI，纯函数式服务
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mommy_chaogu.signals.types import Rule, Signal, SignalSeverity

if TYPE_CHECKING:
    from mommy_chaogu.monitor import Snapshot
    from mommy_chaogu.signals.store import SignalStore

_log = logging.getLogger(__name__)


# 严重度排序权重（用于输出排序：critical 先显示）
_SEVERITY_WEIGHT: dict[SignalSeverity, int] = {
    SignalSeverity.CRITICAL: 0,
    SignalSeverity.WARNING: 1,
    SignalSeverity.INFO: 2,
}


class Alerter:
    """告警调度器。"""

    def __init__(
        self,
        rules: list[Rule],
        log_path: Path | None = None,
        signal_store: SignalStore | None = None,
    ) -> None:
        self.rules = list(rules)
        self.log_path = log_path
        self.signal_store = signal_store
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def default(
        cls,
        log_path: Path | None = None,
        signal_store: SignalStore | None = None,
    ) -> Alerter:
        """用默认规则集构造。"""
        from mommy_chaogu.signals.rules import default_rules

        return cls(default_rules(), log_path=log_path, signal_store=signal_store)

    def evaluate(self, snapshot: Snapshot) -> list[Signal]:
        """对快照跑所有规则，返回全部触发的信号（按严重度排序）。"""
        all_signals: list[Signal] = []
        for rule in self.rules:
            signals = rule.evaluate(snapshot)
            all_signals.extend(signals)
        all_signals.sort(
            key=lambda s: (
                _SEVERITY_WEIGHT[s.severity],
                s.code,
                s.rule_id,
            )
        )
        return all_signals

    # ---------- 输出 ----------

    def format_signals(self, signals: list[Signal]) -> str:
        """格式化为人类可读文本（控制台 + 通知用）。"""
        if not signals:
            return "（无信号触发）"
        lines: list[str] = []
        lines.append(f"🚨 触发信号 {len(signals)} 条：")
        lines.append("─" * 60)
        for s in signals:
            lines.append(s.format())
        return "\n".join(lines)

    def write_signals_log(self, signals: list[Signal]) -> None:
        """持久化信号（双写过渡：结构化库 + 旧文本日志兼容）。

        #10 结构化改造：优先写 signal_events 表（SignalStore）；
        若 log_path 仍配置则同时写旧文本日志，保证迁移期兼容。
        """
        if not signals:
            return
        # 结构化写入（主路径）
        if self.signal_store is not None:
            try:
                self.signal_store.insert(signals)
            except Exception as e:
                _log.warning("信号写入 SignalStore 失败，回退文本日志: %s", e)
        # 旧文本日志（兼容/过渡）
        if self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as f:
                for s in signals:
                    f.write(s.format_log() + "\n")
