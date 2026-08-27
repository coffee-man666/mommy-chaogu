"""SessionJournal — TUI 会话恢复（事件溯源门面）。

产品行为：重启 mommy-tui 后，对话流自动恢复「上次会话」的文字历史，
用户无需任何按键即可接着聊；`/new` 开新会话、`/resume` 切换历史会话。

设计要点（design-an-interface 三方案综合，以「常用路径优先」为主干）：
- agent_memory 表本身就是 append-only 日志；「上次会话」由每会话 MAX(id)
  派生，不维护任何独立指针（无失步、无损坏面）。
- 本模块对 agent_memory **严格只读**：写入仍由 AgentService.chat 内部的
  memory.add 完成（唯一写入方）。续聊换绑通过 ``bound_memory_for_agent()``
  返回 SessionMemory 视图实现（Web/CLI 已验证的既有通路）。
- 已知取舍：工具轨迹 / 富卡片 / 工作流轮次未持久化，恢复出来的是纯文本
  骨架；被 Esc 中断的轮次双方都不入库（agent 层防污染语义），如实继承。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text

from mommy_chaogu.agent.memory import ConversationMemory, SessionMemory, validate_session_id

type ResumeReason = Literal["cold-start", "resumed-latest", "picked"]


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """一条已持久化的对话文本（映射 agent_memory 一行）。"""

    seq: int
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class Recovery:
    """一次会话解析的结果；调用方拿它一次性渲染，无需再做判断。"""

    session_id: str | None  # None 仅当冷启动
    entries: tuple[JournalEntry, ...]  # 尾窗（正序，最旧在前）
    more_older: int  # 尾窗之前被省略的条数（>0 时 UI 渲染省略提示）
    reason: ResumeReason


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """/resume 列表中的一行。"""

    session_id: str
    n_messages: int
    last_active: datetime
    preview: str  # 最近一条 user 消息截断预览（会话后期话题更有辨识度）


class SessionJournal:
    """历史会话的只读派生 + 活跃会话解析。

    所有 IO 都走构造时传入的 ConversationMemory（复用它的 engine 与建表），
    本模块不建新表、不写行。
    """

    def __init__(self, memory: ConversationMemory, *, tail_size: int = 50) -> None:
        self._memory = memory
        self._tail_size = max(1, tail_size)
        self._active: str | None = None

    def recover_latest(self) -> Recovery:
        """解析「上次会话」并返回尾窗。空库（首次安装）返回冷启动。"""
        latest = self._latest_session_id()
        if latest is None:
            return Recovery(None, (), 0, "cold-start")
        entries, more_older = self._tail_window(latest)
        self._active = latest
        return Recovery(latest, entries, more_older, "resumed-latest")

    @property
    def active_id(self) -> str:
        """当前活跃会话。未显式解析/切换时回落 ``default``（与旧版行为一致）。"""
        return self._active if self._active is not None else "default"

    def begin_next(self) -> str:
        """分配并激活一个新会话（/new）。历史会话原样保留在 /resume 列表里。"""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = secrets.token_hex(2)
        new_id = validate_session_id(f"tui-{stamp}-{suffix}")
        self._active = new_id
        return new_id

    def switch(self, session_id: str) -> Recovery:
        """切换活跃会话（/resume <id>）并返回其尾窗。

        目标不存在（如刚被保留期清理）时回落当前会话，不抛异常打断用户。
        """
        try:
            validate_session_id(session_id)
        except ValueError:
            return self.recover_latest()
        if session_id not in self._existing_session_ids():
            return self.recover_latest()
        entries, more_older = self._tail_window(session_id)
        self._active = session_id
        return Recovery(session_id, entries, more_older, "picked")

    def sessions(self, limit: int = 12) -> list[SessionInfo]:
        """可恢复会话列表，按最近活跃倒序（/resume 选择器数据源）。"""
        with self._memory.session() as s:
            rows = s.execute(
                text("""
                    SELECT m.session_id,
                           COUNT(*) AS n,
                           MAX(m.id) AS last_id,
                           MAX(m.timestamp) AS last_ts,
                           (SELECT content FROM agent_memory AS m2
                            WHERE m2.session_id = m.session_id AND m2.role = 'user'
                            ORDER BY m2.id DESC LIMIT 1) AS preview
                    FROM agent_memory AS m
                    GROUP BY m.session_id
                    ORDER BY last_id DESC
                    LIMIT :limit
                """),
                {"limit": max(1, limit)},
            ).all()
        infos: list[SessionInfo] = []
        for r in rows:
            preview = str(r[4] or "")
            ts = r[3] if isinstance(r[3], datetime) else datetime.fromisoformat(str(r[3]))
            infos.append(
                SessionInfo(
                    session_id=str(r[0]),
                    n_messages=int(r[1]),
                    last_active=ts,
                    preview=preview[:40],
                )
            )
        return infos

    def bound_memory_for_agent(self) -> SessionMemory:
        """给 AgentBridge 注入的会话作用域记忆视图（续聊读上下文 + 写回同会话）。

        SessionMemory 满足 AgentService 的 ConversationMemoryLike 协议；
        这条换绑通路在 Web（web/routes/ws.py）与 CLI（cli_commands/channel.py）
        已有先例。写路径仍是 agent 层唯一的 memory.add，无双写。
        """
        return self._memory.for_session(self.active_id)

    def _existing_session_ids(self) -> set[str]:
        with self._memory.session() as s:
            rows = s.execute(text("SELECT DISTINCT session_id FROM agent_memory")).all()
        return {str(r[0]) for r in rows}

    def _tail_window(self, session_id: str) -> tuple[tuple[JournalEntry, ...], int]:
        """某会话的最近 *tail_size* 条（正序）+ 尾窗之前被省略的条数。"""
        with self._memory.session() as s:
            rows = s.execute(
                text("""
                    SELECT id, role, content, timestamp
                    FROM agent_memory
                    WHERE session_id = :sid
                    ORDER BY id DESC LIMIT :limit
                """),
                {"sid": session_id, "limit": self._tail_size},
            ).all()
            total = (
                s.execute(
                    text("SELECT COUNT(*) FROM agent_memory WHERE session_id = :sid"),
                    {"sid": session_id},
                ).scalar()
                or 0
            )
        more_older = max(0, int(total) - len(rows))
        window = list(reversed(rows))
        entries = tuple(
            JournalEntry(
                seq=int(r[0]),
                role=str(r[1]),
                content=str(r[2]),
                timestamp=r[3] if isinstance(r[3], datetime) else datetime.fromisoformat(str(r[3])),
            )
            for r in window
        )
        return entries, more_older

    def _latest_session_id(self) -> str | None:
        """最近活跃的 session_id（按各会话最大消息 id 派生）。"""
        with self._memory.session() as s:
            row = s.execute(
                text("""
                    SELECT session_id
                    FROM agent_memory
                    GROUP BY session_id
                    ORDER BY MAX(id) DESC
                    LIMIT 1
                """)
            ).first()
        return str(row[0]) if row is not None else None
