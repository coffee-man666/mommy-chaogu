"""ToolIndicator — dexter 风格的工具调用指示器。

视觉语言（与 dexter / Claude Code 一致）：
    ⏺ 查行情("600519")        ← 进行中：圈点呼吸闪烁
    ⎿  返回最新报价 · 1.2s     ← 完成：结果摘要 + 耗时
    ⏺ 查行情("600519")
    ⎿  Error: 超时             ← 失败：红圈 + 错误
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Static

# 工具名 → 中文显示名（覆盖 agent/tools/ 的 24 个工具）
TOOL_DISPLAY_NAMES: dict[str, str] = {
    "get_quote": "查行情",
    "get_quotes": "批量查行情",
    "get_market_indexes": "查大盘指数",
    "get_sector_ranking": "查板块排行",
    "search_sector": "搜板块",
    "get_sector_stocks": "查板块成分股",
    "get_money_flow_today": "查今日资金流",
    "get_money_flow_history": "查资金流历史",
    "get_bars": "查K线",
    "get_watchlist": "查自选股",
    "get_portfolio": "查持仓",
    "search_news": "搜新闻",
    "get_announcements": "查公告",
    "get_longhuban": "查龙虎榜",
    "get_fundamentals": "查基本面",
    "get_portfolio_analysis": "持仓分析",
    "backfill_history": "补历史数据",
    "manage_alert": "管理告警",
    "search_similar_events": "搜相似事件",
    "get_prediction_history": "查预测记录",
    "get_market_narrative": "查市场叙事",
    "list_themes": "查主题列表",
    "get_theme_stocks": "查主题个股",
    "get_memory_context": "查记忆",
}

_CIRCLE = "⏺"
_DETAIL_PREFIX = "⎿  "

_COLOR_ACTIVE = "#79b8ff"
_COLOR_OK = "#8a8f98"
_COLOR_ERROR = "#e5484d"

_BLINK_INTERVAL_S = 0.6


def tool_display_name(name: str) -> str:
    """工具英文名 → 中文显示名（未知工具 fallback 到下划线转空格）。"""
    return TOOL_DISPLAY_NAMES.get(name, name.replace("_", " "))


def truncate_at_word(text: str, max_len: int) -> str:
    """在词边界截断（对标 dexter truncateAtWord）。"""
    if len(text) <= max_len:
        return text
    cut = text.rfind(" ", 0, max_len)
    if cut > max_len * 0.5:
        return text[:cut] + "…"
    return text[:max_len] + "…"


def format_tool_args(args: dict[str, Any]) -> str:
    """格式化工具参数用于单行展示。

    query 类参数显示为 "..."；其余 k=v 拼接，单值最长 40 字符。
    """
    if not args:
        return ""
    query = args.get("query")
    if isinstance(query, str):
        return f'"{truncate_at_word(query, 40)}"'
    parts: list[str] = []
    for key, value in args.items():
        if isinstance(value, str):
            parts.append(f"{key}={truncate_at_word(value, 40)}")
        elif isinstance(value, (int, float, bool)):
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def format_result_digest(result: str, max_len: int = 60) -> str:
    """工具结果 → 单行摘要：取首行、压缩空白、截断。"""
    first_line = result.strip().splitlines()[0] if result.strip() else "完成"
    collapsed = " ".join(first_line.split())
    return truncate_at_word(collapsed, max_len)


def format_elapsed(elapsed_ms: int) -> str:
    """耗时格式化（dexter formatDuration）。"""
    if elapsed_ms < 1000:
        return f"{elapsed_ms}ms"
    return f"{elapsed_ms / 1000:.1f}s"


class ToolIndicator(Vertical):
    """单个工具调用的实时状态指示（呼吸圈 → 完成/失败）。"""

    def __init__(self, name: str, args_summary: str) -> None:
        super().__init__(classes="tool-indicator")
        display = tool_display_name(name)
        self._title = f"{display}({args_summary})" if args_summary else display
        self._blink_on = True
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(classes="ti-header")

    def on_mount(self) -> None:
        self._render_header(_COLOR_ACTIVE, blink=True)
        self._timer = self.set_interval(_BLINK_INTERVAL_S, self._blink)

    def _blink(self) -> None:
        self._blink_on = not self._blink_on
        self._render_header(_COLOR_ACTIVE, blink=True)

    def _render_header(self, color: str, *, blink: bool = False) -> None:
        circle = _CIRCLE if (not blink or self._blink_on) else " "
        self.query_one(".ti-header", Static).update(f"[{color}]{circle}[/] {self._title}")

    def set_complete(self, digest: str, elapsed_ms: int) -> None:
        """完成：圈点定型 + 追加 ⎿ 摘要 · 耗时 行。"""
        self._stop_timer()
        self._render_header(_COLOR_OK)
        self.mount(
            Static(
                f"[{_COLOR_OK}]{_DETAIL_PREFIX}{digest} · {format_elapsed(elapsed_ms)}[/]",
                classes="ti-detail",
            )
        )

    def set_error(self, error: str, elapsed_ms: int) -> None:
        """失败：红圈 + 追加 ⎿ Error 行。"""
        self._stop_timer()
        self._render_header(_COLOR_ERROR)
        detail = truncate_at_word(" ".join(error.split()), 80)
        self.mount(
            Static(
                f"[{_COLOR_OK}]{_DETAIL_PREFIX}[{_COLOR_ERROR}]Error: {detail}[/]"
                f"[{_COLOR_OK}] · {format_elapsed(elapsed_ms)}[/]",
                classes="ti-detail",
            )
        )

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
