"""SignalNotifier 测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from mommy_chaogu.push.base import SignalNotifier
from mommy_chaogu.push.deduper import JsonFileDeduper
from mommy_chaogu.signals.types import Signal, SignalSeverity


def make_signal(
    severity: SignalSeverity = SignalSeverity.CRITICAL,
    code: str = "600519",
    rule_id: str = "main_flow_threshold",
) -> Signal:
    return Signal(
        timestamp=datetime(2026, 6, 27, 9, 30, tzinfo=UTC),
        code=code,
        name="XD贵州茅",
        rule_id=rule_id,
        severity=severity,
        title="主力净流出",
        detail="净流出",
    )


def make_notifier(tmp_path: Path, threshold: SignalSeverity = SignalSeverity.WARNING):
    pusher = MagicMock()
    pusher.push.return_value = True
    deduper = JsonFileDeduper(tmp_path / "pushed.json")
    return (
        SignalNotifier(pusher=pusher, deduper=deduper, severity_threshold=threshold),
        pusher,
        deduper,
    )


# ---------- 阈值过滤 ----------


def test_info_below_threshold_not_pushed(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path, threshold=SignalSeverity.WARNING)
    info_signal = make_signal(severity=SignalSeverity.INFO)
    assert notifier.notify_one(info_signal) is False
    pusher.push.assert_not_called()


def test_warning_meets_threshold(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path, threshold=SignalSeverity.WARNING)
    assert notifier.notify_one(make_signal(severity=SignalSeverity.WARNING)) is True
    pusher.push.assert_called_once()


def test_critical_meets_threshold(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path, threshold=SignalSeverity.WARNING)
    assert notifier.notify_one(make_signal(severity=SignalSeverity.CRITICAL)) is True
    pusher.push.assert_called_once()


def test_info_meets_threshold_when_info_allowed(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path, threshold=SignalSeverity.INFO)
    assert notifier.notify_one(make_signal(severity=SignalSeverity.INFO)) is True
    pusher.push.assert_called_once()


# ---------- 去重 ----------


def test_dedup_skips_already_pushed(tmp_path: Path):
    notifier, pusher, deduper = make_notifier(tmp_path)
    signal = make_signal()
    # 标记已推
    deduper.mark_pushed(signal)
    assert notifier.notify_one(signal) is False
    pusher.push.assert_not_called()


# ---------- 推送失败 ----------


def test_pusher_failure_does_not_mark_pushed(tmp_path: Path):
    notifier, pusher, deduper = make_notifier(tmp_path)
    pusher.push.return_value = False
    assert notifier.notify_one(make_signal()) is False
    # 失败不应该标记，下一轮可以重试
    assert deduper.should_push(make_signal()) is True


def test_pusher_exception_handled(tmp_path: Path):
    notifier, pusher, deduper = make_notifier(tmp_path)
    pusher.push.side_effect = RuntimeError("oops")
    # 不应抛
    assert notifier.notify_one(make_signal()) is False
    # 没标记
    assert deduper.should_push(make_signal()) is True


# ---------- 批量 ----------


def test_notify_batch(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path)
    signals = [
        make_signal(code="600519", rule_id="r1"),
        make_signal(code="000001", rule_id="r1"),
        make_signal(code="600036", rule_id="r1"),
    ]
    pushed = notifier.notify_batch(signals)
    assert len(pushed) == 3
    assert pusher.push.call_count == 3


def test_notify_batch_skips_info(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path, threshold=SignalSeverity.WARNING)
    signals = [
        make_signal(severity=SignalSeverity.INFO, code="600519"),
        make_signal(severity=SignalSeverity.CRITICAL, code="000001"),
    ]
    pushed = notifier.notify_batch(signals)
    assert len(pushed) == 1
    assert pusher.push.call_count == 1


def test_notify_batch_dedup(tmp_path: Path):
    notifier, pusher, _ = make_notifier(tmp_path)
    same_signal = make_signal()
    signals = [same_signal, same_signal, same_signal]
    pushed = notifier.notify_batch(signals)
    assert len(pushed) == 1
    assert pusher.push.call_count == 1
