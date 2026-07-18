"""HintBar — 输入框下方的上下文提示栏（dexter hint-bar 移植）。

三种状态：
  空闲:    / 命令 · Tab 看板 · ? 帮助
  busy:    esc 中断
  slash:   命令候选列表（第一条高亮 = Tab 将接受的那条）
"""

from __future__ import annotations

from textual.widgets import Static

_MAX_SUGGESTIONS = 5


class HintBar(Static):
    """单行/多行上下文提示（默认一行，slash 候选时展开）。"""

    def __init__(self) -> None:
        super().__init__(classes="hint-bar")
        self._mode = "default"

    def on_mount(self) -> None:
        self.show_default()

    def show_default(self) -> None:
        self._mode = "default"
        self.update("[#8a8f98] / 命令 · Tab 看板 · ? 帮助[/]")

    def show_busy(self) -> None:
        self._mode = "busy"
        self.update("[#8a8f98] esc 中断[/]")

    def show_suggestions(self, matches: list[tuple[str, str]], selected: int = 0) -> None:
        """slash 输入时展示候选命令（name, description 列表），高亮选中项。"""
        self._mode = "suggestions"
        lines: list[str] = []
        for i, (name, desc) in enumerate(matches[:_MAX_SUGGESTIONS]):
            if i == selected:
                lines.append(f"[#79b8ff]> /{name}[/][#8a8f98] — {desc}[/]")
            else:
                lines.append(f"[#8a8f98]  /{name} — {desc}[/]")
        self.update("\n".join(lines))

    @property
    def mode(self) -> str:
        return self._mode
