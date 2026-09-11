"""ToolIndicator — dexter 风格的工具调用指示器。

视觉语言（与 dexter / Claude Code 一致）：
    ⏺ 查行情("600519")        ← 进行中：圈点呼吸闪烁
    ⎿ 贵州茅台 1680.00 · -0.52% · 842ms   ← 完成：语义摘要 + 耗时
    ⏺ 查行情("600519")
    ⎿  Error: 超时             ← 失败：红圈 + 错误
    ⏺ 保存策略卡({...})
    ⎿ 已拒绝（用户）           ← 用户在内联确认条拒绝

已完成的调用可展开详情：点击指示器（或聚焦后按 Enter）展开
参数与结果预览，再点收起——对标 Kimi Code / Claude Code 的
工具轨迹展开交互。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Static

from mommy_chaogu.tui.services.colors import color, current_theme

# 工具名 → 中文显示名（覆盖 agent/tools/ 的全部工具）
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
    "manage_watchlist": "管理自选股",
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
    "strategy_save": "保存策略卡",
    "strategy_archive": "归档策略卡",
    "strategy_activate_monitor": "启用策略监控",
    "strategy_list": "查策略卡",
    "strategy_get": "查策略卡详情",
    "strategy_prepare_application": "准备策略应用",
    "strategy_prepare_monitor": "准备策略监控",
}

_CIRCLE = "⏺"
_DETAIL_PREFIX = "⎿  "


def _c(role: str) -> str:
    """当前主题的语义色（渲染时解析，支持中途 Ctrl+T 切主题）。"""
    return color(current_theme(), role)


_BLINK_INTERVAL_S = 0.6

# 展开详情里结果预览的行数上限（避免长结果撑爆对话流）
_MAX_RESULT_LINES = 30
_MAX_ARG_LINES = 8


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
    stripped = result.strip()
    first_line = stripped.splitlines()[0] if stripped else "完成"
    collapsed = " ".join(first_line.split())
    return truncate_at_word(collapsed, max_len)


def format_elapsed(elapsed_ms: int) -> str:
    """耗时格式化（dexter formatDuration）。"""
    if elapsed_ms < 1000:
        return f"{elapsed_ms}ms"
    return f"{elapsed_ms / 1000:.1f}s"


def _fmt_money(value: Any) -> str:
    """金额（元）→ 人话：亿 / 万。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e8:
        return f"{sign}{a / 1e8:.2g}亿"
    if a >= 1e4:
        return f"{sign}{a / 1e4:.0f}万"
    return f"{sign}{a:.0f}"


def _try_parse_json(result: str) -> Any:
    """工具结果文本 → JSON 对象（失败返回 None，调用方走 fallback）。"""
    if not result or not result.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return None


def _pct(value: Any) -> str:
    """涨跌幅/占比数值 → 带 % 的字符串（保留两位小数）。"""
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return ""


def _humanize_quote(d: dict[str, Any]) -> str:
    name = d.get("name") or d.get("code") or ""
    price = d.get("price")
    pct = _pct(d.get("change_pct"))
    parts = [str(name)]
    if price is not None:
        parts.append(f"{price}")
    if pct:
        parts.append(pct)
    return " ".join(p for p in parts if p)


def _humanize_flow(d: dict[str, Any]) -> str:
    main = d.get("main_net")
    if main is None:
        return ""
    direction = "净流出" if float(main) < 0 else "净流入"
    parts = [f"主力{direction} {_fmt_money(main)}"]
    ratio = d.get("main_net_ratio")
    if ratio is not None:
        parts.append(f"占比{abs(float(ratio)):.2f}%")
    name = d.get("name")
    if name:
        parts.insert(0, str(name))
    return " ".join(parts)


# 工具名 → 语义摘要提取器。返回空串时 fallback 到原始 JSON 首行。
SEMANTIC_DIGESTS: dict[str, Callable[[Any], str]] = {
    "get_quote": lambda d: _humanize_quote(d) if isinstance(d, dict) else "",
    "get_money_flow_today": lambda d: _humanize_flow(d) if isinstance(d, dict) else "",
    "get_money_flow_history": lambda d: f"{len(d)} 天记录" if isinstance(d, list) else "",
    "get_quotes": lambda d: f"{len(d)} 只报价" if isinstance(d, list) else "",
    "get_market_indexes": lambda d: f"{len(d)} 个指数" if isinstance(d, list) else "",
    "get_bars": (
        lambda d: (
            f"{len(d)} 根K线 · 最新收盘 {d[-1].get('close', '?')}"
            if isinstance(d, list) and d
            else ""
        )
    ),
    "search_news": lambda d: f"{len(d)} 条新闻" if isinstance(d, list) else "",
    "get_announcements": lambda d: f"{len(d)} 条公告" if isinstance(d, list) else "",
    "get_watchlist": lambda d: f"{len(d)} 只自选" if isinstance(d, list) else "",
    "get_sector_stocks": (
        lambda d: (
            f"{len(d.get('stocks') or d.get('items') or [])} 只成分股"
            if isinstance(d, dict)
            else ""
        )
    ),
    "get_fundamentals": (
        lambda d: (
            (
                " · ".join(
                    f"{k.upper()} {d[k]}" for k in ("pe", "pb") if isinstance(d, dict) and d.get(k)
                )
            )
            if isinstance(d, dict)
            else ""
        )
    ),
}


