"""切片 C：无 AI Key 时的首启引导卡。

产品行为：未配置 Provider/Key 启动 TUI 时，除欢迎卡外渲染一张可操作的
引导卡——先告诉用户哪些能力立刻能用（数据命令），再给出一分钟配置路径
（uv run mommy setup）。配置了 AI 则完全不出现。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import FakeServices
from mommy_chaogu.tui.views.chat import ChatView


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class TestFirstRunOnboarding:
    def test_no_agent_mounts_onboarding_card(self) -> None:
        services = FakeServices.create()  # 默认 AgentBridge 无 agent

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                chat = app.query_one(ChatView)
                cards = chat.query(".onboarding-card")
                assert len(cards) == 1
                content = str(cards[0].content)  # type: ignore[attr-defined]
                # 可操作：给出确切命令与示例
                assert "mommy setup" in content
                assert "/quote" in content
                assert "/today" in content

        _run(_test())

    def test_agent_present_skips_onboarding(self) -> None:
        services = FakeServices.create()
        services.agent.has_agent = lambda: True  # type: ignore[method-assign]

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                chat = app.query_one(ChatView)
                assert len(chat.query(".onboarding-card")) == 0

        _run(_test())
