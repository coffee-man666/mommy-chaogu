"""取数失败必须与"取到但字段为空"可区分。

``get_fundamentals`` 早先在东财挂掉时返回各字段为 None 的空壳，
``check_earnings_catalyst`` 直接把它拼进结果，LLM 于是把"数据源挂了"读成
"这家公司没有 ROE"这个**事实**——和 agent-start.md 写的
"事实、工具结果和模型推断保持可区分"直接冲突。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mommy_chaogu.agent.tools import analysis as analysis_tools
from mommy_chaogu.agent.tools.base import ToolContext
from mommy_chaogu.agent.tools.registry import ToolRegistry
from mommy_chaogu.market_data import fundamentals_api


def test_empty_fundamentals_carries_error_marker() -> None:
    payload = fundamentals_api._empty_fundamentals("600519", "boom")
    assert payload["ok"] is False
    assert payload["error"] == "boom"
    assert payload["code"] == "600519"
    # 字段仍是 None，但不能只靠字段判断失败
    assert payload["roe"] is None


def test_get_fundamentals_marks_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("502 Bad Gateway")

    monkeypatch.setattr(fundamentals_api.requests, "get", _boom)
    payload = fundamentals_api.get_fundamentals("600519")
    assert payload["ok"] is False
    assert "502" in payload["error"]


def test_get_fundamentals_marks_empty_data_block(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": None}

    monkeypatch.setattr(fundamentals_api.requests, "get", lambda *a, **k: _Resp())
    payload = fundamentals_api.get_fundamentals("600519")
    assert payload["ok"] is False
    assert "空数据" in payload["error"]


def test_get_fundamentals_marks_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": {"f14": "贵州茅台", "f9": "17.67", "f162": "0.3"}}

    monkeypatch.setattr(fundamentals_api.requests, "get", lambda *a, **k: _Resp())
    payload = fundamentals_api.get_fundamentals("600519")
    assert payload["ok"] is True
    assert payload["name"] == "贵州茅台"
    assert "error" not in payload


def test_get_fundamentals_tool_surfaces_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """工具层必须把 ok=False 透出去，宿主 Agent 才能识别为失败证据。"""
    monkeypatch.setattr(
        fundamentals_api.requests,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("502 Bad Gateway")),
    )
    from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter

    class _Dead:
        name = "dead"

    registry = ToolRegistry(ToolContext(adapter=FallbackAdapter([_Dead()])))
    payload = json.loads(registry.call("get_fundamentals", {"code": "600519"}))
    assert payload["ok"] is False
    assert "error" in payload


def test_check_earnings_catalyst_flags_fundamentals_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        analysis_tools,
        "get_fundamentals",
        lambda code: fundamentals_api._empty_fundamentals(code, "数据源挂了"),
    )
    monkeypatch.setattr(analysis_tools, "get_announcements", lambda code, limit=3: [])
    payload = json.loads(
        analysis_tools._handle_check_earnings_catalyst(None, {"codes": ["600519"]})
    )
    item = payload["results"][0]
    assert item["fundamentals_ok"] is False
    assert item["fundamentals_error"] == "数据源挂了"
    # 不能因为基本面挂了就把整条结果丢掉
    assert item["code"] == "600519"


def test_check_earnings_catalyst_omits_flag_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        analysis_tools,
        "get_fundamentals",
        lambda code: {"ok": True, "code": code, "name": "贵州茅台", "pe": 17.67, "roe": 0.3},
    )
    monkeypatch.setattr(analysis_tools, "get_announcements", lambda code, limit=3: [])
    payload = json.loads(
        analysis_tools._handle_check_earnings_catalyst(None, {"codes": ["600519"]})
    )
    item = payload["results"][0]
    assert "fundamentals_ok" not in item
    assert item["name"] == "贵州茅台"
