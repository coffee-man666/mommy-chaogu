"""Tests for TUI slash command system（单屏对话版）。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from mommy_chaogu.tui.views.chat import SLASH_COMMANDS, SlashCommand, SlashSuggester


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


# ---------------------------------------------------------------------------
# SlashCommand dataclass
# ---------------------------------------------------------------------------


class TestSlashCommand:
    def test_basic_fields(self) -> None:
        cmd = SlashCommand(name="today", description="今日总览")
        assert cmd.name == "today"
        assert cmd.description == "今日总览"
        assert cmd.has_args is False

    def test_with_args(self) -> None:
        cmd = SlashCommand(name="quote", description="报价", has_args=True)
        assert cmd.has_args is True

    def test_frozen(self) -> None:
        cmd = SlashCommand(name="test", description="test")
        with pytest.raises(AttributeError):
            cmd.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SLASH_COMMANDS registry
# ---------------------------------------------------------------------------


class TestSlashRegistry:
    def test_all_expected_commands_present(self) -> None:
        expected = {
            "today",
            "watch",
            "portfolio",
            "flows",
            "quote",
            "predictions",
            "signals",
            "memory",
            "status",
            "help",
            "clear",
            "theme",
            "quit",
        }
        assert set(SLASH_COMMANDS.keys()) == expected

    def test_all_entries_are_slash_command(self) -> None:
        for cmd in SLASH_COMMANDS.values():
            assert isinstance(cmd, SlashCommand)

    def test_flows_and_quote_have_args(self) -> None:
        assert SLASH_COMMANDS["flows"].has_args is True
        assert SLASH_COMMANDS["quote"].has_args is True

    def test_no_arg_commands(self) -> None:
        for name, cmd in SLASH_COMMANDS.items():
            if name in ("flows", "quote"):
                continue
            assert cmd.has_args is False, f"{name} should not have args"

    def test_all_have_descriptions(self) -> None:
        for cmd in SLASH_COMMANDS.values():
            assert cmd.description, f"{cmd.name} has empty description"


# ---------------------------------------------------------------------------
# SlashSuggester
# ---------------------------------------------------------------------------


class TestSlashSuggester:
    @pytest.fixture
    def suggester(self) -> SlashSuggester:
        return SlashSuggester()

    def _suggest(self, suggester: SlashSuggester, value: str) -> str | None:
        """Run the async get_suggestion synchronously."""
        return asyncio.run(suggester.get_suggestion(value))

    def test_non_slash_returns_none(self, suggester: SlashSuggester) -> None:
        assert self._suggest(suggester, "今天怎么样") is None
        assert self._suggest(suggester, "") is None

    def test_just_slash_returns_first_command(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/")
        assert result is not None
        assert result.startswith("/")

    def test_exact_prefix_match(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/to")
        assert result == "/today"

    def test_full_command(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/today")
        assert result == "/today"

    def test_single_char_prefix(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/h")
        assert result == "/help"

    def test_command_with_args_gets_trailing_space(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/q")
        assert result == "/quote "

    def test_command_with_args_full_name(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/quote")
        assert result == "/quote "

    def test_no_match_returns_none(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/xyz")
        assert result is None

    def test_case_insensitive(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/TO")
        assert result == "/today"

    def test_flows_suggestion(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/fl")
        assert result == "/flows "


# ---------------------------------------------------------------------------
# Pilot: 卡片渲染（/flows /memory /watch /portfolio /signals /predictions /status）
# ---------------------------------------------------------------------------


class TestSlashCards:
    def test_flows_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/flows 688981"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".flow-card")) == 1)
                content = str(chat.query(".flow-card")[0].content)  # type: ignore[attr-defined]
                assert "688981" in content
                assert "主力" in content

        _run(_test())

    def test_flows_without_code_renders_watchlist_ranking(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/flows"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".flow-card")) == 1)
                content = str(chat.query(".flow-card")[0].content)  # type: ignore[attr-defined]
                assert "资金流对比" in content
                assert "中芯国际" in content

        _run(_test())

    def test_memory_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/memory"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".memory-card")) == 1)
                content = str(chat.query(".memory-card")[0].content)  # type: ignore[attr-defined]
                assert "记忆系统" in content
                assert "预测" in content
                assert "Token" in content  # token 用量露出

        _run(_test())

    def test_watch_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/watch"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".watch-card")) == 1)
                content = str(chat.query(".watch-card")[0].content)  # type: ignore[attr-defined]
                assert "自选股" in content
                assert "中芯国际" in content
                assert "贵州茅台" in content

        _run(_test())

    def test_portfolio_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/portfolio"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".portfolio-card")) == 1)
                content = str(chat.query(".portfolio-card")[0].content)  # type: ignore[attr-defined]
                assert "持仓" in content
                assert "总市值" in content

        _run(_test())

    def test_signals_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/signals"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".signals-card")) == 1)
                content = str(chat.query(".signals-card")[0].content)  # type: ignore[attr-defined]
                assert "近期信号" in content
                assert "紧急" in content  # 中文严重度徽章
                assert "中芯国际" in content

        _run(_test())

    def test_predictions_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/predictions"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".predictions-card")) == 1)
                content = str(chat.query(".predictions-card")[0].content)  # type: ignore[attr-defined]
                assert "预测跟踪" in content
                assert "命中" in content
                assert "中芯国际" in content
                assert "看涨" in content

        _run(_test())

    def test_status_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/status"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".status-card")) == 1)
                content = str(chat.query(".status-card")[0].content)  # type: ignore[attr-defined]
                assert "服务状态" in content
                assert "AI⚪ 未配置" in content
                assert "东方财富" in content
                assert "market" in content

        _run(_test())

    def test_unknown_command_hint(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/xyz"
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                hints = [str(h.content) for h in chat.query(".hint-card")]  # type: ignore[attr-defined]
                assert any("未知命令" in h for h in hints)

        _run(_test())
