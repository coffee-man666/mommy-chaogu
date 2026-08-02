"""preferences 领域模块单测。

覆盖：
- 默认值与 HOLD_PERIOD_TO_DAYS 派生映射（回测默认参数的单一真相源）
- validate_reminder_windows 严格 HH:MM 校验
- passes_notification_preferences：严重度下限 / 关注规则 / 提醒时段（含跨午夜）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from mommy_chaogu.preferences import (
    DEFAULT_PREFERENCES,
    HOLD_PERIOD_TO_DAYS,
    default_hold_days,
    default_preferences,
    passes_notification_preferences,
    validate_reminder_windows,
)


def _prefs(**overrides: Any) -> dict[str, Any]:
    prefs = default_preferences()
    prefs.update(overrides)
    return prefs


class TestDefaults:
    def test_default_values(self) -> None:
        assert DEFAULT_PREFERENCES["style"] == "balanced"
        assert DEFAULT_PREFERENCES["holding_period"] == "swing"
        assert DEFAULT_PREFERENCES["drawdown_sensitivity"] == "medium"
        assert DEFAULT_PREFERENCES["notify_min_severity"] == "warning"
        assert DEFAULT_PREFERENCES["watched_rules"] == []
        assert DEFAULT_PREFERENCES["reminder_windows"] == []
        assert DEFAULT_PREFERENCES["updated_at"] is None

    def test_default_preferences_returns_independent_copy(self) -> None:
        prefs = default_preferences()
        prefs["watched_rules"].append("x")
        assert DEFAULT_PREFERENCES["watched_rules"] == []

    def test_hold_period_to_days_mapping(self) -> None:
        """回测默认持有天数映射：short→3, swing→5, long→20。"""
        assert HOLD_PERIOD_TO_DAYS == {"short": 3, "swing": 5, "long": 20}
        assert default_hold_days("short") == 3
        assert default_hold_days("swing") == 5
        assert default_hold_days("long") == 20

    def test_default_hold_days_unknown_falls_back_to_swing(self) -> None:
        assert default_hold_days("unknown") == 5


class TestValidateReminderWindows:
    def test_none_and_empty(self) -> None:
        assert validate_reminder_windows(None) == []
        assert validate_reminder_windows([]) == []

    def test_valid_windows(self) -> None:
        windows = validate_reminder_windows(
            [{"start": "09:30", "end": "15:00"}, {"start": "22:00", "end": "07:00"}]
        )
        assert windows == [
            {"start": "09:30", "end": "15:00"},
            {"start": "22:00", "end": "07:00"},
        ]

    @pytest.mark.parametrize(
        "raw",
        [
            [{"start": "9:30", "end": "15:00"}],  # 必须两位小时
            [{"start": "24:00", "end": "15:00"}],  # 小时越界
            [{"start": "09:60", "end": "15:00"}],  # 分钟越界
            [{"start": "ab:cd", "end": "15:00"}],
            [{"start": "09:30"}],  # 缺 end
            [{"end": "15:00"}],  # 缺 start
            ["09:30-15:00"],  # 不是对象
            "09:30-15:00",  # 不是列表
            [{"start": "09:30:00", "end": "15:00"}],  # 不允许秒
        ],
    )
    def test_invalid_windows_raise(self, raw: object) -> None:
        with pytest.raises(ValueError):
            validate_reminder_windows(raw)


class TestPassesNotificationPreferences:
    # 2026-08-03 是周一；用固定 UTC 时间换算 Asia/Shanghai（UTC+8）
    _SHANGHAI_10AM = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)  # 上海 10:00
    _SHANGHAI_8PM = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)  # 上海 20:00
    _SHANGHAI_2AM = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)  # 上海 次日 02:00

    def test_default_prefs_pass_warning_and_critical(self) -> None:
        prefs = _prefs()
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is True
        )
        assert (
            passes_notification_preferences(
                severity="critical", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is True
        )

    def test_severity_floor_blocks_info_by_default(self) -> None:
        prefs = _prefs()
        assert (
            passes_notification_preferences(
                severity="info", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is False
        )

    def test_severity_floor_critical_only(self) -> None:
        prefs = _prefs(notify_min_severity="critical")
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is False
        )
        assert (
            passes_notification_preferences(
                severity="critical", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is True
        )

    def test_watched_rules_allowlist(self) -> None:
        prefs = _prefs(watched_rules=["rule_a"])
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="rule_a", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is True
        )
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="rule_b", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is False
        )

    def test_reminder_window_inside(self) -> None:
        prefs = _prefs(reminder_windows=[{"start": "09:30", "end": "15:00"}])
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is True
        )

    def test_reminder_window_outside(self) -> None:
        prefs = _prefs(reminder_windows=[{"start": "09:30", "end": "15:00"}])
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_8PM
            )
            is False
        )

    def test_midnight_wrapping_window(self) -> None:
        prefs = _prefs(reminder_windows=[{"start": "22:00", "end": "07:00"}])
        # 上海 02:00 在窗口内
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_2AM
            )
            is True
        )
        # 上海 10:00 不在窗口内
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_10AM
            )
            is False
        )

    def test_multiple_windows_any_match(self) -> None:
        prefs = _prefs(
            reminder_windows=[
                {"start": "09:30", "end": "11:30"},
                {"start": "19:00", "end": "21:00"},
            ]
        )
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_8PM
            )
            is True
        )

    def test_naive_now_treated_as_utc(self) -> None:
        prefs = _prefs(reminder_windows=[{"start": "09:30", "end": "15:00"}])
        naive_utc_2am = datetime(2026, 8, 3, 2, 0)  # 上海 10:00
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=naive_utc_2am
            )
            is True
        )

    def test_equal_start_end_means_all_day(self) -> None:
        prefs = _prefs(reminder_windows=[{"start": "09:30", "end": "09:30"}])
        assert (
            passes_notification_preferences(
                severity="warning", rule_id="r1", prefs=prefs, now=self._SHANGHAI_8PM
            )
            is True
        )
