"""TopBar widget — 品牌 + 模式 + 连接点 + 来源 + 市场阶段 + 时钟（§6.1）。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from textual.reactive import reactive
from textual.widgets import Static

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def market_phase() -> str:
    """判断当前市场阶段（Asia/Shanghai 时区）。"""
    now = datetime.now(_SHANGHAI)
    h, m = now.hour, now.minute
    wd = now.weekday()
    if wd >= 5:
        return "已收盘"
    hm = h * 60 + m
    if 555 <= hm < 565:  # 9:15-9:25
        return "集合竞价"
    if 570 <= hm < 690 or 780 <= hm < 900:  # 9:30-11:30, 13:00-15:00
        return "交易中"
    if 690 <= hm < 780:  # 11:30-13:00
        return "午休"
    return "已收盘"


class TopBar(Static):
    """顶部状态栏。"""

    connection_level: reactive[str] = reactive("live")
    source_label: reactive[str] = reactive("加载中…")
    market_phase: reactive[str] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self._clock = ""

    def on_mount(self) -> None:
        self.market_phase = market_phase()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self._clock = datetime.now(_SHANGHAI).strftime("%H:%M:%S")
        self.market_phase = market_phase()
        self._refresh_display()

    def watch_connection_level(self, _level: str) -> None:
        self._refresh_display()

    def watch_source_label(self, _label: str) -> None:
        self._refresh_display()

    def watch_market_phase(self, _phase: str) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        dot = {"live": "🟢", "degraded": "🟡", "offline": "🔴"}.get(self.connection_level, "⚪")
        parts = [
            "[bold]mommy-chaogu[/]",
            f"{dot} {self.source_label}",
            f"[dim]{self.market_phase}[/]",
            f"[dim]{self._clock}[/]",
        ]
        self.update("  ".join(parts))

