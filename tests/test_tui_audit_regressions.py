"""TUI 2026-07-25 体检报告的回归测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import AgentBridge, DataService, FakeServices
from mommy_chaogu.tui.views.chat import _CODE_RE, ChatView
from mommy_chaogu.tui.widgets import cards
from mommy_chaogu.tui.widgets.hint_bar import HintBar


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


async def _wait_for(pilot: Any, predicate: Any, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await pilot.pause(0.02)
        if predicate():
            return True
    return False


def test_dynamic_markup_is_escaped() -> None:
    async def _test() -> None:
        app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            chat = app.query_one(ChatView)
            dangerous = "[/red] [link=https://example.test]"
            chat.append_user(dangerous)
            chat.append_hint(dangerous)
            chat.append_workflow_match(dangerous, [dangerous])
            chat.mount_card(
                cards.watch_card(
                    [
                        {
                            "code": "600519",
                            "name": dangerous,
                            "price": Decimal("1"),
                            "change_pct": Decimal("0"),
                            "main_flow": None,
                        }
                    ]
                )
            )
            await pilot.pause()
            assert len(chat.query(".user-msg")) == 1
            assert len(chat.query(".hint-card")) == 1
            assert len(chat.query(".workflow-card")) == 1
            assert len(chat.query(".watch-card")) == 1

    _run(_test())


def test_clear_is_atomic_on_fresh_and_busy_chat() -> None:
    async def _test() -> None:
        app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            chat = app.query_one(ChatView)
            chat.set_busy(True)
            chat.clear_messages()
            assert await _wait_for(
                pilot,
                lambda: len(chat.query("#chat-welcome")) == 1 and not chat._busy,
            )
            assert chat._working is None
            chat.clear_messages()
            assert await _wait_for(pilot, lambda: len(chat.query("#chat-welcome")) == 1)

    _run(_test())


def test_portfolio_card_reads_production_nested_position() -> None:
    summary = {
        "positions": [
            {
                "position": SimpleNamespace(code="600519", name="贵州茅台"),
                "avg_cost": Decimal("1500"),
                "current_price": Decimal("1600"),
                "unrealized_pnl": Decimal("1000"),
            }
        ],
        "total_market_value": Decimal("16000"),
        "total_unrealized_pnl": Decimal("1000"),
    }
    content = str(cards.portfolio_card(summary).content)
    assert "600519" in content
    assert "贵州茅台" in content


def test_fullwidth_digits_are_not_stock_codes() -> None:
    assert _CODE_RE.fullmatch("600519")
    assert not _CODE_RE.fullmatch("６００５１９")


def test_hidden_suggestion_selection_scrolls_into_view() -> None:
    async def _test() -> None:
        app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            chat = app.query_one(ChatView)
            prompt = chat.query_one("#prompt")
            prompt.value = "/"  # type: ignore[attr-defined]
            await pilot.pause()
            for _ in range(10):
                chat.cycle_selection(1)
            selected = chat.selected_completion()
            assert selected is not None
            hint = str(chat.query_one(HintBar).content)
            assert selected.strip() in hint

    _run(_test())


def test_watchlist_quote_failure_is_not_reported_as_empty() -> None:
    class BrokenAdapter:
        def get_quotes(self, codes: list[str]) -> list[Any]:
            raise TimeoutError

        def get_today_money_flow(self, code: str) -> list[Any]:
            return []

        def format_source_label(self) -> str:
            return ""

    store = SimpleNamespace(get_all_codes=lambda: ["600519"])
    rows = DataService(adapter=BrokenAdapter(), watchlist_store=store).watchlist_quotes()
    assert rows[0]["quote_unavailable"] is True
    content = str(cards.watch_card(rows).content)
    assert "行情源暂时不可用" in content
    assert "还没有自选股" not in content


def test_agent_receives_bounded_conversation_history() -> None:
    class HistoryAgent:
        def __init__(self) -> None:
            self.histories: list[list[dict[str, str]]] = []

        def chat(self, message: str, history: Any = None, **kwargs: Any) -> Any:
            self.histories.append(list(history or []))
            return SimpleNamespace(
                text=f"回答：{message}", usage={}, interrupted=False, tool_calls=[], rounds=1
            )

    async def _test() -> None:
        agent = HistoryAgent()
        services = FakeServices.create()
        services.agent = AgentBridge(_agent=agent)
        app = MommyTuiApp(services=services)  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            chat = app.query_one(ChatView)
            app.handle_chat_message("第一问")
            assert await _wait_for(pilot, lambda: not chat._busy)
            app.handle_chat_message("它呢？")
            assert await _wait_for(pilot, lambda: not chat._busy)
            assert agent.histories[0] == []
            assert agent.histories[1] == [
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "回答：第一问"},
            ]

    _run(_test())
