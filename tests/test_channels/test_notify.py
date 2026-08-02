"""微信主动通知（channels.notify）测试。

验证：
- 未连接微信通道时返回 0
- 持久化去重：同一信号在多次调用（模拟多个轮询周期）中不重复推送
- 消息格式包含结论、证据、时间
- web_base_url 传入时附加深链
- 发送失败不抛异常
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from mommy_chaogu.channels.notify import (
    WeixinNotifyDeduper,
    _format_notification,
    send_signal_notifications,
)
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


def _mock_creds() -> MagicMock:
    creds = MagicMock()
    creds.base_url = "https://example.com"
    creds.token = "tok"
    creds.owner_user_id = "user1"
    return creds


class TestSendSignalNotifications:
    """send_signal_notifications 行为测试。"""

    def test_no_signals_returns_zero(self, tmp_path: Path) -> None:
        deduper = WeixinNotifyDeduper(tmp_path / "state.json")
        assert send_signal_notifications([], deduper=deduper) == 0

    def test_not_connected_returns_zero(self, tmp_path: Path) -> None:
        """未连接微信通道时返回 0，不报错。"""
        with patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.load_credentials.return_value = None
            mock_store_cls.return_value = mock_store
            assert (
                send_signal_notifications(
                    [_make_signal()], deduper=WeixinNotifyDeduper(tmp_path / "state.json")
                )
                == 0
            )

    def test_persistent_dedup_across_calls(self, tmp_path: Path) -> None:
        """同一信号在多次调用（模拟连续轮询）中只推送一次。"""
        deduper = WeixinNotifyDeduper(db_path=tmp_path / "weixin_pushed.json")

        with (
            patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls,
            patch("mommy_chaogu.channels.notify.WeixinClient") as mock_client_cls,
        ):
            mock_store = MagicMock()
            mock_store.load_credentials.return_value = _mock_creds()
            mock_store_cls.return_value = mock_store

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            signal = _make_signal()

            # 第一次调用：应推送 1 条
            result1 = send_signal_notifications([signal], deduper=deduper, client=mock_client)
            assert result1 == 1

            # 第二次调用（模拟下个轮询周期）：同一信号不应重复推送
            result2 = send_signal_notifications([signal], deduper=deduper, client=mock_client)
            assert result2 == 0

            # send_text 只应被调用 1 次
            assert mock_client.send_text.call_count == 1

    def test_different_signals_both_pushed(self, tmp_path: Path) -> None:
        """不同 code 或 rule_id 的信号都应推送。"""
        deduper = WeixinNotifyDeduper(db_path=tmp_path / "weixin_pushed.json")

        with (
            patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls,
            patch("mommy_chaogu.channels.notify.WeixinClient") as mock_client_cls,
        ):
            mock_store = MagicMock()
            mock_store.load_credentials.return_value = _mock_creds()
            mock_store_cls.return_value = mock_store

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            signals = [
                _make_signal(rule_id="rule_a"),
                _make_signal(code="000858", rule_id="rule_b"),
            ]
            result = send_signal_notifications(signals, deduper=deduper, client=mock_client)
            assert result == 2

    def test_send_failure_does_not_raise(self, tmp_path: Path) -> None:
        """单条发送失败不影响整体流程。"""
        with (
            patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls,
            patch("mommy_chaogu.channels.notify.WeixinClient") as mock_client_cls,
        ):
            mock_store = MagicMock()
            mock_store.load_credentials.return_value = _mock_creds()
            mock_store_cls.return_value = mock_store

            mock_client = MagicMock()
            mock_client.send_text.side_effect = RuntimeError("network error")
            mock_client_cls.return_value = mock_client

            deduper = WeixinNotifyDeduper(tmp_path / "state.json")
            result = send_signal_notifications(
                [_make_signal()], deduper=deduper, client=mock_client
            )
            assert result == 0  # 发送失败 → 0 条成功
            assert deduper.should_push(_make_signal()) is True

    def test_clear_then_retrigger_sends_again(self, tmp_path: Path) -> None:
        deduper = WeixinNotifyDeduper(tmp_path / "state.json")
        mock_client = MagicMock()
        with patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls:
            mock_store_cls.return_value.load_credentials.return_value = _mock_creds()
            signal = _make_signal()

            assert send_signal_notifications([signal], deduper=deduper, client=mock_client) == 1
            assert send_signal_notifications([], deduper=deduper, client=mock_client) == 0
            assert send_signal_notifications([signal], deduper=deduper, client=mock_client) == 1
            assert mock_client.send_text.call_count == 2

    def test_severity_escalation_sends_again(self, tmp_path: Path) -> None:
        deduper = WeixinNotifyDeduper(tmp_path / "state.json")
        mock_client = MagicMock()
        with patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls:
            mock_store_cls.return_value.load_credentials.return_value = _mock_creds()

            assert (
                send_signal_notifications(
                    [_make_signal(severity=SignalSeverity.WARNING)],
                    deduper=deduper,
                    client=mock_client,
                )
                == 1
            )
            assert (
                send_signal_notifications(
                    [_make_signal(severity=SignalSeverity.CRITICAL)],
                    deduper=deduper,
                    client=mock_client,
                )
                == 1
            )

    def test_persistence_failure_prevents_network_send(self, tmp_path: Path) -> None:
        deduper = WeixinNotifyDeduper(tmp_path / "state.json")
        mock_client = MagicMock()
        with (
            patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls,
            patch.object(deduper, "_save", side_effect=OSError("read only")),
        ):
            mock_store_cls.return_value.load_credentials.return_value = _mock_creds()
            assert (
                send_signal_notifications([_make_signal()], deduper=deduper, client=mock_client)
                == 0
            )
            mock_client.send_text.assert_not_called()


class TestWeixinNotifyDeduper:
    """持久化去重器测试。"""

    def test_should_push_first_time(self, tmp_path: Path) -> None:
        dedup = WeixinNotifyDeduper(db_path=tmp_path / "d.json")
        assert dedup.should_push(_make_signal()) is True

    def test_should_not_push_after_marked(self, tmp_path: Path) -> None:
        dedup = WeixinNotifyDeduper(db_path=tmp_path / "d.json")
        signal = _make_signal()
        dedup.mark_pushed(signal)
        assert dedup.should_push(signal) is False

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        """文件持久化：新实例能读到已推送记录。"""
        db = tmp_path / "d.json"
        dedup1 = WeixinNotifyDeduper(db_path=db)
        signal = _make_signal()
        dedup1.mark_pushed(signal)

        dedup2 = WeixinNotifyDeduper(db_path=db)
        assert dedup2.should_push(signal) is False


class TestPreferenceFiltering:
    """preference_provider 接入后的筛选行为（/api/preferences 同一份配置）。"""

    # 固定 UTC 时间 → Asia/Shanghai（UTC+8）
    _SHANGHAI_10AM = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)  # 上海 10:00
    _SHANGHAI_8PM = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)  # 上海 20:00
    _SHANGHAI_2AM = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)  # 上海 次日 02:00

    def _send(
        self,
        tmp_path: Path,
        signal: Signal,
        prefs: dict,
        now: datetime,
    ) -> tuple[int, MagicMock]:
        mock_client = MagicMock()
        with patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls:
            mock_store_cls.return_value.load_credentials.return_value = _mock_creds()
            result = send_signal_notifications(
                [signal],
                deduper=WeixinNotifyDeduper(tmp_path / "state.json"),
                client=mock_client,
                preference_provider=lambda: prefs,
                now=now,
            )
        return result, mock_client

    @staticmethod
    def _prefs(**overrides: object) -> dict:
        from mommy_chaogu.preferences import default_preferences

        prefs = default_preferences()
        prefs.update(overrides)
        return prefs

    def test_severity_floor_blocks_warning(self, tmp_path: Path) -> None:
        prefs = self._prefs(notify_min_severity="critical")
        result, mock_client = self._send(tmp_path, _make_signal(), prefs, self._SHANGHAI_10AM)
        assert result == 0
        mock_client.send_text.assert_not_called()

    def test_severity_floor_passes_critical(self, tmp_path: Path) -> None:
        prefs = self._prefs(notify_min_severity="critical")
        result, mock_client = self._send(
            tmp_path, _make_signal(severity=SignalSeverity.CRITICAL), prefs, self._SHANGHAI_10AM
        )
        assert result == 1
        assert mock_client.send_text.call_count == 1

    def test_watched_rules_allowlist(self, tmp_path: Path) -> None:
        prefs = self._prefs(watched_rules=["other_rule"])
        result, mock_client = self._send(tmp_path, _make_signal(), prefs, self._SHANGHAI_10AM)
        assert result == 0
        mock_client.send_text.assert_not_called()

        prefs = self._prefs(watched_rules=["price_change_threshold"])
        result, mock_client = self._send(
            tmp_path / "sub", _make_signal(), prefs, self._SHANGHAI_10AM
        )
        assert result == 1

    def test_reminder_window_inside_and_outside(self, tmp_path: Path) -> None:
        prefs = self._prefs(reminder_windows=[{"start": "09:30", "end": "15:00"}])
        result, mock_client = self._send(
            tmp_path / "in", _make_signal(), prefs, self._SHANGHAI_10AM
        )
        assert result == 1
        assert mock_client.send_text.call_count == 1

        result, mock_client = self._send(
            tmp_path / "out", _make_signal(), prefs, self._SHANGHAI_8PM
        )
        assert result == 0
        mock_client.send_text.assert_not_called()

    def test_midnight_wrapping_window(self, tmp_path: Path) -> None:
        prefs = self._prefs(reminder_windows=[{"start": "22:00", "end": "07:00"}])
        result, mock_client = self._send(tmp_path, _make_signal(), prefs, self._SHANGHAI_2AM)
        assert result == 1
        assert mock_client.send_text.call_count == 1

    def test_provider_exception_still_delivers(self, tmp_path: Path) -> None:
        """provider 抛异常：记日志并跳过过滤（宁可多推也不静默丢告警）。"""

        def _boom() -> dict:
            raise RuntimeError("db locked")

        mock_client = MagicMock()
        with patch("mommy_chaogu.channels.notify.WeixinStore") as mock_store_cls:
            mock_store_cls.return_value.load_credentials.return_value = _mock_creds()
            result = send_signal_notifications(
                [_make_signal()],
                deduper=WeixinNotifyDeduper(tmp_path / "state.json"),
                client=mock_client,
                preference_provider=_boom,
            )
        assert result == 1
        assert mock_client.send_text.call_count == 1


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