def format_digest(name: str, result: str, fallback_max_len: int = 60) -> str:
    """工具结果 → 人话摘要：优先按工具语义提取，失败回退 JSON 首行。"""
    extractor = SEMANTIC_DIGESTS.get(name)
    if extractor is not None:
        data = _try_parse_json(result)
        if data is not None:
            try:
                text = extractor(data)
            except Exception:  # 提取器对意外结构保持健壮
                text = ""
            if text:
                return truncate_at_word(text, fallback_max_len)
    return format_result_digest(result, fallback_max_len)


def _clip_lines(text: str, max_lines: int) -> tuple[str, bool]:
    """按行截断，返回 (文本, 是否被截断)。"""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]), True


def _pretty_result(result: str) -> str:
    """结果文本尽量 pretty-print（JSON 才有缩进，普通文本原样）。"""
    data = _try_parse_json(result)
    if data is not None:
        try:
            return json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            pass
    return result


class ToolIndicator(Vertical):
    """单个工具调用的实时状态指示（呼吸圈 → 完成/失败/拒绝）。"""

    can_focus = True

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("enter", "toggle_detail", "展开/收起详情", show=False),
        Binding("space", "toggle_detail", "展开/收起详情", show=False),
    ]

    def __init__(self, name: str, args_summary: str, args: dict[str, Any] | None = None) -> None:
        super().__init__(classes="tool-indicator")
        display = tool_display_name(name)
        self._tool_name = name
        self._title = f"{display}({args_summary})" if args_summary else display
        self._args = args or {}
        self._result = ""
        self._blink_on = True
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(classes="ti-header")
        yield Static(classes="ti-more")

    def on_mount(self) -> None:
        self._render_header(_c("info"), blink=True)
        self._timer = self.set_interval(_BLINK_INTERVAL_S, self._blink)

    def _blink(self) -> None:
        self._blink_on = not self._blink_on
        self._render_header(_c("info"), blink=True)

    def _render_header(self, color: str, *, blink: bool = False) -> None:
        circle = _CIRCLE if (not blink or self._blink_on) else " "
        header = Text(f"{circle} ", style=color)
        header.append(self._title)
        self.query_one(".ti-header", Static).update(header)

    # ── 详情展开（Kimi Code 式）─────────────────────────────────

    def on_click(self) -> None:
        """点击指示器任意位置切换详情展开。"""
        self.action_toggle_detail()

    def action_toggle_detail(self) -> None:
        """展开/收起参数与结果预览。"""
        if not self._result:
            return
        self.toggle_class("-expanded")
        more = self.query_one(".ti-more", Static)
        if self.has_class("-expanded"):
            more.update(self._build_detail())
        self.scroll_visible(animate=False)

    def _build_detail(self) -> Text:
        """详情内容：参数 + 结果预览（截断可见，不静默）。

        用 Text 分段而非 console markup：参数/结果是任意用户数据，
        不能被当标记解析（Textual Content 对行尾 ``\\[`` + 闭合标签
        有吞标签怪癖）。
        """
        content = Text()
        if self._args:
            args_text = json.dumps(self._args, ensure_ascii=False, indent=2)
            clipped, cut = _clip_lines(args_text, _MAX_ARG_LINES)
            note = " …（参数已截断）" if cut else ""
            content.append("参数:\n", style=_c("muted"))
            content.append(f"{clipped}{note}\n", style="dim")
        pretty = _pretty_result(self._result)
        clipped, cut = _clip_lines(pretty, _MAX_RESULT_LINES)
        note = " …（预览已截断，仅展示前 30 行）" if cut else ""
        content.append("结果:\n", style=_c("muted"))
        content.append(f"{clipped}{note}", style="dim")
        return content

    # ── 状态迁移 ────────────────────────────────────────────────

    def set_complete(
        self,
        digest: str,
        elapsed_ms: int,
        truncated: bool = False,
        *,
        result: str = "",
    ) -> None:
        """完成：圈点定型 + 追加 ⎿ 摘要 · 耗时 行（结果保留供展开查看）。

        *truncated* 为 True（结果被 agent 层截断，>8KB）时追加
        「（结果过大已截断）」——截断可见，不静默。
        """
        self._stop_timer()
        self._result = result
        self._render_header(_c("muted"))
        note = "（结果过大已截断）" if truncated else ""
        line = Text(_DETAIL_PREFIX, style=_c("muted"))
        line.append(digest)
        if note:
            line.append(note)
        line.append(f" · {format_elapsed(elapsed_ms)}")
        self.mount(Static(line, classes="ti-detail"))

    def set_error(self, error: str, elapsed_ms: int) -> None:
        """失败：红圈 + 追加 ⎿ Error 行。"""
        self._stop_timer()
        self._result = error
        self._render_header(_c("danger"))
        detail = truncate_at_word(" ".join(error.split()), 80)
        line = Text(_DETAIL_PREFIX, style=_c("muted"))
        line.append(f"Error: {detail}", style=_c("danger"))
        line.append(f" · {format_elapsed(elapsed_ms)}", style=_c("muted"))
        self.mount(Static(line, classes="ti-detail"))

    def set_denied(self) -> None:
        """用户在内联确认条拒绝了本次调用：黄圈 + ⎿ 已拒绝。"""
        self._stop_timer()
        self._render_header(_c("warning"))
        line = Text(_DETAIL_PREFIX, style=_c("muted"))
        line.append("已拒绝（用户）", style=_c("warning"))
        self.mount(Static(line, classes="ti-detail"))

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
