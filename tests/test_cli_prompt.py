"""CLI 输入组件的编辑行为回归测试。"""

from prompt_toolkit.buffer import Buffer

from mommy_chaogu.cli_prompt import _delete_before_cursor


def test_backspace_removes_every_character_including_first() -> None:
    buffer = Buffer()
    buffer.text = "/delete"
    buffer.cursor_position = len(buffer.text)

    for _ in range(len(buffer.text)):
        _delete_before_cursor(buffer)

    assert buffer.text == ""
    assert buffer.cursor_position == 0


def test_backspace_on_empty_buffer_is_noop() -> None:
    buffer = Buffer()
    _delete_before_cursor(buffer)
    assert buffer.text == ""
