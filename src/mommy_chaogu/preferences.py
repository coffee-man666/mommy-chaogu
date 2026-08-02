"""服务端统一用户偏好（交易风格 + 持有周期 + 通知偏好）。

四个消费方共用同一份配置：
- Today 排序 + 解释（web/routes/overview.py）
- Agent 强调（web/trading_style.py）
- 回测默认参数（``HOLD_PERIOD_TO_DAYS`` 派生 default_hold_days）
- 微信通知筛选（channels/notify.py）

本模块不依赖 web 层，channels 等后台模块可直接 import。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

type StyleT = Literal["conservative", "balanced", "aggressive"]
type HoldingPeriodT = Literal["short", "swing", "long"]
type DrawdownSensitivityT = Literal["low", "medium", "high"]
type NotifySeverityT = Literal["info", "warning", "critical"]


class WindowT(TypedDict):
    """提醒窗口，HH:MM 24 小时制（Asia/Shanghai），允许跨午夜。"""

    start: str
    end: str


DEFAULT_STYLE: StyleT = "balanced"
DEFAULT_HOLDING_PERIOD: HoldingPeriodT = "swing"
DEFAULT_DRAWDOWN_SENSITIVITY: DrawdownSensitivityT = "medium"
DEFAULT_NOTIFY_MIN_SEVERITY: NotifySeverityT = "warning"

#: 严重度排序（数值越大越严重）
SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}

#: 持有周期 → 回测默认持有天数（未来回测入口的单一真相源）
HOLD_PERIOD_TO_DAYS: dict[str, int] = {"short": 3, "swing": 5, "long": 20}

#: 未定制时的完整默认值（updated_at=None 表示从未定制）
DEFAULT_PREFERENCES: dict[str, Any] = {
    "style": DEFAULT_STYLE,
    "holding_period": DEFAULT_HOLDING_PERIOD,
    "drawdown_sensitivity": DEFAULT_DRAWDOWN_SENSITIVITY,
    "notify_min_severity": DEFAULT_NOTIFY_MIN_SEVERITY,
    "watched_rules": [],
    "reminder_windows": [],
    "updated_at": None,
}

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_WINDOW_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def default_preferences() -> dict[str, Any]:
    """返回一份默认偏好的深拷贝（调用方可安全修改）。"""
    return deepcopy(DEFAULT_PREFERENCES)


def default_hold_days(holding_period: str) -> int:
    """持有周期对应的回测默认持有天数，未知值回落到 swing。"""
    return HOLD_PERIOD_TO_DAYS.get(holding_period, HOLD_PERIOD_TO_DAYS["swing"])


def validate_reminder_windows(raw: object) -> list[WindowT]:
    """严格校验提醒窗口列表，非法输入抛 ValueError。

    每个窗口必须是 {"start": "HH:MM", "end": "HH:MM"}（24h），允许跨午夜
    （如 22:00-07:00）。start == end 视为全天。
    """
    if raw is None:
        return []
    if not isinstance(raw, list | tuple):
        raise ValueError("reminder_windows 必须是列表")
    windows: list[WindowT] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("提醒窗口必须是 {start, end} 对象")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, str) or not _WINDOW_RE.match(start):
            raise ValueError(f"提醒窗口 start 格式非法: {start!r}")
        if not isinstance(end, str) or not _WINDOW_RE.match(end):
            raise ValueError(f"提醒窗口 end 格式非法: {end!r}")
        windows.append({"start": start, "end": end})
    return windows


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _in_window(minute: int, window: WindowT) -> bool:
    start = _minutes(window["start"])
    end = _minutes(window["end"])
    if start == end:
        return True  # 起止相同视为全天
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end  # 跨午夜


def passes_notification_preferences(
    *,
    severity: str,
    rule_id: str,
    prefs: Mapping[str, Any],
    now: datetime,
) -> bool:
    """判断一条信号是否通过用户的通知偏好。

    三个条件全部满足才通过：
    - severity 等级 >= notify_min_severity
    - watched_rules 为空（关注全部）或包含 rule_id
    - reminder_windows 为空（任意时间）或当前 Asia/Shanghai 时间落在任一窗口内

    ``now`` 为 naive datetime 时按 UTC 处理。
    """
    rank = SEVERITY_RANK.get(severity, 0)
    min_rank = SEVERITY_RANK.get(str(prefs.get("notify_min_severity", "warning")), 1)
    if rank < min_rank:
        return False

    watched = prefs.get("watched_rules") or []
    if watched and rule_id not in watched:
        return False

    windows = prefs.get("reminder_windows") or []
    if windows:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        local = now.astimezone(_SHANGHAI)
        minute = local.hour * 60 + local.minute
        if not any(_in_window(minute, w) for w in windows):
            return False

    return True
