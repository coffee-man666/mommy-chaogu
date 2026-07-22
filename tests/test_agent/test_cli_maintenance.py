"""mommy-agent verify / consolidate 子命令测试（EVALUATION-2026-07-18 P1）。

回归点：
- "verify" / "consolidate" 在 chat 解析前被拦截为子命令，不会被当成提问
- verify 子命令可离线跑通（修复前 VectorSearch(AGENT_DB) 构造 TypeError）
- consolidate 无 API key 时明确退出码 1，有 client 时走 MemoryConsolidator
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.cli_commands import agent as agent_cli


class TestVerifySubcommand:
    def test_dispatches_to_run_verify(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mommy-agent verify → 调 run_verify 并退出 0（不走 chat 路径）。"""
        db = tmp_path / "agent.db"
        called: list[Path] = []

        def fake_run_verify(d: Path) -> dict[str, int]:
            called.append(d)
            return {
                "total": 0,
                "hit": 0,
                "missed": 0,
                "data_unavailable": 0,
                "unverifiable": 0,
                "expired": 0,
            }

        monkeypatch.setattr(agent_cli, "run_verify", fake_run_verify)
        monkeypatch.setattr(sys, "argv", ["mommy-agent", "verify", "--db", str(db)])

        with pytest.raises(SystemExit) as exc_info:
            agent_cli.main_agent()

        assert exc_info.value.code == 0
        assert called == [db]

    def test_run_verify_empty_db_offline(self, tmp_path: Path) -> None:
        """空库 + 无到期预测时不触网、不崩溃，返回全零统计。"""
        results = agent_cli.run_verify(tmp_path / "agent.db", market_db=tmp_path / "market.db")
        assert results["total"] == 0
        assert results["hit"] == 0
        assert results["missed"] == 0

    def test_run_verify_writes_cache_to_market_db(self, tmp_path: Path) -> None:
        """缓存表应建在 market.db，不再污染 agent.db（cron_verify.py 旧行为）。"""
        import sqlite3

        agent_db = tmp_path / "agent.db"
        market_db = tmp_path / "market.db"
        agent_cli.run_verify(agent_db, market_db=market_db)

        conn = sqlite3.connect(str(market_db))
        market_tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert "quote_cache" in market_tables

        conn = sqlite3.connect(str(agent_db))
        agent_tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert "quote_cache" not in agent_tables


class TestConsolidateSubcommand:
    def test_no_api_key_exits_one(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """无法构造 LLM client 时退出码 1，且给出明确错误信息。"""
        monkeypatch.setattr(agent_cli, "_build_llm_client", lambda *a, **kw: (None, None))
        monkeypatch.setattr(
            sys, "argv", ["mommy-agent", "consolidate", "--db", str(tmp_path / "agent.db")]
        )

        with pytest.raises(SystemExit) as exc_info:
            agent_cli.main_agent()

        assert exc_info.value.code == 1

    def test_runs_consolidator_with_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """有 client 时走 MemoryConsolidator.consolidate_all 并打印统计。

        mock client 的 LLM 返回为空内容，consolidator 降级路径返回全零，
        整个调用不触网。
        """
        fake_client = MagicMock()
        monkeypatch.setattr(
            agent_cli, "_build_llm_client", lambda *a, **kw: (fake_client, "test-model")
        )
        monkeypatch.setattr(
            sys, "argv", ["mommy-agent", "consolidate", "--db", str(tmp_path / "agent.db")]
        )

        with pytest.raises(SystemExit) as exc_info:
            agent_cli.main_agent()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "板块叙事" in out
        assert "市场状态" in out
        assert "规律归纳" in out


class TestChatPathVectorSearchFallback:
    def test_vector_search_init_failure_degrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """VectorSearch 构造抛异常时不崩溃，以 vector_search=None 继续。

        修复前 cli 用 ``VectorSearch(AGENT_DB)``（Path 当 EpisodicMemory 传
        且缺 client）直接 TypeError，agent 启动即崩。
        """
        import mommy_chaogu.agent.vector_search as vs_mod

        monkeypatch.setattr(
            vs_mod.VectorSearch,
            "__init__",
            lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(
            agent_cli, "_build_llm_client", lambda *a, **kw: (MagicMock(), "test-model")
        )

        # AgentService 会因无 API key 抛 ValueError——证明执行越过了
        # VectorSearch 构造点（否则先抛 RuntimeError("boom")）。
        monkeypatch.setattr(sys, "argv", ["mommy-agent", "测试"])
        with pytest.raises(ValueError, match="API key"):
            agent_cli.main_agent()
