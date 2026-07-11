"""mommy-memory CLI 测试：parser 构建 + stats 子命令。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.cli import build_memory_parser, cmd_memory_stats


def test_build_memory_parser_has_subcommands():
    """parser 应包含 stats / events / predictions / knowledge / history 子命令。"""
    parser = build_memory_parser()
    # 找到 subparsers action
    sub_action = None
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            sub_action = action
            break
    assert sub_action is not None
    choices = set(sub_action.choices.keys())
    assert {"stats", "events", "predictions", "knowledge", "history"}.issubset(choices)


def test_memory_parser_default_db_is_agent_db():
    """默认 --db 应为 AGENT_DB 路径。"""
    from mommy_chaogu.db_paths import AGENT_DB

    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(AGENT_DB), "stats"])
    assert Path(args.db) == AGENT_DB


def test_memory_stats_runs_with_empty_db(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """stats 子命令在空数据库上应正常运行并返回 0。"""
    db = tmp_path / "test_agent.db"
    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "stats"])
    rc = cmd_memory_stats(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "记忆系统统计" in captured.out
    assert "对话记忆" in captured.out
    assert "事件记忆" in captured.out
    assert "预测追踪" in captured.out
    assert "知识记忆" in captured.out


def test_memory_stats_with_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """写入一些数据后 stats 应显示正确的计数。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.memory import ConversationMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    db = tmp_path / "agent.db"

    conv = ConversationMemory(db)
    conv.add("user", "茅台怎么样")
    conv.add("assistant", "茅台当前强势")

    em = EpisodicMemory(db)
    em.write(
        event_type="market_snapshot",
        scope="market",
        summary="沪指收涨",
        data={"close": 3200},
    )

    tracker = PredictionTracker(db)
    tracker.create(
        code="600519",
        name="贵州茅台",
        prediction="看涨",
        direction="up",
        timeframe="5d",
    )

    sm = SemanticMemory(db)
    sm.upsert(
        knowledge_type="sector_thesis",
        scope="sector:白酒",
        content="白酒板块景气向上",
    )

    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "stats"])
    rc = cmd_memory_stats(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "总条数: 2" in captured.out  # 对话 2 条
    assert "总条数: 1" in captured.out  # 事件 1 条


def test_memory_events_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """events 子命令应显示事件。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    db = tmp_path / "agent.db"
    em = EpisodicMemory(db)
    em.write(
        event_type="signal_event",
        scope="stock:600519",
        summary="放量突破",
        data={"volume": 1e8},
        code="600519",
    )

    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "events"])
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "600519" in captured.out
    assert "放量突破" in captured.out


def test_memory_predictions_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """predictions 子命令应显示预测。"""
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    db = tmp_path / "agent.db"
    tracker = PredictionTracker(db)
    tracker.create(
        code="300750",
        name="宁德时代",
        prediction="看涨",
        direction="up",
        timeframe="5d",
    )

    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "predictions"])
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "300750" in captured.out
    assert "pending" in captured.out


def test_memory_knowledge_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """knowledge 子命令应显示知识条目。"""
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    db = tmp_path / "agent.db"
    sm = SemanticMemory(db)
    sm.upsert(
        knowledge_type="sector_thesis",
        scope="sector:创新药",
        content="创新药进入上行周期",
        confidence=0.9,
    )

    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "knowledge"])
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "创新药进入上行周期" in captured.out


def test_memory_history_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """history 子命令应显示对话历史。"""
    from mommy_chaogu.agent.memory import ConversationMemory

    db = tmp_path / "agent.db"
    conv = ConversationMemory(db)
    conv.add("user", "今天大盘怎么样")
    conv.add("assistant", "沪指小幅收涨")

    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "history"])
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "今天大盘怎么样" in captured.out
    assert "沪指小幅收涨" in captured.out


def test_memory_events_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """events 在空库上应友好提示。"""
    db = tmp_path / "agent.db"
    parser = build_memory_parser()
    args = parser.parse_args(["--db", str(db), "events"])
    rc = args.func(args)
    assert rc == 0
    assert "暂无事件" in capsys.readouterr().out


def test_memory_parser_limit_args():
    """--limit 参数应正确解析。"""
    parser = build_memory_parser()
    args = parser.parse_args(["events", "--limit", "5"])
    assert args.limit == 5

    args = parser.parse_args(["predictions", "-n", "3"])
    assert args.limit == 3
