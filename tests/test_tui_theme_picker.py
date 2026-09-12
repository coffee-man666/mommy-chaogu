"""主题选择器：↑↓ 实时预览 / Enter 确认 / Esc 还原。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.screens.theme_picker import ThemePickerScreen
from mommy_chaogu.tui.services.bootstrap import FakeServices


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


def _boot() -> MommyTuiApp:
    return MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]


class TestThemePicker:
    def test_open_sets_screen_and_marks_current(self) -> None:
        async def scenario() -> None:
            app = _boot()
            async with app.run_test() as pilot:
                app.action_open_theme_picker()
                await pilot.pause()
                assert isinstance(app.screen, ThemePickerScreen)
                picker = app.screen
                assert len(picker._options) == len(app._THEMES)
                # 打开时高亮在当前主题上，且预览回调不改变主题
                assert app.ui_theme == picker._original

        _run(scenario())

    def test_highlight_previews_live(self) -> None:
        async def scenario() -> None:
            app = _boot()
            async with app.run_test() as pilot:
                app.action_open_theme_picker()
                await pilot.pause()
                before = app.ui_theme
                await pilot.press("down")
                await pilot.pause()
                assert app.ui_theme != before, "高亮移动应实时预览新主题"

        _run(scenario())

    def test_enter_confirms_and_dismisses(self) -> None:
        async def scenario() -> None:
            app = _boot()
            async with app.run_test() as pilot:
                app.action_open_theme_picker()
                await pilot.pause()
                await pilot.press("down")
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, ThemePickerScreen)
                # 确认后的主题即最后预览的主题
                assert app.ui_theme == app._THEMES[1]

        _run(scenario())

    def test_escape_reverts_original(self) -> None:
        async def scenario() -> None:
            app = _boot()
            async with app.run_test() as pilot:
                app.action_open_theme_picker()
                await pilot.pause()
                original = app.ui_theme
                await pilot.press("down")
                await pilot.press("down")
                assert app.ui_theme != original
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, ThemePickerScreen)
                assert app.ui_theme == original, "Esc 应还原打开时主题"

        _run(scenario())
