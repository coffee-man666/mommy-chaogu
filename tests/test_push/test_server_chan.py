"""Server酱 推送测试。"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.push.server_chan import ServerChanPusher
from mommy_chaogu.signals.types import Signal, SignalSeverity


def make_signal(
    severity: SignalSeverity = SignalSeverity.CRITICAL,
    code: str = "600519",
    name: str = "XD贵州茅",
    rule_id: str = "main_flow_threshold",
) -> Signal:
    return Signal(
        timestamp=datetime(2026, 6, 27, 9, 30, tzinfo=UTC),
        code=code,
        name=name,
        rule_id=rule_id,
        severity=severity,
        title="主力净流出",
        detail="净流出 -6.24 亿",
        trigger_value=Decimal("-624000000"),
        threshold_value=Decimal("200000000"),
    )


def make_mock_response(code: int = 0, msg: str = "OK") -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"code": code, "msg": msg}
    resp.raise_for_status = MagicMock()
    return resp


# ---------- 构造器 ----------

def test_empty_key_raises():
    with pytest.raises(ValueError, match="不能为空"):
        ServerChanPusher("")


def test_whitespace_key_raises():
    with pytest.raises(ValueError, match="不能为空"):
        ServerChanPusher("   ")


def test_endpoint_construction():
    pusher = ServerChanPusher("abc123")
    assert pusher.endpoint == "https://sctapi.ftqq.com/abc123.send"


# ---------- push 成功 ----------

def test_push_success_critical():
    pusher = ServerChanPusher("test_key")
    signal = make_signal(severity=SignalSeverity.CRITICAL)
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(code=0)
        assert pusher.push(signal) is True
        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert mock_post.call_args.args[0] == "https://sctapi.ftqq.com/test_key.send"
        assert kwargs["data"]["title"].startswith("🚨")
        assert "XD贵州茅" in kwargs["data"]["title"]
        assert "main_flow_threshold" in kwargs["data"]["title"]
        assert "600519" in kwargs["data"]["desp"]


def test_push_success_warning():
    pusher = ServerChanPusher("test_key")
    signal = make_signal(severity=SignalSeverity.WARNING)
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_post.return_value = make_mock_response()
        assert pusher.push(signal) is True
        kwargs = mock_post.call_args.kwargs
        assert kwargs["data"]["title"].startswith("⚠️")


def test_push_includes_web_link_when_configured():
    pusher = ServerChanPusher("test_key", web_base_url="https://mama.example.com")
    signal = make_signal()
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_post.return_value = make_mock_response()
        pusher.push(signal)
        desp = mock_post.call_args.kwargs["data"]["desp"]
        # 链接里应该有 stock code
        assert "600519" in desp
        # K 线链接部分
        assert "detail/600519" in desp


# ---------- push 失败 ----------

def test_push_failure_non_zero_code():
    pusher = ServerChanPusher("bad_key")
    signal = make_signal()
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(code=40001, msg="SendKey 错误")
        assert pusher.push(signal) is False


def test_push_network_error():
    import requests

    pusher = ServerChanPusher("test_key")
    signal = make_signal()
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("network down")
        assert pusher.push(signal) is False


def test_push_http_status_error():
    import requests

    pusher = ServerChanPusher("test_key")
    signal = make_signal()
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        mock_post.return_value = mock_resp
        assert pusher.push(signal) is False


def test_push_invalid_json():
    pusher = ServerChanPusher("test_key")
    signal = make_signal()
    with patch("mommy_chaogu.push.server_chan.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        assert pusher.push(signal) is False
