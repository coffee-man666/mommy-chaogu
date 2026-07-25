"""HelpScreen — 按键速查（单屏对话版）。"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown

_HELP_TEXT = """\
# 按键速查

## 全局
  Enter      发送（busy 时排队，轮次结束自动发出）
  Esc        中断当前轮（保留已流出部分）
  ↑ ↓        输入历史 / 候选选择
  Tab        接受补全（/ 命令 · @ 股票）
  PgUp PgDn  滚动对话
  Ctrl+L     清屏
  Ctrl+P     命令面板
  Ctrl+T     切换主题
  Ctrl+C     连按两次退出
  ?          帮助（本页面）

## 输入技巧
  /          斜杠命令联想
  @          股票联想（@茅台 → 600519）
  600519     直接输入 6 位代码，Enter 看报价

## 斜杠命令
  /today        今日总览（指数/自选/信号/预测）
  /watch        自选股列表
  /portfolio    持仓
  /flows [code] 资金流（无参数看自选榜）
  /quote code   个股报价
  /predictions  预测跟踪
  /signals      近期信号
  /memory       记忆系统
  /status       服务状态
  /clear        清空对话
  /theme        切换主题
  /quit         退出
"""


class HelpScreen(ModalScreen[None]):
    """帮助弹窗。"""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss", "关闭")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-scroll"):
            yield Markdown(_HELP_TEXT, id="help-text")

    def on_mount(self) -> None:
        self.query_one("#help-scroll").border_title = "按键速查"
