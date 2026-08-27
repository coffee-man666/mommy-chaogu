"""SessionJournal — TUI 会话恢复（切片 1：recover_latest 冷启动与存量恢复）。

产品行为：重启 mommy-tui 后，对话流自动恢复「上次会话」的文字历史，
用户无需任何按键即可接着聊。数据源是 agent_memory（每轮 user/assistant
文本已在持久化），本模块只读派生，不新增写路径。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.agent.memory import ConversationMemory
from mommy_chaogu.tui.services.session_journal import SessionJournal


def _memory(tmp_path: Path) -> ConversationMemory:
    return ConversationMemory(tmp_path / "agent.db")


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class TestRecoverLatest:
    def test_cold_start_empty_db(self, tmp_path: Path) -> None:
        """空库（首次安装）：冷启动，无会话可恢复，不报错。"""
        journal = SessionJournal(_memory(tmp_path))

        rec = journal.recover_latest()

        assert rec.reason == "cold-start"
        assert rec.session_id is None
        assert rec.entries == ()
        assert rec.more_older == 0

    def test_resumes_existing_default_session(self, tmp_path: Path) -> None:
        """存量对话（老版本全写 default）：升级后首启即恢复，无需迁移。"""
        mem = _memory(tmp_path)
        mem.add("user", "茅台多少钱")
        mem.add("assistant", "现价 1680 元")
        journal = SessionJournal(mem)

        rec = journal.recover_latest()

        assert rec.reason == "resumed-latest"
        assert rec.session_id == "default"
        assert [e.role for e in rec.entries] == ["user", "assistant"]
        assert rec.entries[0].content == "茅台多少钱"
        assert rec.entries[1].content == "现价 1680 元"
        assert rec.more_older == 0

    def test_tail_window_clips_and_counts_older(self, tmp_path: Path) -> None:
        """长会话只回放尾窗；被裁掉的条数如实上报（不静默丢历史）。"""
        mem = _memory(tmp_path)
        for i in range(6):
            mem.add("user", f"问题{i}")
            mem.add("assistant", f"回答{i}")
        journal = SessionJournal(mem, tail_size=4)

        rec = journal.recover_latest()

        assert len(rec.entries) == 4
        # 6 轮 × 2 条 = 12 条，尾窗是「最新 4 条」，正序最旧在前
        assert [e.content for e in rec.entries] == ["问题4", "回答4", "问题5", "回答5"]
        assert rec.more_older == 8

    def test_picks_most_recently_active_session(self, tmp_path: Path) -> None:
        """多会话并存：恢复「最近写入」的那个（按消息 id 派生，不依赖时钟）。"""
        mem = _memory(tmp_path)
        mem.add("user", "旧会话一", session_id="tui-0801")
        mem.add("assistant", "旧会话答一", session_id="tui-0801")
        mem.add("user", "新会话二", session_id="tui-0826")
        journal = SessionJournal(mem)

        rec = journal.recover_latest()

        assert rec.reason == "resumed-latest"
        assert rec.session_id == "tui-0826"
        assert [e.content for e in rec.entries] == ["新会话二"]


class TestSessionSwitching:
    def test_cold_start_then_begin_next(self, tmp_path: Path) -> None:
        """冷启动后 /new：分配新会话 id 并激活，旧数据不受影响。"""
        mem = _memory(tmp_path)
        mem.add("user", "老对话", session_id="default")
        journal = SessionJournal(mem)

        new_id = journal.begin_next()

        assert journal.active_id == new_id
        assert new_id != "default"
        assert new_id.startswith("tui-")
        # 合法 id（能被 add 接受即通过校验）
        mem.add("user", "新会话第一句", session_id=new_id)
        assert mem.summary(new_id)["total"] == 1

    def test_active_id_follows_recover_latest(self, tmp_path: Path) -> None:
        """未显式 /new 时，recover_latest 之后 active_id 即所恢复的会话。"""
        mem = _memory(tmp_path)
        mem.add("user", "历史", session_id="default")
        journal = SessionJournal(mem)

        rec = journal.recover_latest()

        assert journal.active_id == rec.session_id == "default"

    def test_switch_to_existing_session(self, tmp_path: Path) -> None:
        """/resume <id>：切换激活会话并返回该会话尾窗。"""
        mem = _memory(tmp_path)
        mem.add("user", "a会话", session_id="tui-a")
        mem.add("user", "b会话一", session_id="tui-b")
        mem.add("assistant", "b会话二", session_id="tui-b")
        journal = SessionJournal(mem)
        journal.begin_next()  # 激活一个新会话

        rec = journal.switch("tui-b")

        assert journal.active_id == "tui-b"
        assert rec.reason == "picked"
        assert rec.session_id == "tui-b"
        assert [e.content for e in rec.entries] == ["b会话一", "b会话二"]

    def test_switch_missing_falls_back_to_active(self, tmp_path: Path) -> None:
        """/resume 到不存在的 id（如刚被清理）：回落当前会话，不抛异常。"""
        mem = _memory(tmp_path)
        mem.add("user", "当前", session_id="default")
        journal = SessionJournal(mem)
        journal.recover_latest()

        rec = journal.switch("tui-gone")

        assert rec.session_id == "default"
        assert journal.active_id == "default"

    def test_sessions_lists_by_recency(self, tmp_path: Path) -> None:
        """/resume 列表：按最近活跃倒序，含条数与首条 user 预览。"""
        mem = _memory(tmp_path)
        mem.add("user", "茅台怎么样", session_id="tui-a")
        mem.add("user", "中芯国际呢", session_id="tui-b")
        journal = SessionJournal(mem)

        rows = journal.sessions()

        assert [r.session_id for r in rows] == ["tui-b", "tui-a"]
        assert rows[0].n_messages == 1
        assert rows[0].preview == "中芯国际呢"
        assert rows[1].preview == "茅台怎么样"


class TestAgentBinding:
    """恢复后「接着聊」的写入归属：换绑 SessionMemory 视图。"""

    def test_bound_memory_scopes_to_active_session(self, tmp_path: Path) -> None:
        mem = _memory(tmp_path)
        mem.add("user", "历史", session_id="tui-a")
        journal = SessionJournal(mem)
        journal.switch("tui-a")

        bound = journal.bound_memory_for_agent()

        assert bound is not None
        assert bound.session_id == "tui-a"  # type: ignore[attr-defined]
        bound.add("user", "恢复后的新消息")
        assert mem.summary("tui-a")["total"] == 2
        assert mem.summary("default")["total"] == 0

    def test_agent_chat_after_resume_writes_to_resumed_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """端到端语义：resume 后跑一轮 agent，正文与上下文都落回该会话。"""
        from unittest.mock import MagicMock, patch

        from mommy_chaogu.agent.service import AgentService
        from mommy_chaogu.agent.tools import ToolContext

        monkeypatch.setenv("AGENT_MODEL", "")
        mem = _memory(tmp_path)
        mem.add("user", "之前问过茅台", session_id="tui-a")
        mem.add("assistant", "1680", session_id="tui-a")
        journal = SessionJournal(mem)
        journal.switch("tui-a")

        adp = MagicMock()
        ctx = ToolContext(adapter=adp)
        final = MagicMock()
        final.tool_calls = None
        final.content = "好的，继续看茅台"
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message = final

        with patch("openai.OpenAI"):
            svc = AgentService(ctx, api_key="sk-test")
        svc._tools = MagicMock()
        svc._tools.definitions.return_value = []
        svc._client.chat.completions.create.return_value = resp

        bound = journal.bound_memory_for_agent()
        assert bound is not None
        svc.chat("继续", memory=bound)

        # 新一轮写回恢复的会话（而不是 default）
        assert mem.summary("tui-a")["total"] == 4
        assert mem.summary("default")["total"] == 0
        # LLM 的上下文里带上了恢复会话的历史
        sent_messages = svc._client.chat.completions.create.call_args.kwargs["messages"]
        roles = [m["role"] for m in sent_messages]
        assert roles.count("user") == 2  # 历史一条 + 本轮一条
        assert any(m["content"] == "之前问过茅台" for m in sent_messages)


class TestChatViewReplay:
    """切片 4：恢复流渲染（复用既有 append_* 原语，不加 IO）。"""

    def test_replay_entries_renders_transcript(self) -> None:
        from datetime import UTC, datetime

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.services.session_journal import JournalEntry
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                ts = datetime.now(UTC)
                chat.replay_entries(
                    (
                        JournalEntry(1, "user", "你好", ts),
                        JournalEntry(2, "assistant", "**回复**", ts),
                    ),
                    more_older=3,
                )
                await pilot.pause()

                assert len(chat.query(".user-msg")) == 1
                assert len(chat.query(".assistant-msg")) == 1
                omitted = chat.query(".resume-omitted")
                assert len(omitted) == 1
                assert "3" in str(omitted[0].content)  # type: ignore[attr-defined]

        _run(_test())

    def test_show_resume_banner(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.show_resume_banner("tui-20260827-120000-ab12", 5)
                await pilot.pause()

                banner = chat.query(".resume-banner")
                assert len(banner) == 1
                content = str(banner[0].content)  # type: ignore[attr-defined]
                assert "5" in content
                assert "tui-20260827" in content

        _run(_test())


class TestAppSessionWiring:
    """切片 5：启动自动恢复 + /new /resume 接线。"""

    @staticmethod
    def _services_with_memory(tmp_path: Path, *, seed: int = 0) -> Any:
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        services = FakeServices.create()
        mem = ConversationMemory(tmp_path / "agent.db")
        for i in range(seed):
            mem.add("user", f"历史问题{i}")
            mem.add("assistant", f"历史回答{i}")
        services.agent._memory = mem
        return services, mem

    @staticmethod
    async def _wait_until(pilot: Any, predicate: Any, timeout_s: float = 4.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return True
            await pilot.pause(0.05)
        return predicate()

    def test_startup_auto_resumes_last_session(self, tmp_path: Path) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.views.chat import ChatView

        services, _mem = self._services_with_memory(tmp_path, seed=2)

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                ok = await self._wait_until(pilot, lambda: len(chat.query(".resume-banner")) == 1)
                assert ok, "启动后应出现恢复横幅"
                assert len(chat.query(".user-msg")) == 2
                assert len(chat.query(".assistant-msg")) == 2
                # 续聊绑定：bridge 的记忆视图换到恢复的会话
                assert services.agent._memory.session_id == "default"

        _run(_test())

    def test_resume_env_off_skips_auto_recovery(self, tmp_path: Path, monkeypatch: Any) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.views.chat import ChatView

        monkeypatch.setenv("MOMMY_TUI_RESUME", "off")
        services, _mem = self._services_with_memory(tmp_path, seed=1)
        original = services.agent._memory

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                await pilot.pause(0.5)
                chat = app.query_one(ChatView)
                assert len(chat.query(".resume-banner")) == 0
                assert services.agent._memory is original  # 未换绑

        _run(_test())

    def test_new_command_starts_fresh_session(self, tmp_path: Path) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp

        services, mem = self._services_with_memory(tmp_path, seed=1)

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                prompt = app.query_one("ChatInput")
                prompt.value = "/new"
                await pilot.press("enter")
                assert await self._wait_until(
                    pilot,
                    lambda: (
                        services.agent._memory is not None
                        and services.agent._memory.session_id.startswith("tui-")
                    ),
                )
                assert app._journal is not None and app._journal.active_id.startswith("tui-")
                assert mem.summary("default")["total"] == 2  # 旧会话原样保留

        _run(_test())

    def test_resume_command_lists_and_switches(self, tmp_path: Path) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.views.chat import ChatView

        services, mem = self._services_with_memory(tmp_path, seed=1)
        mem.add("user", "另一个会话的问题", session_id="tui-20260820-090000-cafe")

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                prompt = app.query_one("ChatInput")
                # 无参：列表卡
                prompt.value = "/resume"
                await pilot.press("enter")
                chat = app.query_one(ChatView)
                assert await self._wait_until(
                    pilot,
                    lambda: any("tui-20260820" in str(c.content) for c in chat.query(".card")),
                )
                # 带 id：切换
                prompt.value = "/resume tui-20260820-090000-cafe"
                await pilot.press("enter")
                assert await self._wait_until(
                    pilot, lambda: services.agent._memory.session_id == "tui-20260820-090000-cafe"
                )
                assert await self._wait_until(
                    pilot,
                    lambda: any(
                        "另一个会话的问题" in str(c.content) for c in chat.query(".user-msg")
                    ),
                )

        _run(_test())
