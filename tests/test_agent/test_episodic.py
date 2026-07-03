"""EpisodicMemory 单测：SQLite 持久化结构化市场事件记忆。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test_episodic.db")


class TestEpisodicCRUD:
    def test_write_returns_id(self, episodic: EpisodicMemory) -> None:
        """write 返回自增 id。"""
        id1 = episodic.write(
            event_type="market_snapshot",
            scope="market",
            summary="沪指收涨",
            data={"close": 3200},
        )
        id2 = episodic.write(
            event_type="market_snapshot",
            scope="market",
            summary="创业板指回落",
            data={"close": 2100},
        )
        assert isinstance(id1, int)
        assert id2 == id1 + 1

    def test_write_and_get_by_id(self, episodic: EpisodicMemory) -> None:
        """写入后 get_by_id 能取回所有字段，JSON 已解析。"""
        eid = episodic.write(
            event_type="market_snapshot",
            scope="market",
            summary="沪指收涨 1.2%",
            data={"sh_index": 3200, "volume": 5e10},
            tags=["bullish", "large_cap"],
            data_coverage={"kline": True, "tick": False},
            confidence=0.8,
            trade_date="2026-07-01",
        )

        event = episodic.get_by_id(eid)
        assert event is not None
        assert event["id"] == eid
        assert event["event_type"] == "market_snapshot"
        assert event["scope"] == "market"
        assert event["summary"] == "沪指收涨 1.2%"
        assert event["code"] is None
        assert event["name"] is None
        assert event["trade_date"] == "2026-07-01"
        assert event["data"] == {"sh_index": 3200, "volume": 5e10}
        assert event["tags"] == ["bullish", "large_cap"]
        assert event["data_coverage"] == {"kline": True, "tick": False}
        assert event["confidence"] == 0.8
        assert event["source"] == "agent"
        assert event["prediction_id"] is None
        assert event["timestamp"] is not None
        assert event["created_at"] is not None

    def test_write_with_all_params(self, episodic: EpisodicMemory) -> None:
        """带全部可选参数写入后能正确读回。"""
        eid = episodic.write(
            event_type="stock_signal",
            scope="stock:600519",
            summary="茅台突破前高",
            data={"price": 1680, "change_pct": 3.5},
            code="600519",
            name="贵州茅台",
            tags=["breakout", "ma_bull"],
            data_coverage={"kline": True, "tick": True},
            source="scanner",
            confidence=0.9,
            trade_date="2026-07-02",
            prediction_id=42,
        )
        event = episodic.get_by_id(eid)
        assert event is not None
        assert event["code"] == "600519"
        assert event["name"] == "贵州茅台"
        assert event["tags"] == ["breakout", "ma_bull"]
        assert event["data_coverage"] == {"kline": True, "tick": True}
        assert event["source"] == "scanner"
        assert event["confidence"] == 0.9
        assert event["prediction_id"] == 42
        assert event["trade_date"] == "2026-07-02"

    def test_get_by_id_not_found(self, episodic: EpisodicMemory) -> None:
        """不存在的 id 返回 None。"""
        assert episodic.get_by_id(9999) is None


class TestEpisodicQuery:
    def test_query_by_scope(self, episodic: EpisodicMemory) -> None:
        """按 scope 精确匹配。"""
        episodic.write("market_snapshot", "market", "a", {})
        episodic.write("stock_signal", "stock:600519", "b", {})

        rows = episodic.query(scope="market")
        assert len(rows) == 1
        assert rows[0]["scope"] == "market"

    def test_query_by_scope_prefix(self, episodic: EpisodicMemory) -> None:
        """scope 前缀匹配：'sector:' 匹配 'sector:创新药'。"""
        episodic.write("sector_pulse", "sector:创新药", "a", {})
        episodic.write("sector_pulse", "sector:半导体", "b", {})
        episodic.write("market_snapshot", "market", "c", {})

        rows = episodic.query(scope="sector:")
        assert len(rows) == 2
        scopes = {r["scope"] for r in rows}
        assert "sector:创新药" in scopes
        assert "sector:半导体" in scopes
        assert "market" not in scopes

    def test_query_by_event_type(self, episodic: EpisodicMemory) -> None:
        """按 event_type 过滤。"""
        episodic.write("market_snapshot", "market", "a", {})
        episodic.write("stock_signal", "stock:600519", "b", {})
        episodic.write("market_snapshot", "market", "c", {})

        rows = episodic.query(event_type="market_snapshot")
        assert len(rows) == 2
        assert all(r["event_type"] == "market_snapshot" for r in rows)

    def test_query_by_code(self, episodic: EpisodicMemory) -> None:
        """按 code 过滤。"""
        episodic.write("stock_signal", "stock:600519", "a", {}, code="600519")
        episodic.write("stock_signal", "stock:000001", "b", {}, code="000001")

        rows = episodic.query(code="600519")
        assert len(rows) == 1
        assert rows[0]["code"] == "600519"

    def test_query_by_date_range(self, episodic: EpisodicMemory) -> None:
        """按 trade_date 闭区间过滤。"""
        episodic.write("market_snapshot", "market", "a", {}, trade_date="2026-06-28")
        episodic.write("market_snapshot", "market", "b", {}, trade_date="2026-06-29")
        episodic.write("market_snapshot", "market", "c", {}, trade_date="2026-07-02")

        rows = episodic.query(start_date="2026-06-29", end_date="2026-07-01")
        assert len(rows) == 1
        assert rows[0]["trade_date"] == "2026-06-29"

    def test_query_limit(self, episodic: EpisodicMemory) -> None:
        """limit 截断结果。"""
        for i in range(5):
            episodic.write("market_snapshot", "market", f"msg-{i}", {})

        rows = episodic.query(limit=2)
        assert len(rows) == 2

    def test_query_empty(self, episodic: EpisodicMemory) -> None:
        """空库 query 返回空列表。"""
        assert episodic.query() == []


class TestEpisodicRecent:
    def test_recent_returns_recent_days(self, episodic: EpisodicMemory) -> None:
        """recent 只返回 days 天内的事件。"""
        # 直接写入一条当前时间的事件
        episodic.write("market_snapshot", "market", "today", {})

        rows = episodic.recent(days=7)
        assert len(rows) == 1
        assert rows[0]["summary"] == "today"

    def test_recent_with_scope(self, episodic: EpisodicMemory) -> None:
        """recent 支持 scope 过滤（含前缀匹配）。"""
        episodic.write("sector_pulse", "sector:创新药", "a", {})
        episodic.write("market_snapshot", "market", "b", {})

        rows = episodic.recent(days=7, scope="sector:")
        assert len(rows) == 1
        assert rows[0]["scope"] == "sector:创新药"


class TestEpisodicSummary:
    def test_summary_counts(self, episodic: EpisodicMemory) -> None:
        """summary 按 event_type / scope 分组计数，含时间跨度。"""
        episodic.write("market_snapshot", "market", "a", {})
        episodic.write("market_snapshot", "market", "b", {})
        episodic.write("stock_signal", "stock:600519", "c", {})

        s = episodic.summary()
        assert s["total"] == 3
        assert s["by_type"] == {"market_snapshot": 2, "stock_signal": 1}
        assert s["by_scope"] == {"market": 2, "stock:600519": 1}
        assert s["earliest"] is not None
        assert s["latest"] is not None

    def test_summary_empty(self, episodic: EpisodicMemory) -> None:
        """空库 summary 为 0 / 空。"""
        s = episodic.summary()
        assert s["total"] == 0
        assert s["by_type"] == {}
        assert s["by_scope"] == {}
        assert s["earliest"] is None
        assert s["latest"] is None


class TestEpisodicPersistence:
    def test_reopen_preserves_data(self, tmp_path: Path) -> None:
        """重新打开同一 db 文件，数据还在。"""
        db = tmp_path / "persist.db"
        em1 = EpisodicMemory(db)
        eid = em1.write(
            "market_snapshot",
            "market",
            "persisted",
            {"sh_index": 3200},
            tags=["bullish"],
        )

        em2 = EpisodicMemory(db)
        event = em2.get_by_id(eid)
        assert event is not None
        assert event["summary"] == "persisted"
        assert event["data"] == {"sh_index": 3200}
        assert event["tags"] == ["bullish"]
