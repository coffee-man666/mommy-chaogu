"""TUI Pilot smoke test.

Boot the app with FakeServices, verify ContentSwitcher starts at 'dashboard',
press Tab → switches to 'chat', press Tab again → back to 'dashboard'.

pytest-asyncio is not a project dependency, so we drive the async run_test()
via asyncio.run() inside a normal sync test function.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import FakeServices


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


class TestAppInstantiation:
    """Verify the app can be constructed without external resources."""

    def test_app_construction(self) -> None:
        app = MommyTuiApp(services=FakeServices.create())
        assert app.services is not None
        assert app.services.data.source_label() == "东方财富 实时"


# ---------------------------------------------------------------------------
# Pilot smoke test via asyncio.run (no pytest-asyncio needed)
# ---------------------------------------------------------------------------


async def _pilot_smoke() -> None:
    app = MommyTuiApp(services=FakeServices.create())
    async with app.run_test() as pilot:
        from textual.widgets import ContentSwitcher

        switcher = app.query_one("#main", ContentSwitcher)

        # (c) starts at 'dashboard'
        assert switcher.current == "dashboard", (
            f"Expected initial view 'dashboard', got '{switcher.current}'"
        )

        # (d) Tab → 'chat'
        await pilot.press("tab")
        await pilot.pause()
        assert switcher.current == "chat", (
            f"Expected 'chat' after first Tab, got '{switcher.current}'"
        )

        # (e) Tab again → back to 'dashboard'
        await pilot.press("tab")
        await pilot.pause()
        assert switcher.current == "dashboard", (
            f"Expected 'dashboard' after second Tab, got '{switcher.current}'"
        )


def test_pilot_tab_switch() -> None:
    """Tab cycles dashboard → chat → dashboard."""
    asyncio.run(_pilot_smoke())
