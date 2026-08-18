"""专业 CLI REPL 的最小交互回归测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from mommy_chaogu.cli import (
    _REPL_SPARKLINE,
    _build_dispatch,
    _dispatch_passthrough_subcommand,
    _render_logo,
    _run_mommy_repl,
    _run_single_query,
)
from mommy_chaogu.cli_prompt import ReplPrompt
from mommy_chaogu.errors import friendly_error


class _FallbackRouter:
    def route(self, _message: str) -> SimpleNamespace:
        return SimpleNamespace(matched=False, fallback_reason="test")


class _FakeAgent:
    _provider = "deepseek"
    _model = "deepseek-chat"

    def chat(self, _message: str, **callbacks: object) -> SimpleNamespace:
        on_tool = callbacks["on_tool_call"]
        on_result = callbacks["on_tool_result"]
        on_chunk = callbacks["on_chunk"]
        assert callable(on_tool)
        assert callable(on_result)
        assert callable(on_chunk)
        on_tool("get_market_indexes", {})
        on_result("get_market_indexes", True, 20, "[]")
        on_chunk("## 结论\n\n")
        on_chunk("今天行情平稳。")
        return SimpleNamespace(text="## 结论\n\n今天行情平稳。", tool_calls=[])

    def flush(self, timeout: int) -> None:
        assert timeout == 10


def test_repl_renders_rich_answer_and_quits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["今天怎么样", "/quit"])
    monkeypatch.setattr(ReplPrompt, "read", lambda _self: next(answers))

    with pytest.raises(SystemExit) as exc:
        _run_mommy_repl(_FallbackRouter(), object(), _FakeAgent())

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "mommy-chaogu" in output
    assert "███" in output
    assert "▂" in output
    assert "结论" in output
    assert "完成" in output
    assert "再见" in output


def test_repl_header_logo_is_quant_style_gradient() -> None:
    logo = _render_logo()
    assert "███" in logo.plain
    assert _REPL_SPARKLINE in logo.plain
    assert "↗" in logo.plain
    styles = [str(span.style) for span in logo.spans]
    assert any("124,92,255" in s for s in styles)  # 渐变起点：品牌紫
    assert any("91,192,190" in s for s in styles)  # 渐变终点：青
    assert any("#f43f5e" in s for s in styles)  # 红涨
    assert any("#22c55e" in s for s in styles)  # 绿跌


# ---------- 子命令分发 ----------


def test_dispatch_table_covers_documented_subcommands() -> None:
    dispatch = _build_dispatch()
    for name in (
        "watchlist",
        "monitor",
        "cache",
        "channel",
        "connect",
        "setup",
        "semicon",
        "flows",
        "report",
        "agent",
        "memory",
        "web",
        "tui",
        "workflow",
        "doctor",
    ):
        assert name in dispatch
        prog_name, func = dispatch[name]
        assert prog_name == f"mommy-{name}"
        # tui 延迟导入（None），其余都必须有可调 main
        if name != "tui":
            assert callable(func)


def test_dispatch_direct_subcommand_rewrites_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_main() -> None:
        calls.append(list(sys.argv))

    dispatch = {"fake": ("mommy-fake", fake_main)}
    monkeypatch.setattr(sys, "argv", ["mommy", "fake", "list", "--all"])

    assert _dispatch_passthrough_subcommand(dispatch) is True
    assert calls == [["mommy-fake", "list", "--all"]]


def test_dispatch_raw_subcommand_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_main() -> None:
        calls.append(list(sys.argv))

    dispatch = {"fake": ("mommy-fake", fake_main)}
    monkeypatch.setattr(sys, "argv", ["mommy", "--raw", "fake", "add"])

    assert _dispatch_passthrough_subcommand(dispatch) is True
    assert calls == [["mommy-fake", "add"]]


def test_dispatch_raw_unknown_subcommand_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mommy", "--raw", "nope"])
    with pytest.raises(SystemExit) as exc:
        _dispatch_passthrough_subcommand({"fake": ("mommy-fake", lambda: None)})
    assert exc.value.code == 1


def test_dispatch_no_match_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mommy", "今天怎么样"])
    assert _dispatch_passthrough_subcommand({"fake": ("mommy-fake", lambda: None)}) is False


# ---------- 单次查询模式 ----------


class _WorkflowRouter:
    def __init__(self, workflow_id: str = "user_test") -> None:
        self._workflow_id = workflow_id
        self.routed: list[str] = []

    def route(self, message: str) -> SimpleNamespace:
        self.routed.append(message)
        return SimpleNamespace(
            matched=True,
            workflow=SimpleNamespace(description="测试工作流", id=self._workflow_id),
        )

    def execute_route(self, _route: object, query: str, **_cb: object) -> SimpleNamespace:
        return SimpleNamespace(
            summary=f"已执行 {query}", workflow_id=self._workflow_id, succeeded=True
        )


class _RecordingWorkflowStore:
    def __init__(self) -> None:
        self.hits: list[str] = []
        self.closed = 0

    def increment_hit(self, workflow_id: str) -> None:
        self.hits.append(workflow_id)

    def close(self) -> None:
        self.closed += 1


def test_single_query_user_workflow_records_hit_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    router = _WorkflowRouter("user_morning")
    store = _RecordingWorkflowStore()
    runtime = SimpleNamespace(router=router, agent_service=None)

    with pytest.raises(SystemExit) as exc:
        _run_single_query("今天怎么样", runtime=runtime, workflow_store=store, verbose=False)

    assert exc.value.code == 0
    assert store.hits == ["user_morning"]  # user_ 工作流成功后记录命中
    assert store.closed == 1
    output = capsys.readouterr().out
    assert "测试工作流" in output
    assert "已执行" in output


def test_single_query_builtin_workflow_does_not_record_hit() -> None:
    router = _WorkflowRouter("morning_brief")
    store = _RecordingWorkflowStore()
    runtime = SimpleNamespace(router=router, agent_service=None)

    with pytest.raises(SystemExit):
        _run_single_query("今天怎么样", runtime=runtime, workflow_store=store, verbose=False)

    assert store.hits == []  # 只有 user_* 工作流 increment_hit
    assert store.closed == 1


def test_single_query_without_agent_prints_setup_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    router = _WorkflowRouter()
    router.route = lambda _m: SimpleNamespace(matched=False, fallback_reason="no match")  # type: ignore[method-assign]
    store = _RecordingWorkflowStore()
    runtime = SimpleNamespace(router=router, agent_service=None)

    with pytest.raises(SystemExit) as exc:
        _run_single_query("随便聊聊", runtime=runtime, workflow_store=store, verbose=False)

    assert exc.value.code == 0
    assert "mommy setup" in capsys.readouterr().out


# ---------- 错误文案映射（CLI/TUI 共享） ----------


@pytest.mark.parametrize(
    ("message", "expect"),
    [
        ("Error code: 429 - rate limit exceeded", "限流"),
        ("insufficient quota", "额度"),
        ("Error code: 401 - invalid api key", "key 无效"),
    ],
)
def test_friendly_error_maps_api_failures(message: str, expect: str) -> None:
    assert expect in friendly_error(Exception(message))


def test_friendly_error_fallback_keeps_first_line() -> None:
    result: Any = friendly_error(Exception("第一行\n traceback 堆栈"))
    assert result.startswith("出错了：第一行")
