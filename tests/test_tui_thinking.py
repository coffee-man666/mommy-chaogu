"""切片 B2：思考过程折叠展示（ThinkingBlock + ChatView 接线）。

产品行为：推理模型（deepseek-reasoner 等）思考时，回答上方出现
「✻ 思考中…」活动块；开始出正文后自动收起为「✻ 思考完成 · N 字」，
点击/Enter 可展开查看思考全文（暗色、限行）。普通模型不出现该块。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import FakeServices
from mommy_chaogu.tui.views.chat import ChatView
from mommy_chaogu.tui.widgets.thinking import ThinkingBlock


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class TestThinkingLifecycle:
    @staticmethod
    def _app() -> MommyTuiApp:
        return MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]

    def test_active_then_auto_finalize_on_answer(self) -> None:
        async def _test() -> None:
            app = self._app()
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.start_thinking()
                chat.append_thinking("先拆解问题…")
                chat.append_thinking("再查数据…")
                chat.flush_stream()
                await pilot.pause()

                blocks = chat.query(ThinkingBlock)
                assert len(blocks) == 1
                assert blocks[0].has_class("-active")
                assert "思考中" in str(blocks[0].query_one(".th-header").content)  # type: ignore[attr-defined]

                # 首个正文 chunk 到达 → 自动收起
                chat.append_chunk("答案开始")
                chat.flush_stream()
                await pilot.pause()

                block = chat.query_one(ThinkingBlock)
                assert not block.has_class("-active")
                header = str(block.query_one(".th-header").content)  # type: ignore[attr-defined]
                assert "思考完成" in header
                # 字数按思考全文计（两段 delta 共 11 字）
                assert "11" in header

        _run(_test())

    def test_toggle_expands_reasoning_text(self) -> None:
        async def _test() -> None:
            app = self._app()
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.start_thinking()
                chat.append_thinking("推理全文第一行")
                chat.append_thinking("第二行")
                chat.append_chunk("答")
                await pilot.pause()

                block = chat.query_one(ThinkingBlock)
                body = block.query_one(".th-body")
                assert "推理全文第一行" not in str(body.content)  # type: ignore[attr-defined]

                block.action_toggle_detail()
                await pilot.pause()
                assert "推理全文第一行" in str(body.content)  # type: ignore[attr-defined]
                assert "第二行" in str(body.content)  # type: ignore[attr-defined]

                block.action_toggle_detail()
                await pilot.pause()
                assert "推理全文第一行" not in str(body.content)  # type: ignore[attr-defined]

        _run(_test())

    def test_no_answer_then_interrupt_finalizes(self) -> None:
        """思考途中被中断（永远等不到正文）：busy 结束时收起，不留悬空活动块。"""

        async def _test() -> None:
            app = self._app()
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.set_busy(True)
                chat.start_thinking()
                chat.append_thinking("想到一半")
                chat.set_busy(False)
                await pilot.pause()

                block = chat.query_one(ThinkingBlock)
                assert not block.has_class("-active")

        _run(_test())

    def test_plain_turn_has_no_thinking_block(self) -> None:
        """普通模型整轮不触发思考回调：对话流里没有 ThinkingBlock。"""

        async def _test() -> None:
            app = self._app()
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.append_chunk("直接回答")
                chat.flush_stream()
                await pilot.pause()
                assert len(chat.query(ThinkingBlock)) == 0

        _run(_test())


class TestAppThinkingWiring:
    """app → agent 的 on_thinking 回调链路（真实轮次生命周期）。"""

    def test_turn_with_reasoning_shows_and_collapses_block(self) -> None:
        from types import SimpleNamespace

        services = FakeServices.create()

        def _chat(message: str, **kwargs: Any) -> Any:
            on_thinking = kwargs.get("on_thinking")
            assert on_thinking is not None, "app 必须向 agent 层传 on_thinking"
            on_thinking("思考甲")
            on_thinking("思考乙")
            on_chunk = kwargs.get("on_chunk")
            assert on_chunk is not None
            on_chunk("正式回答")
            return SimpleNamespace(
                text="正式回答", interrupted=False, usage={}, reasoning="思考甲思考乙"
            )

        services.agent.route = lambda text: None  # type: ignore[method-assign]
        services.agent.has_agent = lambda: True  # type: ignore[method-assign]
        services.agent.chat = _chat  # type: ignore[method-assign]
        services.agent.watch_background = lambda on_done: False  # type: ignore[method-assign]

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test(size=(110, 30)) as pilot:
                chat = app.query_one(ChatView)
                prompt = app.query_one("ChatInput")
                prompt.value = "问点难的"
                await pilot.press("enter")
                deadline = asyncio.get_running_loop().time() + 4
                while asyncio.get_running_loop().time() < deadline:
                    blocks = chat.query(ThinkingBlock)
                    if blocks and not blocks[0].has_class("-active"):
                        break
                    await pilot.pause(0.05)
                block = chat.query_one(ThinkingBlock)
                assert not block.has_class("-active")
                assert "6" in str(block.query_one(".th-header").content)  # type: ignore[attr-defined]

        _run(_test())


class TestKeyboardFocusCycle:
    """无候选时 Tab 把焦点让给对话流 widget（键盘可展开思考块）。"""

    def test_tab_moves_focus_to_thinking_block_and_enter_expands(self) -> None:
        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test(size=(110, 30)) as pilot:
                chat = app.query_one(ChatView)
                chat.start_thinking()
                chat.append_thinking("键盘展开验证")
                chat.append_chunk("答")
                chat.flush_stream()
                await pilot.pause()

                prompt = app.query_one("ChatInput")
                prompt.focus()
                # 第一次 Tab 落到 chat-log 滚动容器（容器导航），第二次进思考块
                await pilot.press("tab")
                await pilot.press("tab")
                from textual.widgets import Input

                assert not isinstance(app.focused, Input)
                focused = app.focused
                assert focused is not None and focused.has_class("thinking-block")
                await pilot.press("enter")
                await pilot.pause()
                assert focused.has_class("-expanded")  # type: ignore[union-attr]
                body = focused.query_one(".th-body").content  # type: ignore[union-attr]
                assert "键盘展开验证" in str(body)

        _run(_test())
