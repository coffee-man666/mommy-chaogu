"""HintBar — 输入框下方的上下文提示栏（dexter hint-bar 移植）。

五种状态：
  空闲:      / 命令 · @ 股票 · Enter 发送 · Esc 中断
  busy:      Esc 中断 · Enter 排队
  slash:     命令候选列表（高亮项 = Tab 将接受的那条）
  @联想:     股票候选列表（高亮项 = Tab 将插入的代码）
  6 位代码:  ⏎ 查看 600519 报价
"""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static

_MAX_SUGGESTIONS = 5


class HintBar(Static):
    """单行/多行上下文提示（默认一行，候选列表时展开）。"""

    def __init__(self) -> None:
        super().__init__(classes="hint-bar")
        self._mode = "default"

    def on_mount(self) -> None:
        self.show_default()

    def show_default(self) -> None:
        self._mode = "default"
        self.update("[#8a8f98] / 命令 · @ 股票 · Enter 发送 · ↑ 历史 · Esc 中断[/]")

    def show_busy(self) -> None:
        self._mode = "busy"
        self.update("[#8a8f98] Esc 中断 · Enter 排队[/]")

    def show_suggestions(self, matches: list[tuple[str, str]], selected: int = 0) -> None:
        """slash 输入时展示候选命令（name, description 列表），高亮选中项。"""
        self._mode = "suggestions"
        lines: list[str] = []
        start = min(
            max(0, selected - _MAX_SUGGESTIONS + 1),
            max(0, len(matches) - _MAX_SUGGESTIONS),
        )
        for i, (name, desc) in enumerate(matches[start : start + _MAX_SUGGESTIONS], start=start):
            if i == selected:
                lines.append(f"[#79b8ff]> /{escape(name)}[/][#8a8f98] — {escape(desc)}[/]")
            else:
                lines.append(f"[#8a8f98]  /{escape(name)} — {escape(desc)}[/]")
        self.update("\n".join(lines))

    def show_stock_suggestions(self, matches: list[tuple[str, str]], selected: int = 0) -> None:
        """@ 输入时展示股票候选（code, name 列表），高亮选中项。"""
        self._mode = "stock-suggestions"
        lines: list[str] = []
        start = min(
            max(0, selected - _MAX_SUGGESTIONS + 1),
            max(0, len(matches) - _MAX_SUGGESTIONS),
        )
        for i, (code, name) in enumerate(matches[start : start + _MAX_SUGGESTIONS], start=start):
            label = escape(f"{code} {name}".rstrip())
            if i == selected:
                lines.append(f"[#79b8ff]> {label}[/]")
            else:
                lines.append(f"[#8a8f98]  {label}[/]")
        self.update("\n".join(lines))

    def show_code_hint(self, code: str) -> None:
        """输入完整 6 位代码时提示 Enter 直接看报价。"""
        self._mode = "code-hint"
        self.update(f"[#8a8f98] ⏎ 查看 {escape(code)} 报价[/]")

    @property
    def mode(self) -> str:
        return self._mode
