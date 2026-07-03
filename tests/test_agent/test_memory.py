"""ConversationMemory 单测：SQLite 持久化对话记忆。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent.memory import ConversationMemory
from mommy_chaogu.agent.service import AgentService
from mommy_chaogu.agent.tools import ToolContext


@pytest.fixture
def memory(tmp_path: Path) -> ConversationMemory:
    return ConversationMemory(tmp_path / "test_memory.db")


class TestConversationMemoryCRUD:
    def test_add_and_recent(self, memory: ConversationMemory) -> None:
        """add 后 recent 能取到，顺序为最旧在前。"""
        memory.add("user", "你好")
        memory.add("assistant", "你好！有什么可以帮你的？")

        recent = memory.recent()
        assert len(recent) == 2
        assert recent[0]["role"] == "user"
        assert recent[0]["content"] == "你好"
        assert recent[1]["role"] == "assistant"
        assert recent[1]["content"] == "你好！有什么可以帮你的？"

    def test_add_returns_id(self, memory: ConversationMemory) -> None:
        """add 返回自增 id。"""
        id1 = memory.add("user", "a")
        id2 = memory.add("assistant", "b")
        assert id2 == id1 + 1

    def test_timestamp_recorded(self, memory: ConversationMemory) -> None:
        """每条记录带 timestamp。"""
        memory.add("user", "test")
        recent = memory.recent()
        assert len(recent) == 1
        assert isinstance(recent[0]["timestamp"], datetime)

    def test_recent_limit(self, memory: ConversationMemory) -> None:
        """recent(limit=N) 只返回最近 N 条。"""
        for i in range(10):
            memory.add("user", f"msg-{i}")

        recent = memory.recent(limit=3)
        assert len(recent) == 3
        # 最旧的应该是 msg-7（最近 3 条是 7,8,9）
        assert recent[0]["content"] == "msg-7"
        assert recent[2]["content"] == "msg-9"

    def test_recent_empty(self, memory: ConversationMemory) -> None:
        """空库时 recent 返回空列表。"""
        assert memory.recent() == []


class TestConversationMemoryClear:
    def test_clear_returns_count(self, memory: ConversationMemory) -> None:
        """clear 返回删除条数。"""
        memory.add("user", "a")
        memory.add("assistant", "b")
        n = memory.clear()
        assert n == 2
        assert memory.recent() == []

    def test_clear_empty(self, memory: ConversationMemory) -> None:
        """清空空库返回 0。"""
        assert memory.clear() == 0


class TestConversationMemorySummary:
    def test_summary_counts(self, memory: ConversationMemory) -> None:
        """summary 按 role 统计。"""
        memory.add("user", "a")
        memory.add("assistant", "b")
        memory.add("user", "c")

        s = memory.summary()
        assert s["total"] == 3
        assert s["user"] == 2
        assert s["assistant"] == 1

    def test_summary_empty(self, memory: ConversationMemory) -> None:
        """空库 summary 全 0。"""
        s = memory.summary()
        assert s["total"] == 0
        assert s["user"] == 0
        assert s["assistant"] == 0


class TestMemoryPersistence:
    def test_reopen_preserves_data(self, tmp_path: Path) -> None:
        """重新打开同一 db 文件，数据还在。"""
        db = tmp_path / "persist.db"
        mem1 = ConversationMemory(db)
        mem1.add("user", "persisted")
        mem1.add("assistant", "yes")

        mem2 = ConversationMemory(db)
        recent = mem2.recent()
        assert len(recent) == 2
        assert recent[0]["content"] == "persisted"


class TestAgentServiceWithMemory:
    """AgentService.chat(memory=...) 集成测试。"""

    @patch("openai.OpenAI")
    def test_chat_persists_to_memory(
        self, _mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        """chat 完成后 user/assistant 消息被写入 memory。"""
        adp = MagicMock()
        adp.get_quote.return_value = None
        ctx = ToolContext(adapter=adp)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "你好！"

        svc = AgentService(ctx, api_key="sk-test")
        svc._client.chat.completions.create.return_value = mock_response

        mem = ConversationMemory(tmp_path / "agent.db")
        resp = svc.chat("你好", memory=mem)

        assert resp.text == "你好！"
        recent = mem.recent()
        assert len(recent) == 2
        assert recent[0]["role"] == "user"
        assert recent[0]["content"] == "你好"
        assert recent[1]["role"] == "assistant"
        assert recent[1]["content"] == "你好！"

    @patch("openai.OpenAI")
    def test_chat_loads_memory_as_context(
        self, _mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        """chat 会从 memory 加载历史作为上下文。"""
        adp = MagicMock()
        adp.get_quote.return_value = None
        ctx = ToolContext(adapter=adp)

        captured_messages: list = []

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "ok"

        def capture(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return mock_response

        svc = AgentService(ctx, api_key="sk-test")
        svc._client.chat.completions.create.side_effect = capture

        mem = ConversationMemory(tmp_path / "agent.db")
        mem.add("user", "之前的提问")
        mem.add("assistant", "之前的回答")

        svc.chat("新问题", memory=mem)

        # messages 应包含：system + 2 条历史 + 1 条新 user
        roles = [m["role"] for m in captured_messages]
        assert roles == ["system", "user", "assistant", "user"]
        assert captured_messages[1]["content"] == "之前的提问"
        assert captured_messages[3]["content"] == "新问题"
