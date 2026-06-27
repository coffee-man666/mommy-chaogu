"""Server酱 推送实现。

API 文档：https://sct.ftqq.com/
- Endpoint: POST https://sctapi.ftqq.com/{SendKey}.send
- Body: title=标题&desp=内容（application/x-www-form-urlencoded）
- 响应：{"code": 0, "data": {...}, "msg": "..."} (0 成功)

注意：requests 是同步调用，但 BackgroundService._tick 是 async task，
单次推送 ~100ms 不影响其他 WS 客户端。如果以后需要异步换成 aiohttp。
"""
from __future__ import annotations

import logging
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

DEFAULT_ENDPOINT = "https://sctapi.ftqq.com/{send_key}.send"
DEFAULT_TIMEOUT = 10.0


class ServerChanPusher:
    """Server酱 推送实现（兼容 Server酱³ 和旧版）。"""

    def __init__(
        self,
        send_key: str,
        endpoint_template: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT,
        web_base_url: str = "",
    ) -> None:
        if not send_key or not send_key.strip():
            raise ValueError("Server酱 SendKey 不能为空")
        self.send_key = send_key.strip()
        self.endpoint = endpoint_template.format(send_key=self.send_key)
        self.timeout = timeout
        self.web_base_url = web_base_url.rstrip("/")

    def push(self, signal: Signal) -> bool:
        """推送一条信号到 Server酱。返回是否成功。"""
        title = self._format_title(signal)
        desp = self._format_markdown(signal)
        try:
            resp = requests.post(
                self.endpoint,
                data={"title": title, "desp": desp},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = self._safe_json(resp)
            code = data.get("code", -1)
            if code == 0:
                return True
            err_msg = data.get("message") or data.get("msg") or f"code={code}"
            _log.warning("Server酱推送失败: %s - %s", signal.code, err_msg)
            return False
        except requests.RequestException as e:
            _log.warning("Server酱推送网络异常: %s - %s", signal.code, e)
            return False
        except Exception:
            _log.exception("Server酱推送异常: %s", signal.code)
            return False

    def _safe_json(self, resp: requests.Response) -> dict[str, Any]:
        try:
            result: dict[str, Any] = resp.json()
            return result
        except Exception:
            return {}

    def _format_title(self, signal: Signal) -> str:
        emoji = SEVERITY_EMOJI[signal.severity]
        label = SEVERITY_LABEL[signal.severity]
        return f"{emoji} {label} · {signal.name} {signal.rule_id}"

    def _format_markdown(self, signal: Signal) -> str:
        ts = signal.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"### {signal.title}",
            "",
            f"- **股票**：`{signal.code}` {signal.name}",
            f"- **时间**：{ts}",
            f"- **详情**：{signal.detail}",
        ]
        if signal.trigger_value is not None and signal.threshold_value is not None:
            lines.append(
                f"- **触发值**：{signal.trigger_value}（阈值 {signal.threshold_value}）"
            )
        if self.web_base_url and signal.code and len(signal.code) == 6:
            lines.append("")
            lines.append(f"[**📈 查看 K 线 →**]({self.web_base_url}/#/detail/{signal.code})")
        lines.extend(["", "---", "*妈妈炒股 · mommy-chaogu*"])
        return "\n".join(lines)
