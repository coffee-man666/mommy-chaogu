"""主动通知：通过微信消息通道推送信号摘要。

与 Server酱/Bark 的单向推送互补——当微信通道在线时，
信号通知会同时通过微信私聊发送给用户，包含结论、证据和深链。

去重：持久化当前活跃信号状态，只在首次触发、清除后重触发或严重度升级时推送。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from mommy_chaogu.channels.store import WeixinStore
from mommy_chaogu.channels.weixin import WeixinClient
from mommy_chaogu.db_paths import DEFAULT_DATA_DIR
from mommy_chaogu.preferences import passes_notification_preferences

if TYPE_CHECKING:
    from mommy_chaogu.signals.types import Signal

_log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "weixin_notifications.json"
_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


class WeixinNotifyDeduper:
    """Persist active signal states and reserve delivery before network I/O."""

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._active: dict[str, str] = {}
        self._lock = RLock()
        self._load()

    def _load(self) -> None:
        try:
            raw = self._db_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            active = data.get("active", {})
            if isinstance(active, dict):
                self._active = {
                    str(key): str(value)
                    for key, value in active.items()
                    if str(value) in _SEVERITY_RANK
                }
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            self._active = {}

    def _save(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"active": dict(sorted(self._active.items()))}
        tmp = self._db_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._db_path)

    def should_push(self, signal: Signal) -> bool:
        key = self._key(signal)
        current = self._severity(signal)
        previous = self._active.get(key)
        return previous is None or _SEVERITY_RANK[current] > _SEVERITY_RANK[previous]

    def mark_pushed(self, signal: Signal) -> None:
        self.reserve(signal)

    def reserve(self, signal: Signal) -> tuple[bool, str | None]:
        """Persist a delivery claim before sending and return prior state."""
        with self._lock:
            key = self._key(signal)
            current = self._severity(signal)
            previous = self._active.get(key)
            if previous is not None and _SEVERITY_RANK[current] <= _SEVERITY_RANK[previous]:
                if _SEVERITY_RANK[current] < _SEVERITY_RANK[previous]:
                    self._active[key] = current
                    try:
                        self._save()
                    except OSError:
                        self._active[key] = previous
                        raise
                return False, previous
            self._active[key] = current
            try:
                self._save()
            except OSError:
                if previous is None:
                    self._active.pop(key, None)
                else:
                    self._active[key] = previous
                raise
            return True, previous

    def rollback(self, signal: Signal, previous: str | None) -> None:
        """Release a reservation after network failure so a later tick may retry."""
        with self._lock:
            key = self._key(signal)
            if previous is None:
                self._active.pop(key, None)
            else:
                self._active[key] = previous
            try:
                self._save()
            except OSError as exc:
                _log.error("微信通知去重状态回滚失败: %s", exc)

    def reconcile(self, signals: list[Signal]) -> None:
        """Clear states for rules no longer active, enabling a later retrigger."""
        with self._lock:
            current_keys = {self._key(signal) for signal in signals}
            previous = self._active.copy()
            self._active = {
                key: severity for key, severity in self._active.items() if key in current_keys
            }
            if self._active == previous:
                return
            try:
                self._save()
            except OSError:
                self._active = previous
                raise

    @staticmethod
    def _key(signal: Signal) -> str:
        return f"{signal.code}|{signal.rule_id}"

    @staticmethod
    def _severity(signal: Signal) -> str:
        value = getattr(signal.severity, "value", signal.severity)
        severity = str(value)
        return severity if severity in _SEVERITY_RANK else "info"


def send_signal_notifications(
    signals: list[Signal],
    *,
    web_base_url: str = "",
    client: WeixinClient | None = None,
    deduper: WeixinNotifyDeduper | None = None,
    preference_provider: Callable[[], Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> int:
    """通过微信通道主动推送信号通知。

    使用持久化状态确保连续轮询不重复，并在网络发送前持久化 reservation。

    ``preference_provider`` 提供时，每次调用读取一次用户偏好
    （/api/preferences 的同一份配置），在 dedup reservation 之前按
    严重度下限 / 关注规则 / 提醒时段过滤信号。
    注意：provider 抛异常时记日志并**跳过过滤**（按全部通过处理）——
    宁可多推也不过滤失败时静默丢弃关键告警。
    ``now`` 仅用于测试注入当前时间（默认取系统 UTC 时间）。

    Returns: 成功发送的条数（0 = 未连接/无信号/发送失败/全部已推送）。
    """
    dedup = deduper or WeixinNotifyDeduper()
    try:
        dedup.reconcile(signals)
    except OSError as exc:
        _log.error("微信通知去重状态无法持久化，跳过本轮发送: %s", exc)
        return 0
    if not signals:
        return 0

    prefs: Mapping[str, Any] | None = None
    if preference_provider is not None:
        try:
            prefs = preference_provider()
        except Exception as exc:
            _log.warning("读取用户偏好失败，本轮微信通知不按偏好过滤: %s", exc)
            prefs = None

    store = WeixinStore()
    creds = store.load_credentials()
    if creds is None:
        return 0  # 微信通道未连接

    cli = client or WeixinClient()
    sent = 0

    for signal in signals:
        if prefs is not None and not passes_notification_preferences(
            severity=str(getattr(signal.severity, "value", signal.severity)),
            rule_id=signal.rule_id,
            prefs=prefs,
            now=now if now is not None else datetime.now(UTC),
        ):
            continue
        try:
            reserved, previous = dedup.reserve(signal)
        except OSError as exc:
            _log.error("微信通知去重状态无法持久化，跳过发送: %s", exc)
            continue
        if not reserved:
            continue
        text = _format_notification(signal, web_base_url)
        try:
            cli.send_text(
                base_url=creds.base_url,
                token=creds.token,
                to_user_id=creds.owner_user_id,
                text=text,
            )
            sent += 1
        except Exception as exc:
            dedup.rollback(signal, previous)
            _log.warning("微信主动推送失败 (%s %s): %s", signal.code, signal.rule_id, exc)

    return sent


def _format_notification(signal: Signal, web_base_url: str) -> str:
    """格式化单条信号为微信消息。

    包含：结论、关键证据、数据时间和回到 Web 的深链。
    """
    severity_label = {"info": "💡 提示", "warning": "⚠️ 警告", "critical": "🚨 严重"}.get(
        signal.severity.value if hasattr(signal.severity, "value") else str(signal.severity),
        "⚠️ 警告",
    )

    lines = [
        f"{severity_label} · {signal.name}（{signal.code}）",
        "",
        f"📊 {signal.title}",
        f"📝 {signal.detail}",
        f"🕐 {signal.timestamp.strftime('%H:%M:%S')}",
    ]

    if signal.trigger_value is not None and signal.threshold_value is not None:
        lines.append(f"📐 触发值 {signal.trigger_value}（阈值 {signal.threshold_value}）")

    if web_base_url and len(signal.code) == 6:
        lines.append(f"\n🔗 {web_base_url}/#/detail/{signal.code}")

    return "\n".join(lines)
