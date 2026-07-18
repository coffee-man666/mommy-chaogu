"""Bark 推送实现。

API 文档：https://bark.day.app/
- Endpoint: POST https://api.day.app/{device_key}
- Body (JSON): {"title": "标题", "body": "内容"}
- 响应：{"code": 200, "message": "success", ...} (code 200 成功)

Bark 是一款轻量级 iOS 推送 App，适合个人即时通知。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from mommy_chaogu.signals.types import Signal, SignalSeverity

_log = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    SignalSeverity.INFO: "ℹ️",
    SignalSeverity.WARNING: "⚠️",
    SignalSeverity.CRITICAL: "🚨",
}

SEVERITY_LABEL = {
    SignalSeverity.INFO: "提示",
    SignalSeverity.WARNING: "提醒",
    SignalSeverity.CRITICAL: "警告",
}

DEFAULT_ENDPOINT = "https://api.day.app/{device_key}"
DEFAULT_TIMEOUT = 10.0
TITLE_MAX_LEN = 20


class BarkPusher:
    """Bark 推送实现。"""

    def __init__(
        self,
        device_key: str | None = None,
        endpoint_template: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT,
        web_base_url: str = "",
    ) -> None:
        key = device_key or os.environ.get("BARK_DEVICE_KEY", "")
        if not key or not key.strip():
            raise ValueError(
                "Bark device_key 不能为空（可通过参数或 BARK_DEVICE_KEY 环境变量提供）"
            )
        self.device_key = key.strip()
        self.endpoint = endpoint_template.format(device_key=self.device_key)
        self.timeout = timeout
        self.web_base_url = web_base_url.rstrip("/")

    def push(self, signal: Signal) -> bool:
        """推送一条信号到 Bark。返回是否成功。"""
        title = self._format_title(signal)
        body = self._format_markdown(signal)
        try:
            resp = requests.post(
                self.endpoint,
                json={"title": title, "body": body},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = self._safe_json(resp)
            code = data.get("code", -1)
            if code == 200:
                return True
            err_msg = data.get("message") or f"code={code}"
            _log.warning("Bark推送失败: %s - %s", signal.code, err_msg)
            return False
        except requests.RequestException as e:
            _log.warning("Bark推送网络异常: %s - %s", signal.code, e)
            return False
        except Exception:
            _log.exception("Bark推送异常: %s", signal.code)
            return False

    def _safe_json(self, resp: requests.Response) -> dict[str, Any]:
        try:
            result: dict[str, Any] = resp.json()
            return result
        except Exception:
            return {}

    def _format_title(self, signal: Signal) -> str:
        """格式化标题，截断到 TITLE_MAX_LEN 字符。"""
        title = f"{signal.name} {signal.rule_id}"
        if len(title) > TITLE_MAX_LEN:
            title = title[:TITLE_MAX_LEN]
        return title

    def _format_markdown(self, signal: Signal) -> str:
        """格式化 body 为带 emoji 严重度的 Markdown。"""
        emoji = SEVERITY_EMOJI[signal.severity]
        label = SEVERITY_LABEL[signal.severity]
        ts = signal.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"{emoji} **{label}** · {signal.title}",
            "",
            f"- **股票**：`{signal.code}` {signal.name}",
            f"- **时间**：{ts}",
            f"- **详情**：{signal.detail}",
        ]
        if signal.trigger_value is not None and signal.threshold_value is not None:
            lines.append(f"- **触发值**：{signal.trigger_value}（阈值 {signal.threshold_value}）")
        if self.web_base_url and signal.code and len(signal.code) == 6:
            lines.append("")
            lines.append(f"[**📈 查看 K 线 →**]({self.web_base_url}/#/detail/{signal.code})")
        return "\n".join(lines)
