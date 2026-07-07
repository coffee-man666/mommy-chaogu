"""AI 对话面板（RichLog + Input）。

输入回车 → 调 data_service.chat() → 结果追加到 RichLog。
用 Rich Markdown 渲染 agent 回复。
agent 不可用（无 API key）时显示提示。
"""

from __future__ import annotations

import asyncio
import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

_log = logging.getLogger(__name__)


class ChatPanel(Vertical):
    """AI 对话面板。

    RichLog 显示对话流，Input 接受用户输入。
    回车发送消息，异步等待 agent 回复后追加到对话流。
    """

    DEFAULT_CSS = """
    ChatPanel {
        width: 2fr;
        height: 100%;
        border: round $panel;
    }
    ChatPanel > .title {
        padding: 0 1;
        height: 1;
        background: $boost;
        color: $text;
    }
    ChatPanel > RichLog {
        height: 1fr;
        border: none;
        padding: 0 1;
    }
    ChatPanel > Input {
        height: 3;
        border: round $accent;
        margin: 0 1;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._history: list[dict[str, str]] = []
        self._busy = False
        self._chat_task: object = None

    def compose(self) -> ComposeResult:
        yield Static("🤖 AI 助手", classes="title")
        yield RichLog(id="chat-log", markup=True, wrap=True)
        yield Input(id="chat-input", placeholder="输入消息，回车发送…")

    def on_mount(self) -> None:
        """初始化：显示欢迎信息 + agent 状态。"""
        log = self.query_one("#chat-log", RichLog)
        log.write("[bold cyan]═══ Mommy AI 助手 ═══[/]")
        log.write("")

        app = self.app
        data_service = getattr(app, "data_service", None)
        if data_service is not None and data_service.agent is not None:
            log.write("[green]✓ Agent 已就绪，可以开始对话[/]")
        else:
            log.write(
                "[yellow]⚠️ Agent 不可用（未配置 API key）。"
                "设置 DEEPSEEK_API_KEY / OPENAI_API_KEY / ZAI_API_KEY 后可用。[/]"
            )
        log.write("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """回车发送消息。"""
        if self._busy:
            return
        text = event.value.strip()
        if not text:
            return

        event.input.clear()
        self._chat_task = asyncio.get_event_loop().create_task(self._handle_chat(text))

    async def _handle_chat(self, text: str) -> None:
        """处理一次对话：显示用户消息 → 调 agent → 显示回复。"""
        self._busy = True
        log = self.query_one("#chat-log", RichLog)

        # 显示用户消息
        log.write(f"[bold blue]🧑 你:[/] {text}")
        log.write("[dim]⏳ 思考中…[/]")

        app = self.app
        data_service = getattr(app, "data_service", None)
        if data_service is None:
            log.write("[red]数据服务未就绪[/]")
            self._busy = False
            return

        # 删除上一条"思考中"提示
        # RichLog 没有直接删除单行的方法，改用分隔线替代
        try:
            reply = await data_service.chat(text, history=self._history)
        except Exception as e:
            reply = f"❌ 调用失败: {e}"

        # 记录历史
        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": reply})
        # 只保留最近 20 轮
        if len(self._history) > 40:
            self._history = self._history[-40:]

        # 用 Rich Markdown 渲染 agent 回复
        from rich.markdown import Markdown

        log.write("[bold green]🤖 AI:[/]")
        try:
            log.write(Markdown(reply))
        except Exception:
            log.write(reply)
        log.write("[dim]" + "─" * 30 + "[/]")

        self._busy = False
