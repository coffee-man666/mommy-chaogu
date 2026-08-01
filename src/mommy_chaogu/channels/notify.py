"""主动通知：通过微信消息通道推送信号摘要。

与 Server酱/Bark 的单向推送互补——当微信通道在线时，
信号通知会同时通过微信私聊发送给用户，包含结论、证据和深链。

去重：使用 JSON 文件持久化当天已推送的信号指纹（code|rule_id|date），
确保同一信号在多个轮询周期内不会重复推送。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mommy_chaogu.channels.store import WeixinStore
from mommy_chaogu.channels.weixin import WeixinClient

if TYPE_CHECKING:
    from mommy_chaogu.signals.types import Signal

_log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/weixin_pushed.json")


def _today_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class WeixinNotifyDeduper:
    """JSON 文件去重：同一 code|rule_id 每天只推一次。

    文件格式与 push/deduper.py 的 JsonFileDeduper 一致，
    但使用独立的文件以避免与 Server酱 去重冲突。
    """

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._pushed: set[str] = set()
        self._load()

    def _load(self) -> None:
        try:
            raw = self._db_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            today = _today_iso()
            # 只保留今天的 key（跨天自动清理）
            self._pushed = {
                k for k in data.get("pushed_keys", [])
                if k.endswith(today)
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._pushed = set()

    def _save(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"date": _today_iso(), "pushed_keys": sorted(self._pushed)}
        tmp = self._db_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._db_path)

    def should_push(self, signal: Signal) -> bool:
        key = self._key(signal)
        return key not in self._pushed

    def mark_pushed(self, signal: Signal) -> None:
        key = self._key(signal)
        self._pushed.add(key)
        self._save()

    @staticmethod
    def _key(signal: Signal) -> str:
        today = _today_iso()
        return f"{signal.code}|{signal.rule_id}|{today}"


def send_signal_notifications(
    signals: list[Signal],
    *,
    web_base_url: str = "",
    client: WeixinClient | None = None,
    deduper: WeixinNotifyDeduper | None = None,
) -> int:
    """通过微信通道主动推送信号通知。

    使用持久化去重确保同一信号在多个轮询周期内不重复推送。

    Returns: 成功发送的条数（0 = 未连接/无信号/发送失败/全部已推送）。
    """
    if not signals:
        return 0

    store = WeixinStore()
    creds = store.load_credentials()
    if creds is None:
        return 0  # 微信通道未连接

    cli = client or WeixinClient()
    dedup = deduper or WeixinNotifyDeduper()
    sent = 0

    for signal in signals:
        if not dedup.should_push(signal):
            continue  # 今天已推送过该信号
        text = _format_notification(signal, web_base_url)
        try:
            cli.send_text(
                base_url=creds.base_url,
                token=creds.token,
                to_user_id=creds.owner_user_id,
                text=text,
            )
            dedup.mark_pushed(signal)
            sent += 1
        except Exception as exc:
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
