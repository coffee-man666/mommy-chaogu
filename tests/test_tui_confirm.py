"""TUI 内联写操作确认集成测试（ConfirmBar + app.on_confirm 接线）。

覆盖：
- 挂载：写操作触发时对话流出现确认条并抢焦点，HintBar 切确认提示
- y / n / a / Esc 四种决定路径
- a（本会话不再询问）：第二轮同工具不再弹确认
- 取消整轮（cancel_event）：悬空确认强制落定为拒绝，worker 不悬空
- 只读工具不弹确认
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import FakeServices
from mommy_chaogu.tui.views.chat import ChatView


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class _ReplayAgent:
    """假 AgentBridge：on_confirm 决定驱动后续回调序列。"""

    def __init__(self) -> None:
        self.decisions: list[bool] = []
        self.confirm_asked = 0

    def route(self, text: str) -> None:
        return None

    def has_agent(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "deepseek"

    def model_name(self) -> str:
        return "deepseek-chat"

    def watch_background(self, on_done: Any) -> bool:
        return False

    def chat(self, message: str, **kwargs: Any) -> Any:
        on_confirm = kwargs.get("on_confirm")
        on_tool_call = kwargs.get("on_tool_call")
        on_tool_result = kwargs.get("on_tool_result")
        assert on_confirm is not None, "app 必须向 agent 层传 on_confirm"

        time.sleep(0.1)
        self.confirm_asked += 1
        allowed = bool(on_confirm("strategy_save", {"card": {"name": "均值回归"}}))
        self.decisions.append(allowed)
        if allowed:
            on_tool_call("strategy_save", {"card": {"name": "均值回归"}})
            time.sleep(0.05)
            on_tool_result("strategy_save", True, 5, '{"ok": true}')
        time.sleep(0.05)
        return SimpleNamespace(
            text="完成" if allowed else "已按你的要求取消", interrupted=False, usage={}
        )


def _make_app(agent: _ReplayAgent) -> MommyTuiApp:
    services = FakeServices.create()
    services.agent = agent  # type: ignore[assignment]
    return MommyTuiApp(services=services)  # type: ignore[arg-type]


async def _submit(pilot: Any, app: MommyTuiApp, text: str) -> None:
    prompt = app.query_one("ChatInput")
    prompt.value = text
    await pilot.press("enter")


async def _wait_until(pilot: Any, predicate: Any, timeout_s: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await pilot.pause(0.05)
    return predicate()


class TestInlineConfirm:
    def _chat_view(self, app: MommyTuiApp) -> ChatView:
        return app.query_one(ChatView)

    def test_deny(self) -> None:
        agent = _ReplayAgent()
        app = _make_app(agent)

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await _submit(pilot, app, "存策略卡")
                assert await _wait_until(pilot, self._chat_view(app).has_pending_confirm)
                await pilot.press("n")
                assert await _wait_until(pilot, lambda: bool(agent.decisions))
                assert agent.decisions == [False]
                assert not self._chat_view(app).has_pending_confirm()

        _run(scenario())

    def test_allow(self) -> None:
        agent = _ReplayAgent()
        app = _make_app(agent)

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await _submit(pilot, app, "存策略卡")
                assert await _wait_until(pilot, self._chat_view(app).has_pending_confirm)
                await pilot.press("y")
                assert await _wait_until(pilot, lambda: bool(agent.decisions))
                assert agent.decisions == [True]

        _run(scenario())

    def test_escape_denies(self) -> None:
        agent = _ReplayAgent()
        app = _make_app(agent)

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await _submit(pilot, app, "存策略卡")
                assert await _wait_until(pilot, self._chat_view(app).has_pending_confirm)
                await pilot.press("escape")
                assert await _wait_until(pilot, lambda: bool(agent.decisions))
                assert agent.decisions == [False]

        _run(scenario())

    def test_always_allows_rest_of_session(self) -> None:
        agent = _ReplayAgent()
        app = _make_app(agent)

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                # 第一轮：按 a 放行
                await _submit(pilot, app, "存策略卡")
                assert await _wait_until(pilot, self._chat_view(app).has_pending_confirm)
                await pilot.press("a")
                assert await _wait_until(pilot, lambda: bool(agent.decisions))
                assert agent.decisions == [True]
                # 第二轮：同工具直接放行，不再弹确认条
                await _wait_until(pilot, lambda: not app.query_one(ChatView)._busy)
                await _submit(pilot, app, "再存一次")
                assert await _wait_until(pilot, lambda: len(agent.decisions) == 2)
                assert agent.decisions == [True, True]
                assert not self._chat_view(app).has_pending_confirm()
                assert "strategy_save" in app._session_allowed_tools

        _run(scenario())

    def test_cancel_resolves_pending_confirm(self) -> None:
        """等待决定期间整轮被取消：确认条强制落定，on_confirm 返回 False。"""
        agent = _ReplayAgent()
        app = _make_app(agent)

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await _submit(pilot, app, "存策略卡")
                assert await _wait_until(pilot, self._chat_view(app).has_pending_confirm)
                cancel = app._cancel_event
                assert cancel is not None
                cancel.set()
                assert await _wait_until(pilot, lambda: bool(agent.decisions))
                assert agent.decisions == [False]
                assert not self._chat_view(app).has_pending_confirm()

        _run(scenario())

    def test_hint_bar_shows_confirm_mode(self) -> None:
        agent = _ReplayAgent()
        app = _make_app(agent)

        async def scenario() -> None:
            from mommy_chaogu.tui.widgets.hint_bar import HintBar

            async with app.run_test(size=(100, 30)) as pilot:
                await _submit(pilot, app, "存策略卡")
                assert await _wait_until(pilot, self._chat_view(app).has_pending_confirm)
                assert app.query_one(HintBar).mode == "confirm"
                await pilot.press("y")
                assert await _wait_until(pilot, lambda: bool(agent.decisions))
                # 决定后不再停留确认提示（轮次可能已结束回到 default）
                assert app.query_one(HintBar).mode != "confirm"

        _run(scenario())
