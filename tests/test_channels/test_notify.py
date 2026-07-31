"""微信主动通知（channels.notify）测试。

验证：
- 未连接微信通道时返回 0
- 有信号时按 code+rule_id 去重
- 消息格式包含结论、证据、时间
- web_base_url 传入时附加深链
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from mommy_chaogu.channels.notify import _format_notification, send_signal_notifications
from mommy_chaogu.signals.types import Signal, SignalSeverity


def _make_signal(
    code: str = "600519",
    name: str = "贵州茅台",
    rule_id: str = "price_change_threshold",
    severity: SignalSeverity = SignalSeverity.WARNING,
) -> Signal:
    return Signal(
        timestamp=datetime(2026, 7, 31, 14, 30, tzinfo=UTC),
        code=code,
        name=name,
        rule_id=rule_id,
        severity=severity,
        title="主力净流入警告",
        detail="主力净额 1.2 亿（阈值 8000 万）",
        trigger_value=Decimal("120000000"),
        threshold_value=Decimal("80000000"),
    )


class TestSendSignalNotifications:
    """send_signal_notifications 行为测试。"""

    def test_no_signals_returns_zero(self) -> None:
        assert send_signal_notifications([]) == 0

    def test_not_connected_returns_zero(self) -> None:
        """未连接微信通道时返回 0，不报错。"""
        with patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.load_credentials.return_value = None
            mock_store_cls.return_value = mock_store
            assert send_signal_notifications([_make_signal()]) == 0

    def test_dedup_same_code_rule(self) -> None:
        """相同 code+rule_id 的信号只发一条。"""
        with (
            patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls,
            patch("mommy_chaogu.channels.notify.WeixinClient") as mock_client_cls,
        ):
            mock_store = MagicMock()
            creds = MagicMock()
            creds.base_url = "https://example.com"
            creds.token = "tok"
            creds.owner_user_id = "user1"
            mock_store.load_credentials.return_value = creds
            mock_store_cls.return_value = mock_store

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            signals = [
                _make_signal(rule_id="rule_a"),
                _make_signal(rule_id="rule_a"),  # 重复
                _make_signal(rule_id="rule_b"),  # 不同规则
            ]
            result = send_signal_notifications(signals)
            assert result == 2  # 去重后只有 2 条唯一信号

    def test_send_failure_does_not_raise(self) -> None:
        """单条发送失败不影响整体流程。"""
        with (
            patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls,
            patch("mommy_chaogu.channels.notify.WeixinClient") as mock_client_cls,
        ):
            mock_store = MagicMock()
            creds = MagicMock()
            creds.base_url = "https://example.com"
            creds.token = "tok"
            creds.owner_user_id = "user1"
            mock_store.load_credentials.return_value = creds
            mock_store_cls.return_value = mock_store

            mock_client = MagicMock()
            mock_client.send_text.side_effect = RuntimeError("network error")
            mock_client_cls.return_value = mock_client

            result = send_signal_notifications([_make_signal()])
            assert result == 0  # 发送失败 → 0 条成功


class TestFormatNotification:
    """消息格式测试。"""

    def test_contains_conclusion_and_evidence(self) -> None:
        signal = _make_signal()
        text = _format_notification(signal, "")
        assert "贵州茅台" in text
        assert "600519" in text
        assert "主力净流入警告" in text
        assert "主力净额 1.2 亿" in text
        assert "14:30" in text

    def test_contains_deep_link(self) -> None:
        signal = _make_signal()
        text = _format_notification(signal, "https://mom.example.com")
        assert "https://mom.example.com/#/detail/600519" in text

    def test_no_deep_link_without_base_url(self) -> None:
        signal = _make_signal()
        text = _format_notification(signal, "")
        assert "#/detail/" not in text

    def test_severity_labels(self) -> None:
        for severity, expected_emoji in [
            (SignalSeverity.INFO, "💡"),
            (SignalSeverity.WARNING, "⚠️"),
            (SignalSeverity.CRITICAL, "🚨"),
        ]:
            signal = _make_signal(severity=severity)
            text = _format_notification(signal, "")
            assert expected_emoji in text
