"""去重器测试。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mommy_chaogu.push.deduper import JsonFileDeduper
from mommy_chaogu.signals.types import Signal, SignalSeverity


def make_signal(code: str = "600519", rule_id: str = "main_flow_threshold") -> Signal:
    return Signal(
        timestamp=datetime(2026, 6, 27, 9, 30, tzinfo=UTC),
        code=code,
        name="XD贵州茅",
        rule_id=rule_id,
        severity=SignalSeverity.CRITICAL,
        title="主力净流出",
        detail="净流出 -6.24 亿",
    )


def test_first_time_should_push(tmp_path: Path):
    deduper = JsonFileDeduper(tmp_path / "pushed.json")
    signal = make_signal()
    assert deduper.should_push(signal) is True
    deduper.mark_pushed(signal)
    assert deduper.should_push(signal) is False


def test_different_code_pushable(tmp_path: Path):
    deduper = JsonFileDeduper(tmp_path / "pushed.json")
    deduper.mark_pushed(make_signal(code="600519"))
    assert deduper.should_push(make_signal(code="000001")) is True


def test_different_rule_pushable(tmp_path: Path):
    deduper = JsonFileDeduper(tmp_path / "pushed.json")
    deduper.mark_pushed(make_signal(rule_id="rule_a"))
    assert deduper.should_push(make_signal(rule_id="rule_b")) is True


def test_persistence_across_instances(tmp_path: Path):
    db = tmp_path / "pushed.json"
    d1 = JsonFileDeduper(db)
    d1.mark_pushed(make_signal())
    # 新实例应该加载上次的记录
    d2 = JsonFileDeduper(db)
    assert d2.should_push(make_signal()) is False


def test_old_date_filtered_out(tmp_path: Path):
    """昨天的 key 不应算今天的去重。"""
    db = tmp_path / "pushed.json"
    # 手动写一个昨天的文件
    db.write_text(
        json.dumps(
            {
                "date": "2026-06-26",  # 昨天
                "pushed_keys": ["600519|main_flow_threshold|2026-06-26"],
            }
        ),
        encoding="utf-8",
    )
    deduper = JsonFileDeduper(db)
    # 今天的同名信号应该可以推
    assert deduper.should_push(make_signal()) is True


def test_corrupted_file_ignored(tmp_path: Path):
    db = tmp_path / "pushed.json"
    db.write_text("not json {{{ broken", encoding="utf-8")
    deduper = JsonFileDeduper(db)  # 不应抛
    assert deduper.should_push(make_signal()) is True


def test_missing_file_works(tmp_path: Path):
    deduper = JsonFileDeduper(tmp_path / "pushed.json")  # 文件不存在
    assert deduper.should_push(make_signal()) is True


def test_clear(tmp_path: Path):
    db = tmp_path / "pushed.json"
    deduper = JsonFileDeduper(db)
    deduper.mark_pushed(make_signal())
    assert deduper.count() == 1
    deduper.clear()
    assert deduper.count() == 0
    assert not db.exists()


def test_save_creates_parent_dirs(tmp_path: Path):
    db = tmp_path / "deep" / "nested" / "pushed.json"
    deduper = JsonFileDeduper(db)
    deduper.mark_pushed(make_signal())
    assert db.exists()


# ---------- 跨天翻转（常驻进程，阶段五评审修复） ----------


class _FakeDate(date):
    """可翻转日期的 date 替身：monkeypatch 到 deduper 模块的 date 名字上。"""

    _day = "2026-10-01"

    @classmethod
    def today(cls) -> date:
        y, m, d = (int(part) for part in cls._day.split("-"))
        return date(y, m, d)


def test_day_rollover_same_instance_allows_repush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """常驻进程跨天：昨天推过的 code+rule 次日可再次推送（当天仍限一次）。

    回归背景：web lifespan 只构造一次 JsonFileDeduper，_today 冻结在构造
    时刻时，常驻 mommy-web（launchd KeepAlive / systemd Restart）跨天后
    同一 code+rule 被永久抑制直到进程重启——计划验收「次日可再次触发」
    在常驻部署下不成立。
    """
    monkeypatch.setattr("mommy_chaogu.push.deduper.date", _FakeDate)
    deduper = JsonFileDeduper(tmp_path / "pushed.json")
    signal = make_signal()

    assert deduper.should_push(signal) is True
    deduper.mark_pushed(signal)
    assert deduper.should_push(signal) is False  # 当天限流

    _FakeDate._day = "2026-10-02"  # 次日，同一常驻实例
    assert deduper.should_push(signal) is True, "次日应可再次触发"
    deduper.mark_pushed(signal)
    assert deduper.should_push(signal) is False  # 次日也只推一次


def test_day_rollover_reloads_todays_keys_at_flip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """翻转时重读文件：翻转前其它进程（共用 pushed.json）写入的当天 key 被拾取。"""
    monkeypatch.setattr("mommy_chaogu.push.deduper.date", _FakeDate)
    db = tmp_path / "pushed.json"
    resident = JsonFileDeduper(db)
    resident.mark_pushed(make_signal())

    _FakeDate._day = "2026-10-02"
    sibling = JsonFileDeduper(db)  # 同日另一进程（如 cron snapshot）先推
    sibling.mark_pushed(make_signal())

    # 常驻实例首次跨天访问：翻转 + 重加载 → 看到 sibling 的当日 key
    assert resident.should_push(make_signal()) is False
