"""TUI Pilot 冒烟测试（单屏对话版）。

启动 app（FakeServices）→ 焦点在输入框 → 输入 /today → 卡片出现 →
输入普通文本（无 agent）→ 显示降级提示。

pytest-asyncio 不是项目依赖，所以用 asyncio.run() 驱动 run_test()。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import FakeServices


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class TestFakeServices:
    """Validate FakeServices produces sane fake data before the app uses it."""

    def test_create_returns_services(self) -> None:
        svc = FakeServices.create()
        assert svc is not None
        assert svc.data is not None
        assert svc.agent is not None

    def test_watchlist_quotes(self) -> None:
        svc = FakeServices.create()
        rows = svc.data.watchlist_quotes()
        assert len(rows) == 3
        assert rows[0]["code"] == "688981"
        assert rows[0]["name"] == "中芯国际"
        assert isinstance(rows[0]["price"], Decimal)

    def test_portfolio_snapshot(self) -> None:
        svc = FakeServices.create()
        snap = svc.data.portfolio_snapshot()
        assert snap["total_market_value"] == Decimal("50000")
        assert len(snap["positions"]) == 2

    def test_source_label(self) -> None:
        svc = FakeServices.create()
        assert svc.data.source_label() == "东方财富 实时"

    def test_agent_has_no_agent(self) -> None:
        """FakeServices should not wire up a real LLM agent."""
        svc = FakeServices.create()
        assert svc.agent.has_agent() is False

    def test_card_data_sources(self) -> None:
        """对话内卡片数据源（指数/信号/@联想）都有假数据。"""
        svc = FakeServices.create()
        assert svc.indexes is not None and len(svc.indexes()) == 3
        assert svc.signals_recent is not None and len(svc.signals_recent()) == 2
        assert svc.stock_candidates is not None
        assert ("600519", "贵州茅台") in svc.stock_candidates()


class TestAppInstantiation:
    """Verify the app can be constructed without external resources."""

    def test_app_construction(self) -> None:
        app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
        assert app.services is not None
        assert app.services.data.source_label() == "东方财富 实时"


# ---------------------------------------------------------------------------
# Pilot 冒烟：单屏启动 → /today → 降级提示
# ---------------------------------------------------------------------------


async def _wait_for(pilot: Any, predicate: Any, timeout: float = 5.0) -> bool:
    """轮询等待条件成立（worker 线程 + call_from_thread 异步收敛）。"""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause(0.05)
        if predicate():
            return True
    return False


class TestSingleScreenSmoke:
    def test_startup_focus_and_layout(self) -> None:
        """单屏：无 ContentSwitcher/看板，启动焦点在输入框。"""
        from textual.widgets import ContentSwitcher, Input

        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.top_bar import TopBar

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test():
                # 单屏组件齐备
                app.query_one(TopBar)
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                # 不再有 ContentSwitcher / 看板
                assert len(app.query(ContentSwitcher)) == 0
                assert len(app.query("#dashboard-tabs")) == 0
                # 启动焦点在输入框
                assert prompt.has_focus

        _run(_test())

    def test_welcome_card_shows_fake_data(self) -> None:
        """欢迎卡回填：指数 + 自选红绿 + 无 agent 降级说明。"""
        from textual.widgets import Static

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                from mommy_chaogu.tui.views.chat import ChatView

                chat = app.query_one(ChatView)

                def _ready() -> bool:
                    try:
                        content = str(chat.query_one("#chat-welcome", Static).content)  # type: ignore[attr-defined]
                    except Exception:
                        return False
                    return "上证" in content

                assert await _wait_for(pilot, _ready)
                content = str(chat.query_one("#chat-welcome", Static).content)  # type: ignore[attr-defined]
                assert "3 只" in content  # 自选 3 只
                assert "AI 未配置" in content  # 降级说明

        _run(_test())

    def test_topbar_ai_unconfigured(self) -> None:
        """TopBar：无 agent 时 AI⚪ 未配置。"""
        from mommy_chaogu.tui.widgets.top_bar import TopBar

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test():
                top = app.query_one(TopBar)
                assert "⚪" in top.ai_label
                assert "未配置" in top.ai_label

        _run(_test())

    def test_slash_today_renders_card(self) -> None:
        """输入 /today → 今日总览卡出现在对话流。"""
        from textual.widgets import Input

        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "/today"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".overview-card")) == 1)
                content = str(chat.query(".overview-card")[0].content)  # type: ignore[attr-defined]
                assert "今日总览" in content
                assert "上证指数" in content

        _run(_test())

    def test_plain_text_without_agent_shows_fallback(self) -> None:
        """普通文本（FakeServices 无 agent）→ 降级提示。"""
        from textual.widgets import Input

        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "今天大盘怎么样"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".hint-card")) >= 1)
                hints = [str(h.content) for h in chat.query(".hint-card")]  # type: ignore[attr-defined]
                assert any("AI 未配置" in h for h in hints)
                # 用户消息上屏
                assert len(chat.query(".user-msg")) == 1

        _run(_test())
