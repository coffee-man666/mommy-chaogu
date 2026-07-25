"""TopBar widget — 指数快照 + AI 状态点 + 时钟（§1.2⑤）。

    沪指 3,847.51 ▲0.6% · AI🟢 deepseek · 14:32:05
    指数 —             · AI⚪ 未配置      · 14:32:05

启动即知 agent 是否可用（不再只记日志）。指数快照由 app 的后台 worker
周期性喂入（set_index）；AI 状态在启动时按 AgentBridge.provider_name 设置。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from textual.reactive import reactive
from textual.widgets import Static

from mommy_chaogu.tui.services.formatting import change_arrow, change_color, format_change_pct

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
    """顶部状态栏：指数快照 · AI 状态 · 时间。"""

    ai_label: reactive[str] = reactive("AI⚪ 未配置")

    def __init__(self) -> None:
        super().__init__()
        self._clock = ""
        self._index: dict[str, Any] | None = None
        self._theme = "dark"

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self._clock = datetime.now(_SHANGHAI).strftime("%H:%M:%S")
        self._refresh_display()

    def watch_ai_label(self, _label: str) -> None:
        self._refresh_display()

    def set_index(self, name: str, price: Any, change_pct: Any) -> None:
        """喂入指数快照（app 的 worker 线程经 call_from_thread 调用）。"""
        self._index = {"name": name, "price": price, "change_pct": change_pct}
        self._refresh_display()

    def set_theme(self, theme: str) -> None:
        """主题切换后重渲染涨跌颜色。"""
        self._theme = theme
        self._refresh_display()

    def _index_text(self) -> str:
        if self._index is None:
            return "[dim]指数 —[/]"
        name = str(self._index.get("name", ""))
        short = name.replace("指数", "")[:2] if name else "指数"
        price = self._index.get("price")
        price_str = f"{float(price):,.2f}" if price is not None else "—"
        pct = self._index.get("change_pct")
        color = change_color(pct, self._theme)
        change_str = f"{change_arrow(pct)} {format_change_pct(pct)}"
        return f"{short} {price_str} [{color}]{change_str}[/{color}]"

    def _refresh_display(self) -> None:
        parts = [
            self._index_text(),
            f"[dim]·[/] {self.ai_label}",
            f"[dim]· {self._clock}[/]",
        ]
        self.update(" ".join(parts))
