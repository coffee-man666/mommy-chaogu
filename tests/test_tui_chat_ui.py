"""Tests for dexter-style chat UI: ToolIndicator / WorkingIndicator / HintBar.

Covers:
- format helpers (tool display names, args, digest, elapsed)
- ToolIndicator start → complete / error lifecycle
- WorkingIndicator mount/remove driven by set_busy
- HintBar contextual states (default / busy / slash suggestions)
- Full agent-chat flow with tool_call + tool_result callbacks
- Theme fix: action_cycle_theme uses app.theme (textual 8.x API)
- Dashboard empty-state wiring
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mommy_chaogu.tui.views.chat import match_slash_commands
from mommy_chaogu.tui.widgets.hint_bar import HintBar
from mommy_chaogu.tui.widgets.tool_indicator import (
    ToolIndicator,
    format_elapsed,
    format_result_digest,
    format_tool_args,
    tool_display_name,
    truncate_at_word,
)
from mommy_chaogu.tui.widgets.working_indicator import WorkingIndicator

# ---------------------------------------------------------------------------
# format helpers
# ---------------------------------------------------------------------------


class TestToolDisplayName:
    def test_mapped(self) -> None:
        assert tool_display_name("get_quote") == "查行情"
        assert tool_display_name("get_money_flow_today") == "查今日资金流"
        assert tool_display_name("search_similar_events") == "搜相似事件"

    def test_all_24_tools_mapped(self) -> None:
        from mommy_chaogu.tui.widgets.tool_indicator import TOOL_DISPLAY_NAMES

        assert len(TOOL_DISPLAY_NAMES) == 24

    def test_fallback(self) -> None:
        assert tool_display_name("some_unknown_tool") == "some unknown tool"


class TestFormatToolArgs:
    def test_empty(self) -> None:
        assert format_tool_args({}) == ""

    def test_query_quoted(self) -> None:
        assert format_tool_args({"query": "比亚迪"}) == '"比亚迪"'

    def test_key_value(self) -> None:
        assert format_tool_args({"code": "600519"}) == "code=600519"

    def test_numeric(self) -> None:
        assert format_tool_args({"days": 30}) == "days=30"

    def test_long_value_truncated(self) -> None:
        result = format_tool_args({"code": "x" * 100})
        assert len(result) <= len("code=") + 41


class TestFormatResultDigest:
    def test_first_line_only(self) -> None:
        assert format_result_digest("第一行\n第二行\n第三行") == "第一行"

    def test_whitespace_collapsed(self) -> None:
        assert format_result_digest("  多个   空格  ") == "多个 空格"

    def test_empty(self) -> None:
        assert format_result_digest("") == "完成"

    def test_truncated(self) -> None:
        assert len(format_result_digest("x" * 200)) <= 61


class TestFormatElapsed:
    def test_ms(self) -> None:
        assert format_elapsed(850) == "850ms"

    def test_seconds(self) -> None:
        assert format_elapsed(1230) == "1.2s"
        assert format_elapsed(12000) == "12.0s"


class TestTruncateAtWord:
    def test_short(self) -> None:
        assert truncate_at_word("abc", 10) == "abc"

    def test_word_boundary(self) -> None:
        assert truncate_at_word("hello world foo", 12) == "hello world…"
        assert truncate_at_word("hello world foo", 8) == "hello…"

    def test_hard_cut(self) -> None:
        assert truncate_at_word("abcdefghijklmnop", 8) == "abcdefgh…"


class TestMatchSlashCommands:
    def test_all_on_bare_slash(self) -> None:
        assert len(match_slash_commands("/")) == 10

    def test_prefix(self) -> None:
        names = [c.name for c in match_slash_commands("/re")]
        assert names == ["refresh"]

    def test_non_slash(self) -> None:
        assert match_slash_commands("hello") == []

    def test_no_match(self) -> None:
        assert match_slash_commands("/xyz") == []


# ---------------------------------------------------------------------------
# Pilot: ToolIndicator lifecycle
# ---------------------------------------------------------------------------


def _run(pilot_coro) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(pilot_coro)


class TestToolIndicatorLifecycle:
    def test_start_then_complete(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.tool_call_started(1, "get_quote", {"code": "600519"})
                await pilot.pause()

                indicator = chat.query_one(ToolIndicator)
                header = str(indicator.query_one(".ti-header").content)  # type: ignore[attr-defined]
                assert "⏺" in header
                assert "查行情(code=600519)" in header

                chat.tool_call_finished(1, True, 1230, "贵州茅台 1680.00 +0.5%")
                await pilot.pause()

                detail = str(indicator.query_one(".ti-detail").content)  # type: ignore[attr-defined]
                assert "⎿" in detail
                assert "贵州茅台" in detail
                assert "1.2s" in detail
                # 完成后 call_id 已被弹出
                assert 1 not in chat._tool_widgets

        _run(_test())

    def test_error_path(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.tool_call_started(2, "get_bars", {"code": "688981"})
                await pilot.pause()
                chat.tool_call_finished(2, False, 500, "连接超时")
                await pilot.pause()

                indicator = chat.query_one(ToolIndicator)
                detail = str(indicator.query_one(".ti-detail").content)  # type: ignore[attr-defined]
                assert "Error: 连接超时" in detail

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: WorkingIndicator + HintBar
# ---------------------------------------------------------------------------


class TestBusyIndicators:
    def test_working_indicator_mount_remove(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.set_busy(True)
                await pilot.pause()
                assert len(chat.query(WorkingIndicator)) == 1

                chat.set_busy(False)
                await pilot.pause()
                assert len(chat.query(WorkingIndicator)) == 0

        _run(_test())

    def test_hint_bar_states(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                hint = chat.query_one(HintBar)
                assert hint.mode == "default"

                # 输入 / 前缀 → 候选列表
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/re"
                await pilot.pause()
                assert hint.mode == "suggestions"
                content = str(hint.content)  # type: ignore[attr-defined]
                assert "/refresh" in content

                # busy → esc 提示
                chat.set_busy(True)
                await pilot.pause()
                assert hint.mode == "busy"

                # 忙完 → 回到候选（输入还在）
                chat.set_busy(False)
                await pilot.pause()
                assert hint.mode == "suggestions"

                # 清空输入 → 默认
                prompt.value = ""
                await pilot.pause()
                assert hint.mode == "default"

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: 完整 agent 对话流（tool_call + tool_result 回调）
# ---------------------------------------------------------------------------


class _FakeAgent:
    """同步触发两个回调的假 agent。"""

    def chat(self, message, history=None, on_tool_call=None, on_tool_result=None):  # type: ignore[no-untyped-def]
        if on_tool_call is not None:
            on_tool_call("get_quote", {"code": "600519"})
        if on_tool_result is not None:
            on_tool_result("get_quote", True, 1230, "贵州茅台 1680.00 +0.5%")
        return SimpleNamespace(text="茅台最新报价 1680 元。", tool_calls=[], rounds=1)


class TestAgentChatFlow:
    def test_full_turn_renders_tool_and_stats(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            services = FakeServices.create()
            services.agent._agent = _FakeAgent()
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                app.handle_chat_message("茅台怎么样")
                # 等 worker 线程 + call_from_thread 完成
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not chat._busy:
                        break

                assert not chat._busy
                # 工具指示器已完成（⎿ 摘要 · 耗时）
                indicator = chat.query_one(ToolIndicator)
                detail = str(indicator.query_one(".ti-detail").content)  # type: ignore[attr-defined]
                assert "贵州茅台" in detail
                assert "1.2s" in detail
                # 助手回复（⏺ + Markdown）
                assistant = chat.query(".assistant-msg")
                assert len(assistant) == 1
                # ✻ 收尾统计
                stats = chat.query(".turn-stats")
                assert len(stats) == 1
                assert "✻" in str(stats[0].content)  # type: ignore[attr-defined]
                # 用户消息 ❯
                user = chat.query(".user-msg")
                assert "❯" in str(user[0].content)  # type: ignore[attr-defined]

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: 主题修复（app.theme API）+ 看板空态
# ---------------------------------------------------------------------------


class TestThemeFix:
    def test_cycle_theme_sets_app_theme(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                app.ui_theme = "dark"
                app.action_cycle_theme()
                await pilot.pause()
                assert app.ui_theme == "light"
                assert app.theme == "textual-light"

                app.action_cycle_theme()
                await pilot.pause()
                assert app.ui_theme == "colorblind"
                assert app.theme == "textual-dark"

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: slash 候选 ↑↓ 循环选择
# ---------------------------------------------------------------------------


class TestSlashCycling:
    def _to_chat(self, app) -> None:  # type: ignore[no-untyped-def]
        from textual.widgets import ContentSwitcher

        app.query_one("#main", ContentSwitcher).current = "chat"

    def test_up_down_cycles_candidates(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                self._to_chat(app)
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/"
                await pilot.pause()

                assert len(chat._slash_matches) == 10
                assert chat._slash_sel == 0

                await pilot.press("down")
                await pilot.pause()
                assert chat._slash_sel == 1
                assert chat.selected_slash_completion() == "/refresh"

                await pilot.press("up")
                await pilot.pause()
                assert chat._slash_sel == 0

                # 继续 up → 环绕到最后一项
                await pilot.press("up")
                await pilot.pause()
                assert chat._slash_sel == 9
                assert chat.selected_slash_completion() == "/quit"

        _run(_test())

    def test_tab_completes_selected_candidate(self) -> None:
        from textual.widgets import ContentSwitcher, Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                self._to_chat(app)
                await pilot.pause()
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/"
                await pilot.pause()

                # ↓ 移到 /refresh，Tab 接受选中项
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                assert prompt.value == "/refresh"
                # 仍在对话模式（Tab 被补全拦截）
                switcher = app.query_one("#main", ContentSwitcher)
                assert switcher.current == "chat"

        _run(_test())

    def test_space_exits_slash_selection(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                self._to_chat(app)
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/watch "
                await pilot.pause()
                assert not chat.in_slash_selection()
                assert chat.selected_slash_completion() is None

        _run(_test())


class TestDashboardEmptyState:
    def test_empty_watchlist_shows_hint(self) -> None:
        from textual.widgets import Static

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.dashboard import DashboardView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                dashboard = app.query_one(DashboardView)
                empty = dashboard.query_one("#watch-empty", Static)

                dashboard.update_watchlist([])
                await pilot.pause()
                assert empty.display is True

                dashboard.update_watchlist(
                    [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "price": None,
                            "change_pct": None,
                            "change_amount": None,
                            "main_flow": None,
                        }
                    ]
                )
                await pilot.pause()
                assert empty.display is False

        _run(_test())
