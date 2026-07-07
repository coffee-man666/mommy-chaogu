"""TUI 模块：Textual 终端界面。

基于 Textual 框架，直接复用项目内部 adapter/store，
不走 HTTP，提供三栏 dashboard 布局 + 个股详情屏。
"""

from mommy_chaogu.tui.app import MommyTUIApp

__all__ = ["MommyTUIApp"]
