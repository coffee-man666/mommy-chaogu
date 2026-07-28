"""Tests for production-readiness fixes.

Covers:
- Timezone-aware market_phase() (Finding 2)
- Colorblind theme color remapping in change_color() (Finding 3)
- HelpScreen BINDINGS (not BINDING)
- mommy-tui CLI --help / --version
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mommy_chaogu.tui.services.formatting import change_color

# ---------------------------------------------------------------------------
# Finding 2: Timezone — market_phase() must use Asia/Shanghai
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
            def now(cls, tz=None):  # type: ignore[no-untyped-def]
                if tz is not None:
                    return dt.astimezone(tz)
                return dt

            # Pass through any other attributes
            def __getattr__(self, name):  # type: ignore[no-untyped-def]
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


# ---------------------------------------------------------------------------
# HelpScreen should use BINDINGS (plural)
# ---------------------------------------------------------------------------


class TestHelpScreenBindings:
    def test_help_screen_has_bindings(self) -> None:
        from mommy_chaogu.tui.screens.help import HelpScreen

        # BINDINGS must exist as class attribute
        assert hasattr(HelpScreen, "BINDINGS")
        # BINDING (singular) must NOT exist
        assert not hasattr(HelpScreen, "BINDING")


class TestTuiCli:
    def test_help_exits_without_starting_tui(self, capsys: pytest.CaptureFixture[str]) -> None:
        from mommy_chaogu.tui.app import build_tui_parser

        with pytest.raises(SystemExit) as exc_info:
            build_tui_parser().parse_args(["--help"])

        assert exc_info.value.code == 0
        assert "mommy-tui" in capsys.readouterr().out

    def test_version_exits_without_starting_tui(self, capsys: pytest.CaptureFixture[str]) -> None:
        from mommy_chaogu import __version__
        from mommy_chaogu.tui.app import build_tui_parser

        with pytest.raises(SystemExit) as exc_info:
            build_tui_parser().parse_args(["--version"])

        assert exc_info.value.code == 0
        assert __version__ in capsys.readouterr().out
