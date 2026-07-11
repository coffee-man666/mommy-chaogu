"""HelpScreen — 按键速查（§3.2, 附录 B）。"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

_HELP_TEXT = """\
# 按键速查

## 全局
  Tab        切换 对话 ⇄ 看板
  Ctrl+Q     退出
  r          刷新当前视图
  ?          帮助（本页面）
  Ctrl+P     命令面板
  Esc        关闭弹层 / 中断生成

## 对话模式
  Enter      发送
  ↑ ↓        输入历史
  1-7        发送预设问题（空态时）
  Ctrl+L     清屏

## 看板模式
  1-4        切换 自选/持仓/主题/信号
  j k ↑ ↓    行移动
  g / G      跳到顶部 / 底部
  Enter      个股详情
  o          切换排序
  a / x      添加 / 移除自选
  s          启停信号扫描
"""


class HelpScreen(ModalScreen[None]):
    """帮助弹窗。"""

    BINDING: ClassVar[list[Binding | tuple[str, str, str]]] = [("escape", "dismiss", "关闭")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-scroll"):
            yield Static(_HELP_TEXT, id="help-text")

    def on_mount(self) -> None:
        self.query_one("#help-scroll").border_title = "按键速查"
