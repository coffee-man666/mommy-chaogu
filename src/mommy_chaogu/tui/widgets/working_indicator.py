"""WorkingIndicator — "思考中" 工作指示器（dexter working-indicator 本土化）。

    ⠹ 盯盘中… (12s)

spinner 帧循环 + 每次 busy 随机一个炒股语境动词 + 实时耗时。
"""

from __future__ import annotations

import random
import time

from textual.timer import Timer
from textual.widgets import Static

# 中文思考动词表（对标 dexter THINKING_VERBS，贴合 A 股语境）
THINKING_VERBS: list[str] = [
    "盯盘中",
    "复盘中",
    "翻财报中",
    "算估值中",
    "看资金流中",
    "扒数据中",
    "查公告中",
    "扫板块中",
    "琢磨中",
    "研判中",
    "对账中",
    "推演中",
]

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_TICK_INTERVAL_S = 0.1


def random_thinking_verb() -> str:
    return random.choice(THINKING_VERBS)


class WorkingIndicator(Static):
    """busy 期间挂载到对话流末尾；busy 结束移除。"""

    def __init__(self) -> None:
        super().__init__(classes="working-indicator")
        self._verb = random_thinking_verb()
        self._frame_idx = 0
        self._started = time.monotonic()
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._refresh_text()
        self._timer = self.set_interval(_TICK_INTERVAL_S, self._tick)

    def _tick(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(_SPINNER_FRAMES)
        self._refresh_text()

    def _refresh_text(self) -> None:
        frame = _SPINNER_FRAMES[self._frame_idx]
        elapsed = int(time.monotonic() - self._started)
        suffix = f" ({elapsed}s)" if elapsed >= 1 else ""
        self.update(f"[#79b8ff]{frame} {self._verb}…[/][#8a8f98]{suffix}[/]")

    def stop_timer(self) -> None:
        """停止帧动画（移除前调用，避免 timer 泄漏）。"""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
