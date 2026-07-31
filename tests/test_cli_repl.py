"""专业 CLI REPL 的最小交互回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mommy_chaogu.cli import _run_mommy_repl
from mommy_chaogu.cli_prompt import ReplPrompt


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
    assert "结论" in output
    assert "完成" in output
    assert "再见" in output
