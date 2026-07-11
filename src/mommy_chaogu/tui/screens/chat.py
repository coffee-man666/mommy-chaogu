"""沉浸式 AI 对话屏（默认主屏）。

布局：
    ┌─────────────────────────────────────┐
    │         IndexStrip（顶部 1 行）       │
    ├─────────────────────────────────────┤
    │                                     │
    │          对话流（Markdown）           │
    │                                     │
    ├─────────────────────────────────────┤
    │  Input 输入框（底部固定）              │
    └─────────────────────────────────────┘

Tab → 切换到数据看板。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static

from mommy_chaogu.tui.widgets.chat_message import ChatMessage
from mommy_chaogu.tui.widgets.index_strip import IndexStrip

_log = logging.getLogger(__name__)

# 匹配 Textual DOMNode.BINDINGS 的类型
_Bindings = list[Binding | tuple[str, str] | tuple[str, str, str]]


class ChatScreen(Screen[object]):
    """沉浸式 AI 对话屏（默认主屏）。

    Tab 切换到看板，Ctrl+Q 退出。
    assistant 回复用 Markdown widget 渲染。
    """

    BINDINGS: ClassVar[_Bindings] = [
        Binding("tab", "cycle_screen", "看板", priority=True),
        Binding("ctrl+q", "quit", "退出"),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
    }
    ChatScreen > IndexStrip {
        height: 1;
    }
    ChatScreen > #chat-scroll {
        height: 1fr;
        padding: 0 1;
    }
    ChatScreen > #chat-input {
        height: 3;
        border: round $accent;
        margin: 0 1;
    }
    ChatScreen > #chat-welcome {
        padding: 1 2;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._history: list[dict[str, str]] = []
        self._busy = False
        self._chat_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield IndexStrip()
        with VerticalScroll(id="chat-scroll"):
            yield Static(
                "欢迎使用 Mommy Chaogu TUI\n输入消息开始对话...",
                id="chat-welcome",
            )
        yield Input(id="chat-input", placeholder="输入消息... (Tab→看板, Ctrl+Q退出)")

    def on_mount(self) -> None:
        """挂载后检查 Agent 状态。"""
        data_service = getattr(self.app, "data_service", None)
        if data_service is None:
            return

        ag = data_service.agent
        if ag is None:
            with contextlib.suppress(Exception):
                welcome = self.query_one("#chat-welcome", Static)
                welcome.update(
                    "欢迎使用 Mommy Chaogu TUI\n\n"
                    "⚠️ Agent 不可用：未配置 API key\n"
                    "设置 DEEPSEEK_API_KEY / OPENAI_API_KEY / "
                    "ZAI_API_KEY 后可用"
                )

    def on_unmount(self) -> None:
        """卸载时取消正在进行的对话任务，避免悬空 task。"""
        task = self._chat_task
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """回车发送消息。"""
        if self._busy:
            return
        text = event.value.strip()
        if not text:
            return

        event.input.clear()
        self._chat_task = asyncio.create_task(self._handle_chat(text))

    async def _handle_chat(self, text: str) -> None:
        """处理一次对话：显示用户消息 → 调 agent → 显示回复。"""
        self._busy = True
        try:
            scroll = self.query_one("#chat-scroll", VerticalScroll)

            # 移除欢迎语
            with contextlib.suppress(Exception):
                welcome = self.query_one("#chat-welcome")
                welcome.remove()

            # 1. 追加用户消息
            user_msg = ChatMessage(role="user", content=text)
            await scroll.mount(user_msg)

            # 2. 创建 assistant Markdown 占位
            assistant_msg = ChatMessage(role="assistant", content="*思考中…*")
            await scroll.mount(assistant_msg)

            # 滚动到底部
            scroll.scroll_end(animate=False)

            data_service = getattr(self.app, "data_service", None)

            # 3. 调 data_service.chat(message)
            # TODO: data_service.chat() 尚不支持 on_tool_call 回调，
            #       待支持后可在调用时传入回调，用 ToolIndicator 展示工具调用过程。
            if data_service is None:
                await assistant_msg.update_content("❌ 数据服务未就绪")
            else:
                try:
                    reply = await data_service.chat(text, history=self._history)
                except Exception as e:
                    _log.warning("agent chat 失败: %s", e)
                    reply = f"❌ Agent 调用失败: {e}"

                # 记录历史（只保留最近 20 轮（40 条消息））
                self._history.append({"role": "user", "content": text})
                self._history.append({"role": "assistant", "content": reply})
                if len(self._history) > 40:
                    self._history = self._history[-40:]

                # 4. 结果用 Markdown widget 渲染
                await assistant_msg.update_content(reply)

            scroll.scroll_end(animate=False)
        except Exception as e:
            _log.exception("chat 处理失败")
            # 向用户展示错误（UI 中没有专门的错误区，用 ChatMessage 展示）
            with contextlib.suppress(Exception):
                scroll = self.query_one("#chat-scroll", VerticalScroll)
                err_msg = ChatMessage(role="assistant", content=f"⚠️ 出错了: {e}")
                await scroll.mount(err_msg)
                scroll.scroll_end(animate=False)
        finally:
            self._busy = False
            # 重新聚焦到输入框
            with contextlib.suppress(Exception):
                self.query_one("#chat-input", Input).focus()
