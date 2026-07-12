"""Tests for production-readiness fixes (Phase 1).

Covers:
- Timezone-aware market_phase() and TopBar clock (Finding 2)
- Colorblind theme color remapping in change_color() (Finding 3)
- Empty watchlist clears stale rows (Finding 4)
- Tab slash-completion vs mode switch (Finding 5)
- HelpScreen BINDINGS (not BINDING) (Finding 5)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mommy_chaogu.tui.services.formatting import change_color

# ---------------------------------------------------------------------------
# Finding 2: Timezone — market_phase() and clock must use Asia/Shanghai
# ---------------------------------------------------------------------------


class TestMarketPhaseTimezone:
    """market_phase should always use Asia/Shanghai regardless of system TZ."""

    @pytest.mark.parametrize(
        "dt,expected",
        [
            # Saturday
            (datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")), "已收盘"),
            # Monday 9:20 — 集合竞价
            (datetime(2026, 7, 6, 9, 20, tzinfo=ZoneInfo("Asia/Shanghai")), "集合竞价"),
            # Monday 10:00 — 交易中
            (datetime(2026, 7, 6, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")), "交易中"),
            # Monday 12:00 — 午休
            (datetime(2026, 7, 6, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")), "午休"),
            # Monday 14:00 — 交易中
            (datetime(2026, 7, 6, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")), "交易中"),
            # Monday 15:30 — 已收盘
            (datetime(2026, 7, 6, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")), "已收盘"),
        ],
    )
    def test_phase_at_shanghai_time(
        self, dt: datetime, expected: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify market_phase returns correct phase for known Shanghai times."""
        # Force system timezone to UTC to prove it's not using local time
        monkeypatch.setenv("TZ", "UTC")
        import time as _time

        _time.tzset()

        from mommy_chaogu.tui.widgets import top_bar as tb_mod

        # Monkey-patch datetime.now in top_bar to return our fixed time
        original_now = datetime.now

        class _FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return dt.astimezone(tz)
                return dt

            # Pass through any other attributes
            def __getattr__(self, name):
                return getattr(original_now, name)

        monkeypatch.setattr(tb_mod, "datetime", _FakeDateTime)
        assert tb_mod.market_phase() == expected


# ---------------------------------------------------------------------------
# Finding 3: Colorblind theme — change_color should return blue for negatives
# ---------------------------------------------------------------------------


class TestColorblindTheme:
    def test_positive_red_default(self) -> None:
        assert change_color(1.5) == "red"

    def test_negative_green_default(self) -> None:
        assert change_color(-1.5) == "green"

    def test_positive_red_colorblind(self) -> None:
        assert change_color(1.5, theme="colorblind") == "red"

    def test_negative_blue_colorblind(self) -> None:
        """In colorblind mode, green should be replaced with blue."""
        assert change_color(-1.5, theme="colorblind") == "blue"

    def test_negative_green_dark(self) -> None:
        assert change_color(-1.5, theme="dark") == "green"

    def test_negative_green_light(self) -> None:
        assert change_color(-1.5, theme="light") == "green"

    def test_zero_dim_regardless_of_theme(self) -> None:
        assert change_color(0, theme="dark") == "dim"
        assert change_color(0, theme="colorblind") == "dim"

    def test_none_dim_regardless_of_theme(self) -> None:
        assert change_color(None, theme="dark") == "dim"
        assert change_color(None, theme="colorblind") == "dim"

    def test_open_stock_detail_recolors_when_theme_changes(self) -> None:
        """An already-open detail screen should immediately adopt colorblind colors."""
        from textual.widgets import Static

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.screens.stock_detail import StockDetailScreen
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                screen = StockDetailScreen("000001")
                screen._load_detail = lambda: None  # type: ignore[method-assign]
                app.push_screen(screen)
                await pilot.pause()

                app.ui_theme = "dark"
                screen._update_header("平安银行", "10.00", -1.5)
                header = screen.query_one("#stock-header", Static)
                assert "[green]" in str(header.content)

                app.ui_theme = "light"
                app.action_cycle_theme()
                assert app.ui_theme == "colorblind"
                assert "[blue]" in str(header.content)
                assert "[green]" not in str(header.content)

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# Finding 4: Empty watchlist should clear stale rows
# ---------------------------------------------------------------------------


class TestEmptyWatchlistClears:
    def test_update_watchlist_empty_calls_update_data(self) -> None:
        """update_watchlist([]) should pass empty list to table.update_data."""
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.dashboard import DashboardView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                dashboard = app.query_one(DashboardView)

                # Track if update_data was called with empty list
                called_with: list[list] = []
                table = dashboard.query_one("#watch-table")

                original = table.update_data

                def spy(rows):
                    called_with.append(rows)
                    original(rows)

                table.update_data = spy  # type: ignore[assignment]

                # Call with empty list
                dashboard.update_watchlist([])
                await pilot.pause()

                assert len(called_with) == 1
                assert called_with[0] == []

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# Finding 5: Tab should accept slash completion, not just switch modes
# ---------------------------------------------------------------------------


class TestTabSlashCompletion:
    def test_tab_completes_slash_in_chat(self) -> None:
        """In chat mode, typing /ref then Tab should complete to /refresh."""
        from textual.widgets import ContentSwitcher, Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                switcher = app.query_one("#main", ContentSwitcher)
                switcher.current = "chat"
                await pilot.pause()

                prompt = app.query_one("#prompt", Input)
                prompt.value = "/ref"
                await pilot.pause()

                # Press Tab — should complete, not switch to dashboard
                await pilot.press("tab")
                await pilot.pause()

                assert prompt.value == "/refresh", (
                    f"Expected '/refresh', got '{prompt.value}'"
                )
                assert switcher.current == "chat", "Should still be in chat mode"

        asyncio.run(_test())

    def test_tab_switches_mode_when_not_slash(self) -> None:
        """Tab without slash prefix should still toggle modes."""
        from textual.widgets import ContentSwitcher, Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())
            async with app.run_test() as pilot:
                switcher = app.query_one("#main", ContentSwitcher)
                switcher.current = "chat"
                await pilot.pause()

                prompt = app.query_one("#prompt", Input)
                prompt.value = "hello"
                await pilot.pause()

                await pilot.press("tab")
                await pilot.pause()

                assert switcher.current == "dashboard"

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# Finding 5: HelpScreen should use BINDINGS (plural)
# ---------------------------------------------------------------------------


class TestHelpScreenBindings:
    def test_help_screen_has_bindings(self) -> None:
        from mommy_chaogu.tui.screens.help import HelpScreen

        # BINDINGS must exist as class attribute
        assert hasattr(HelpScreen, "BINDINGS")
        # BINDING (singular) must NOT exist
        assert not hasattr(HelpScreen, "BINDING")
