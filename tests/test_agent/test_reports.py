"""AgentReportService 单测：mock agent + 临时 episodic memory。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.reports import AgentReportService

# ---------- helpers ----------


@dataclass
class _MockResp:
    text: str = "报告正文"
    tool_calls: list = None  # type: ignore[assignment]
    rounds: int = 1

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.chat.return_value = _MockResp()
    return agent


@pytest.fixture
def tmp_memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test_agent.db")


# ---------- board 模式 episodic memory 测试 ----------


class TestBoardReportEpisodicMemory:
    def test_writes_analysis_record_sector_scope(
        self, mock_agent: MagicMock, tmp_memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """board 模式生成报告后，episodic memory 有 analysis_record 事件，scope 为 sector:*。"""
        svc = AgentReportService(mock_agent, db_path=tmp_memory.db_path)

        # mock _collect_board_data 返回板块数据
        board_data = {
            "board_name": "半导体",
            "board_code": "BK1106",
            "timestamp": "2026-07-05 15:00",
            "total_stocks": 50,
            "up_count": 35,
            "down_count": 15,
            "avg_change_pct": 2.3,
            "total_amount_yi": 500.0,
            "total_main_net_yi": 12.5,
            "top_inflow": [],
            "top_outflow": [],
            "top_gainers": [],
        }
        monkeypatch.setattr(svc, "_collect_board_data", lambda *a, **kw: board_data)

        text = svc.generate_daily_report(board_code="BK1106", board_name="半导体")
        assert text == "报告正文"

        events = tmp_memory.query(event_type="analysis_record")
        assert len(events) == 1
        ev = events[0]
        assert ev["scope"] == "sector:半导体"
        assert ev["event_type"] == "analysis_record"
        assert ev["source"] == "agent_report"
        assert len(ev["summary"]) <= 200
        assert "半导体" in ev["summary"]
        # data 包含板块涨跌幅、资金流净额
        assert ev["data"]["avg_change_pct"] == 2.3
        assert ev["data"]["total_main_net_yi"] == 12.5
        assert ev["data"]["up_count"] == 35
        assert ev["data"]["down_count"] == 15
        # trade_date 已设置
        assert ev["trade_date"] is not None

    def test_summary_under_200_chars(
        self, mock_agent: MagicMock, tmp_memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = AgentReportService(mock_agent, db_path=tmp_memory.db_path)
        board_data = {
            "board_name": "测试板块",
            "avg_change_pct": 1.0,
            "total_main_net_yi": 5.0,
            "up_count": 10,
            "down_count": 5,
        }
        monkeypatch.setattr(svc, "_collect_board_data", lambda *a, **kw: board_data)
        svc.generate_daily_report(board_code="BK9999", board_name="测试板块")
        events = tmp_memory.query(event_type="analysis_record")
        assert len(events[0]["summary"]) <= 200


# ---------- pool 模式 episodic memory 测试 ----------


class TestPoolReportEpisodicMemory:
    def test_writes_analysis_record_market_scope(
        self, mock_agent: MagicMock, tmp_memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pool 模式无 board_name，scope 应为 market。"""
        svc = AgentReportService(mock_agent, db_path=tmp_memory.db_path)

        pool_data = {
            "pool_name": "半导体精选",
            "timestamp": "2026-07-05 15:00",
            "total_stocks": 30,
            "top_inflow_today": [
                {"code": "600519", "name": "贵州茅台", "main_net_yi": 3.5, "main_net_ratio": 2.1},
            ],
            "top_outflow_today": [],
            "top_inflow_30d": [],
            "top_outflow_30d": [],
        }
        monkeypatch.setattr(svc, "_collect_pool_data", lambda *a, **kw: pool_data)

        svc.generate_daily_report(pool_name="semicon")

        events = tmp_memory.query(event_type="analysis_record")
        assert len(events) == 1
        assert events[0]["scope"] == "market"
        assert "贵州茅台" in events[0]["summary"]


# ---------- 向后兼容测试 ----------


class TestBackwardCompat:
    def test_no_db_path_skips_memory(
        self, mock_agent: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db_path=None 时不初始化 memory，不报错。"""
        svc = AgentReportService(mock_agent)  # 不传 db_path
        assert svc._memory is None

        board_data = {"board_name": "半导体", "avg_change_pct": 1.0}
        monkeypatch.setattr(svc, "_collect_board_data", lambda *a, **kw: board_data)

        # 不应报错
        text = svc.generate_daily_report(board_code="BK1106", board_name="半导体")
        assert text == "报告正文"

    def test_empty_data_skips_recording(
        self, mock_agent: MagicMock, tmp_memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无数据时返回提示语，不写 episodic memory。"""
        svc = AgentReportService(mock_agent, db_path=tmp_memory.db_path)
        monkeypatch.setattr(svc, "_collect_board_data", lambda *a, **kw: {})

        text = svc.generate_daily_report(board_code="BK1106")
        assert "暂无数据" in text

        events = tmp_memory.query(event_type="analysis_record")
        assert len(events) == 0
