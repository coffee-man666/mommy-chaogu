"""切片 A：TopBar 会话级 token 用量状态（作品验收项之一）。

产品行为：每轮对话结束后，顶栏常驻显示本会话累计 token 消耗
（∑ 1.2k tok 样式），用户对成本心里有数；未产生用量时不占位。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Vertical

from mommy_chaogu.tui.widgets.top_bar import TopBar


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield Vertical()


class TestTopBarSessionUsage:
    def _run_mounted(self, check: Any) -> None:
        async def scenario() -> None:
            app = _Host()
            async with app.run_test() as pilot:
                bar = TopBar()
                app.query_one(Vertical).mount(bar)
                await pilot.pause()
                check(bar)

        _run(scenario())

    def test_hidden_when_zero(self) -> None:
        def check(bar: TopBar) -> None:
            bar.set_session_usage(0)
            assert "∑" not in str(bar.content)

        self._run_mounted(check)

    def test_compact_display(self) -> None:
        def check(bar: TopBar) -> None:
            bar.set_session_usage(1234)
            assert "∑ 1.2k tok" in str(bar.content)

        self._run_mounted(check)

    def test_accumulates(self) -> None:
        def check(bar: TopBar) -> None:
            bar.set_session_usage(850)
            bar.set_session_usage(850 + 1784)
            assert "∑ 2.6k tok" in str(bar.content)

        self._run_mounted(check)


class TestAppSessionUsageAccumulation:
    """App 每轮结束后把 usage 累加进 TopBar（真实轮次生命周期）。"""

    def test_turn_usage_accumulates_in_topbar(self, tmp_path: Path) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        services = FakeServices.create()

        def _chat(message: str, **kwargs: Any) -> Any:
            return SimpleNamespace(
                text="好的",
                interrupted=False,
                usage={"total_tokens": 1784},
            )

        services.agent.route = lambda text: None  # type: ignore[method-assign]
        services.agent.has_agent = lambda: True  # type: ignore[method-assign]
        services.agent.chat = _chat  # type: ignore[method-assign]
        services.agent.watch_background = lambda on_done: False  # type: ignore[method-assign]

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test(size=(110, 30)) as pilot:
                top = app.query_one(TopBar)
                prompt = app.query_one("ChatInput")
                prompt.value = "第一轮"
                await pilot.press("enter")
                deadline = asyncio.get_running_loop().time() + 4
                while asyncio.get_running_loop().time() < deadline:
                    if "∑" in str(top.content):
                        break
                    await pilot.pause(0.05)
                assert "∑ 1.8k tok" in str(top.content)

                prompt.value = "第二轮"
                await pilot.press("enter")
                deadline = asyncio.get_running_loop().time() + 4
                while asyncio.get_running_loop().time() < deadline:
                    if "∑ 3.6k tok" in str(top.content):
                        break
                    await pilot.pause(0.05)
                assert "∑ 3.6k tok" in str(top.content)

        _run(_test())
