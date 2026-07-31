"""Kimi Code 风格的 REPL 输入组件。

上方对话继续使用终端滚动区；这里只接管当前输入框、补全菜单和底部状态栏。
"""

from __future__ import annotations

from collections.abc import Callable

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    BufferControl,
    Dimension,
    Float,
    FloatContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

_COMMANDS = [
    "/help",
    "/clear",
    "/status",
    "/model",
    "/tui",
    "/web",
    "/quit",
]


class ReplPrompt:
    """可重复运行的有边框输入框，保留本次会话的历史记录。"""

    def __init__(
        self,
        *,
        model_label: str,
        cwd_label: str,
        status_provider: Callable[[], str] | None = None,
    ) -> None:
        self.model_label = model_label
        self.cwd_label = cwd_label
        self._status_provider = status_provider
        self._history = InMemoryHistory()
        self._completer = WordCompleter(_COMMANDS, ignore_case=True, sentence=True)
        self._style = Style.from_dict(
            {
                "frame.border": "#6b7280",
                "frame.label": "bold #7c5cff",
                "prompt": "bold #7c5cff",
                "input": "#f3f4f6",
                "toolbar": "bg:#20242c #aeb4bf",
                "toolbar.model": "bg:#20242c bold #e5e7eb",
                "toolbar.hint": "bg:#20242c #7f8794",
                "completion-menu.completion": "bg:#20242c #d1d5db",
                "completion-menu.completion.current": "bg:#7c5cff #ffffff",
                "completion-menu.meta.completion": "bg:#20242c #7f8794",
                "completion-menu.meta.completion.current": "bg:#7c5cff #ffffff",
            }
        )

    def _toolbar(self) -> StyleAndTextTuples:
        state = self._status_provider() if self._status_provider is not None else "就绪"
        columns = get_app().output.get_size().columns
        toolbar: StyleAndTextTuples = [
            ("class:toolbar.model", f" {self.model_label} "),
            ("class:toolbar", f"  {state}  "),
        ]
        if columns >= 64:
            toolbar.append(("class:toolbar.hint", f"  {self.cwd_label} "))
        if columns >= 110:
            toolbar.append(("class:toolbar.hint", " ·  Enter 发送  ·  Ctrl-J 换行 "))
        return toolbar

    def read(self) -> str:
        """读取一条消息；Ctrl-C/EOF 以标准异常交给调用方处理。"""
        key_bindings = KeyBindings()
        buffer = Buffer(
            history=self._history,
            completer=self._completer,
            complete_while_typing=True,
            auto_suggest=AutoSuggestFromHistory(),
            multiline=True,
        )

        @key_bindings.add("enter")
        def _accept(event) -> None:  # type: ignore[no-untyped-def]
            text = event.current_buffer.text
            if text.strip():
                event.app.exit(result=text)

        @key_bindings.add("c-j")
        def _newline(event) -> None:  # type: ignore[no-untyped-def]
            event.current_buffer.insert_text("\n")

        @key_bindings.add("c-c")
        def _cancel(_event) -> None:  # type: ignore[no-untyped-def]
            raise KeyboardInterrupt

        @key_bindings.add("c-d")
        def _eof(event) -> None:  # type: ignore[no-untyped-def]
            if event.current_buffer.text:
                event.current_buffer.delete()
                return
            raise EOFError

        control = BufferControl(
            buffer=buffer,
            input_processors=[BeforeInput([("class:prompt", "❯ ")])],
        )
        input_window = Window(
            control,
            height=Dimension(min=1, max=6),
            wrap_lines=True,
            style="class:input",
        )
        frame = Frame(input_window, title="Message", style="class:frame")
        toolbar = Window(
            FormattedTextControl(self._toolbar),
            height=1,
            style="class:toolbar",
        )
        container = FloatContainer(
            content=HSplit([frame, toolbar]),
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8, scroll_offset=1),
                )
            ],
        )
        app: Application[str] = Application(
            layout=Layout(container, focused_element=input_window),
            key_bindings=key_bindings,
            style=self._style,
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
        )
        result = app.run()
        self._history.append_string(result)
        return result.strip()
