"""Tests for TUI slash command system."""

from __future__ import annotations

import asyncio

import pytest

from mommy_chaogu.tui.views.chat import SLASH_COMMANDS, SlashCommand, SlashSuggester

# ---------------------------------------------------------------------------
# SlashCommand dataclass
# ---------------------------------------------------------------------------


class TestSlashCommand:
    def test_basic_fields(self) -> None:
        cmd = SlashCommand(name="refresh", description="刷新")
        assert cmd.name == "refresh"
        assert cmd.description == "刷新"
        assert cmd.has_args is False

    def test_with_args(self) -> None:
        cmd = SlashCommand(name="watch", description="详情", has_args=True)
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
            "help",
            "refresh",
            "clear",
            "dashboard",
            "chat",
            "theme",
            "watch",
            "flows",
            "memory",
            "quit",
        }
        assert set(SLASH_COMMANDS.keys()) == expected

    def test_all_entries_are_slash_command(self) -> None:
        for cmd in SLASH_COMMANDS.values():
            assert isinstance(cmd, SlashCommand)

    def test_watch_and_flows_have_args(self) -> None:
        assert SLASH_COMMANDS["watch"].has_args is True
        assert SLASH_COMMANDS["flows"].has_args is True

    def test_no_arg_commands(self) -> None:
        for name, cmd in SLASH_COMMANDS.items():
            if name in ("watch", "flows"):
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
        result = self._suggest(suggester, "/ref")
        assert result == "/refresh"

    def test_full_command(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/refresh")
        assert result == "/refresh"

    def test_single_char_prefix(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/h")
        assert result == "/help"

    def test_command_with_args_gets_trailing_space(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/w")
        assert result == "/watch "

    def test_command_with_args_full_name(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/watch")
        assert result == "/watch "

    def test_no_match_returns_none(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/xyz")
        assert result is None

    def test_case_insensitive(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/REF")
        assert result == "/refresh"

    def test_flows_suggestion(self, suggester: SlashSuggester) -> None:
        result = self._suggest(suggester, "/fl")
        assert result == "/flows "

    def test_multiple_matches_returns_first(self, suggester: SlashSuggester) -> None:
        """Multiple commands start with 'c': clear, chat."""
        result = self._suggest(suggester, "/c")
        assert result is not None
        # Should return one of the 'c' commands
        assert result.lstrip("/").split()[0] in ("clear", "chat")


# ---------------------------------------------------------------------------
# Pilot: /flows + /memory 卡片渲染（#7）
# ---------------------------------------------------------------------------


def _run(coro) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(coro)


class TestFlowsMemoryCards:
    def test_flows_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/flows 688981"
                await pilot.pause()
                # 提交
                await pilot.press("enter")
                await pilot.pause()

                card = chat.query(".flows-card")
                assert len(card) == 1
                content = str(card[0].content)  # type: ignore[attr-defined]
                assert "688981" in content
                assert "主力" in content
                # 不应再出现"请在终端运行"
                assert "请在终端运行" not in content

        _run(_test())

    def test_memory_renders_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/memory"
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                card = chat.query(".memory-card")
                assert len(card) == 1
                content = str(card[0].content)  # type: ignore[attr-defined]
                assert "记忆系统" in content
                assert "预测" in content
                assert "请在终端运行" not in content
