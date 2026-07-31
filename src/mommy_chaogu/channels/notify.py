"""主动通知：通过微信消息通道推送信号摘要。

与 Server酱/Bark 的单向推送互补——当微信通道在线时，
信号通知会同时通过微信私聊发送给用户，包含结论、证据和深链。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mommy_chaogu.channels.store import WeixinStore
from mommy_chaogu.channels.weixin import WeixinClient

if TYPE_CHECKING:
    from mommy_chaogu.signals.types import Signal

_log = logging.getLogger(__name__)


def send_signal_notifications(
    signals: list[Signal],
    *,
    web_base_url: str = "",
    client: WeixinClient | None = None,
) -> int:
    """通过微信通道主动推送信号通知。

    Returns: 成功发送的条数（0 = 未连接/无信号/发送失败）。
    """
    if not signals:
        return 0

    store = WeixinStore()
    creds = store.load_credentials()
    if creds is None:
        return 0  # 微信通道未连接

    cli = client or WeixinClient()
    sent = 0

    # 合并同类信号：同一 code+rule_id 只发一条
    seen: set[str] = set()
    unique: list[Signal] = []
    for s in signals:
        key = f"{s.code}|{s.rule_id}"
        if key not in seen:
            seen.add(key)
            unique.append(s)

    for signal in unique:
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
