"""推送抽象层。

Pusher: 单条推送接口（任意实现都可以：Server酱 / 钉钉 / Telegram / Bark）
Deduper: 防重复推送（一码一规一天）
SignalNotifier: 顶层封装 = 严重度过滤 + 去重 + 推送
"""

from __future__ import annotations

import logging
from typing import Protocol

from mommy_chaogu.signals.types import Signal, SignalSeverity

_log = logging.getLogger(__name__)


class Pusher(Protocol):
    """推送接口。"""

    def push(self, signal: Signal) -> bool:
        """推送一条信号。返回 True 表示成功。"""
        ...


class Deduper(Protocol):
    """去重接口。"""

    def should_push(self, signal: Signal) -> bool:
        """是否应该推送（未推过）？"""
        ...

    def mark_pushed(self, signal: Signal) -> None:
        """标记已推送（持久化）。"""
        ...


class SignalNotifier:
    """顶层推送器：过滤 + 去重 + 推送。

    默认只推 warning / critical（info 太多了）。可以配置。

    用法：
        notifier = SignalNotifier(pusher, deduper)
        for signal in signals:
            if notifier.notify_one(signal):
                log.info("推了: %s", signal.code)
    """

    def __init__(
        self,
        pusher: Pusher,
        deduper: Deduper,
        severity_threshold: SignalSeverity = SignalSeverity.WARNING,
        web_base_url: str = "",
    ) -> None:
        self.pusher = pusher
        self.deduper = deduper
        self.severity_threshold = severity_threshold
        self.web_base_url = web_base_url.rstrip("/")

    def _meets_threshold(self, signal: Signal) -> bool:
        """严重度是否达到推送阈值？

        severity 是有序的（info < warning < critical）。
        """
        order = {
            SignalSeverity.INFO: 0,
            SignalSeverity.WARNING: 1,
            SignalSeverity.CRITICAL: 2,
        }
        return order[signal.severity] >= order[self.severity_threshold]

    def notify_one(self, signal: Signal) -> bool:
        """推送单条信号。返回是否成功推送（含去重 + 阈值过滤）。"""
        if not self._meets_threshold(signal):
            return False
        if not self.deduper.should_push(signal):
            _log.debug("去重跳过: %s %s", signal.code, signal.rule_id)
            return False
        try:
            ok = self.pusher.push(signal)
        except Exception:
            _log.exception("推送异常: %s %s", signal.code, signal.rule_id)
            return False
        if ok:
            self.deduper.mark_pushed(signal)
            _log.info(
                "推送成功 [%s] %s %s: %s",
                signal.severity.value.upper(),
                signal.code,
                signal.name,
                signal.rule_id,
            )
        else:
            _log.warning(
                "推送失败 [%s] %s %s: %s",
                signal.severity.value.upper(),
                signal.code,
                signal.name,
                signal.rule_id,
            )
        return ok

    def notify_batch(self, signals: list[Signal]) -> list[Signal]:
        """批量推送。返回实际推了的信号列表。"""
        pushed: list[Signal] = []
        for signal in signals:
            if self.notify_one(signal):
                pushed.append(signal)
        return pushed
