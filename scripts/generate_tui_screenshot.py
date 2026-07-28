"""Generate the README TUI screenshot with deterministic fake services."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input

from mommy_chaogu.tui.app import MommyTuiApp
from mommy_chaogu.tui.services.bootstrap import FakeServices
from mommy_chaogu.tui.views.chat import ChatView


async def generate() -> None:
    output_dir = Path("docs/images")
    output_dir.mkdir(parents=True, exist_ok=True)
    app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
    async with app.run_test(size=(120, 38)) as pilot:
        chat = app.query_one(ChatView)
        prompt = chat.query_one("#prompt", Input)
        prompt.value = "/today"
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.05)
            if len(chat.query(".overview-card")) == 1:
                break
        app.save_screenshot(filename="tui-conversation.svg", path=str(output_dir))


if __name__ == "__main__":
    asyncio.run(generate())
