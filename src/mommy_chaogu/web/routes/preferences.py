"""/api/preferences 路由：服务端统一用户偏好。

交易风格 / 持有周期 / 回撤敏感度 / 通知偏好由服务端持有，
四个消费方（Today 排序、Agent 强调、回测默认参数、微信通知筛选）读同一份配置。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from mommy_chaogu.preferences import HOLD_PERIOD_TO_DAYS
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.deps import get_watchlist_store
from mommy_chaogu.web.schemas import UserPreferencesOut, UserPreferencesUpdate

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


def _to_out(prefs: Mapping[str, Any]) -> UserPreferencesOut:
    """持久化值 + 默认值 → 完整响应（补派生字段 default_hold_days）。"""
    updated_at = prefs.get("updated_at")
    if isinstance(updated_at, datetime) and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return UserPreferencesOut(
        style=prefs["style"],
        holding_period=prefs["holding_period"],
        drawdown_sensitivity=prefs["drawdown_sensitivity"],
        notify_min_severity=prefs["notify_min_severity"],
        watched_rules=prefs["watched_rules"],
        reminder_windows=prefs["reminder_windows"],
        default_hold_days=HOLD_PERIOD_TO_DAYS[prefs["holding_period"]],
        updated_at=updated_at,
    )


def _normalize_watched_rules(raw: list[str]) -> list[str]:
    """去重 + strip + 丢弃空串（保持首次出现顺序）。"""
    return list(dict.fromkeys(s for rule in raw if (s := rule.strip())))


@router.get("", response_model=UserPreferencesOut)
def get_preferences(
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> UserPreferencesOut:
    """读取用户偏好（未定制的字段返回默认值）。"""
    return _to_out(store.get_user_preferences())


@router.put("", response_model=UserPreferencesOut)
def update_preferences(
    body: UserPreferencesUpdate,
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> UserPreferencesOut:
    """部分更新用户偏好，返回完整偏好对象。"""
    fields = body.model_fields_set
    updates: dict[str, Any] = {}
    if "style" in fields:
        updates["style"] = body.style
    if "holding_period" in fields:
        updates["holding_period"] = body.holding_period
    if "drawdown_sensitivity" in fields:
        updates["drawdown_sensitivity"] = body.drawdown_sensitivity
    if "notify_min_severity" in fields:
        updates["notify_min_severity"] = body.notify_min_severity
    if "watched_rules" in fields and body.watched_rules is not None:
        updates["watched_rules"] = _normalize_watched_rules(body.watched_rules)
    if "reminder_windows" in fields and body.reminder_windows is not None:
        updates["reminder_windows"] = [w.model_dump() for w in body.reminder_windows]
    return _to_out(store.update_user_preferences(updates))


@router.post("/reset", response_model=UserPreferencesOut)
def reset_preferences(
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
) -> UserPreferencesOut:
    """恢复全部默认值，返回完整偏好对象。"""
    return _to_out(store.reset_user_preferences())
