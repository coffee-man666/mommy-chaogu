"""WorkingIndicator — "思考中" 工作指示器（dexter working-indicator 本土化）。

    ⠹ 盯盘中… (12s)
    ⠹ 盯盘中… (12s · ↓ 1.2k tokens)

spinner 帧循环 + 每次 busy 随机一个炒股语境动词 + 实时耗时 + 可选 token 统计。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

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


def _format_tokens(n: int) -> str:
    """token 数 → dexter 风格紧凑显示（1.2k / 850）。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class WorkingIndicator(Static):
    """busy 期间挂载到对话流末尾；busy 结束移除。

    可选 set_stats_provider 注册一个 callable，每次 tick 调用它获取
    当前 turn 的 token 统计 dict（含 total_tokens 或 completion_tokens），
    在耗时后追加显示。
    """

    def __init__(self) -> None:
        super().__init__(classes="working-indicator")
        self._verb = random_thinking_verb()
        self._frame_idx = 0
        self._started = time.monotonic()
        self._timer: Timer | None = None
        self._stats_provider: Callable[[], dict[str, Any]] | None = None

    def on_mount(self) -> None:
        self._refresh_text()
        self._timer = self.set_interval(_TICK_INTERVAL_S, self._tick)

    def set_stats_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        """注册 token 统计来源（worker 线程更新的共享 dict 或 callable）。"""
        self._stats_provider = provider

    def _tick(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(_SPINNER_FRAMES)
        self._refresh_text()

    def _refresh_text(self) -> None:
        frame = _SPINNER_FRAMES[self._frame_idx]
        elapsed = int(time.monotonic() - self._started)
        parts: list[str] = [f"[#79b8ff]{frame} {self._verb}…[/]"]
        # 后缀：耗时 + 可选 token 统计
        suffix_parts: list[str] = []
        if elapsed >= 1:
            suffix_parts.append(f"{elapsed}s")
        if self._stats_provider is not None:
            with _safe_stats(self._stats_provider) as stats:
                if stats:
                    tokens = stats.get("total_tokens") or stats.get("completion_tokens") or 0
                    if tokens:
                        suffix_parts.append(f"↓ {_format_tokens(int(tokens))} tokens")
        if suffix_parts:
            parts.append(f"[#8a8f98]({' · '.join(suffix_parts)})[/]")
        self.update("".join(parts))

    def stop_timer(self) -> None:
        """停止帧动画（移除前调用，避免 timer 泄漏）。"""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None


class _SafeStatsContext:
    """安全调用 stats_provider：异常时返回空 dict（主线程不应因统计报错崩溃）。"""

    def __init__(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._provider = provider
        self.stats: dict[str, Any] = {}

    def __enter__(self) -> dict[str, Any]:
        try:
            self.stats = self._provider() or {}
        except Exception:
            self.stats = {}
        return self.stats

    def __exit__(self, *args: object) -> None:
        pass


def _safe_stats(provider: Callable[[], dict[str, Any]]) -> _SafeStatsContext:
    return _SafeStatsContext(provider)
