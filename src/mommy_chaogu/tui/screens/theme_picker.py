"""ThemePickerScreen — 主题选择器：↑↓ 实时预览，Enter 确认，Esc 还原。

预览回调由 App 注入（on_preview/on_confirm），本屏不持有主题逻辑；
Esc 取消时先回调还原 original，再关屏。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class ThemePickerScreen(ModalScreen[None]):
    """主题选择弹窗：高亮即预览。"""

    DEFAULT_CSS = """
    ThemePickerScreen {
        align: center middle;
        #theme-dialog {
            width: 52;
            height: auto;
            max-height: 80%;
            background: $surface;
            border: round $primary;
            padding: 0 1;
        }
        #theme-hint {
            color: $text-muted;
            text-align: center;
        }
        #theme-list {
            height: auto;
            max-height: 14;
            background: $surface;
        }
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel_theme", "取消（还原）")]

    def __init__(
        self,
        options: list[tuple[str, str]],
        original: str,
        on_preview: Callable[[str], None],
        on_confirm: Callable[[str], None],
    ) -> None:
        """options: (theme_id, 展示文本)；original: 打开时的主题（Esc 还原用）。"""
        super().__init__()
        self._options = options
        self._original = original
        self._on_preview = on_preview
        self._on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Static("↑↓ 实时预览 · Enter 确认 · Esc 还原", id="theme-hint")
            yield OptionList(
                *[Option(prompt, id=tid) for tid, prompt in self._options],
                id="theme-list",
            )

    def on_mount(self) -> None:
        option_list = self.query_one("#theme-list", OptionList)
        option_list.border_title = "选择主题"
        for idx, (tid, _) in enumerate(self._options):
            if tid == self._original:
                option_list.highlighted = idx  # 触发一次预览（同主题，无副作用）
                break

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self._on_preview(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._on_confirm(event.option.id or self._original)
        self.dismiss()

    def action_cancel_theme(self) -> None:
        self._on_preview(self._original)
        self.dismiss()
