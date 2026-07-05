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


class TestEpisodicContentHash:
    def test_write_with_content_hash(self, episodic: EpisodicMemory) -> None:
        """write 支持 content_hash 参数并存入。"""
        eid = episodic.write(
            "analysis_record",
            "stock:600519",
            "茅台突破",
            {"price": 1680},
            content_hash="abc123",
        )
        event = episodic.get_by_id(eid)
        assert event is not None
        assert event["content_hash"] == "abc123"

    def test_write_without_content_hash(self, episodic: EpisodicMemory) -> None:
        """不传 content_hash 时存为 None。"""
        eid = episodic.write("market_snapshot", "market", "a", {})
        event = episodic.get_by_id(eid)
        assert event is not None
        assert event["content_hash"] is None

    def test_exists_by_hash(self, episodic: EpisodicMemory) -> None:
        """exists_by_hash 检查同 scope + content_hash 是否存在。"""
        episodic.write(
            "analysis_record",
            "stock:600519",
            "茅台突破",
            {},
            content_hash="hash_a",
        )
        assert episodic.exists_by_hash("stock:600519", "hash_a") is True
        assert episodic.exists_by_hash("stock:600519", "hash_b") is False
        # 不同 scope 同 hash 不算重复
        assert episodic.exists_by_hash("stock:000001", "hash_a") is False

    def test_content_hash_migration_from_old_db(self, tmp_path: Path) -> None:
        """旧库（无 content_hash 列）打开后自动迁移添加列。"""
        db = tmp_path / "old.db"
        # 模拟旧 schema
        from sqlalchemy import create_engine, text

        engine = create_engine(f"sqlite:///{db}", future=True)
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE episodic_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trade_date TEXT,
                    event_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    code TEXT,
                    name TEXT,
                    data TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags TEXT DEFAULT '[]',
                    data_coverage TEXT DEFAULT '{}',
                    source TEXT DEFAULT 'agent',
                    confidence REAL DEFAULT 0.5,
                    prediction_id INTEGER,
                    created_at TEXT NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO episodic_events
                    (timestamp, event_type, scope, data, summary, created_at)
                VALUES ('2026-01-01', 'market_snapshot', 'market', '{}', 'old', '2026-01-01')
            """))
        engine.dispose()

        # 重新打开应自动迁移
        em = EpisodicMemory(db)
        events = em.query()
        assert len(events) == 1
        assert events[0]["content_hash"] is None
        # 迁移后能正常写入带 content_hash 的新事件
        eid = em.write("market_snapshot", "market", "new", {}, content_hash="h1")
        assert em.get_by_id(eid)["content_hash"] == "h1"


class TestEpisodicCleanupOld:
    def test_cleanup_old_signal_events(self, episodic: EpisodicMemory) -> None:
        """signal_event 超过 days 天被清理。"""
        from datetime import UTC, datetime, timedelta

        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        # 手动写入一条 100 天前的 signal_event
        from sqlalchemy import text

        with episodic.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO episodic_events
                    (timestamp, event_type, scope, data, summary, created_at)
                VALUES (:ts, 'signal_event', 'market', '{}', 'old signal', :ts)
            """), {"ts": old_ts})

        deleted = episodic.cleanup_old(days=90)
        assert deleted == 1
        assert episodic.query() == []

    def test_cleanup_preserves_recent(self, episodic: EpisodicMemory) -> None:
        """近期事件不被清理。"""
        episodic.write("signal_event", "market", "recent", {})
        deleted = episodic.cleanup_old(days=90)
        assert deleted == 0
        assert len(episodic.query()) == 1

    def test_cleanup_preserves_long_retain_types(self, episodic: EpisodicMemory) -> None:
        """analysis_record / market_snapshot 保留更久（180 天）。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        # 100 天前的 analysis_record 不应被 90 天 cleanup 删除
        with episodic.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO episodic_events
                    (timestamp, event_type, scope, data, summary, created_at)
                VALUES (:ts, 'analysis_record', 'market', '{}', 'old analysis', :ts)
            """), {"ts": old_ts})
            conn.execute(text("""
                INSERT INTO episodic_events
                    (timestamp, event_type, scope, data, summary, created_at)
                VALUES (:ts, 'market_snapshot', 'market', '{}', 'old snapshot', :ts)
            """), {"ts": old_ts})

        deleted = episodic.cleanup_old(days=90)
        assert deleted == 0
        assert len(episodic.query()) == 2

    def test_cleanup_removes_long_retain_after_180d(self, episodic: EpisodicMemory) -> None:
        """analysis_record 超过 180 天被清理。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        old_ts = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with episodic.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO episodic_events
                    (timestamp, event_type, scope, data, summary, created_at)
                VALUES (:ts, 'analysis_record', 'market', '{}', 'very old', :ts)
            """), {"ts": old_ts})

        deleted = episodic.cleanup_old(days=90)
        assert deleted == 1
        assert episodic.query() == []

    def test_cleanup_empty_db(self, episodic: EpisodicMemory) -> None:
        """空库 cleanup 返回 0。"""
        assert episodic.cleanup_old(days=90) == 0

    def test_cleanup_returns_count(self, episodic: EpisodicMemory) -> None:
        """cleanup 返回删除的条数。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        with episodic.engine.begin() as conn:
            for i in range(3):
                conn.execute(text("""
                    INSERT INTO episodic_events
                        (timestamp, event_type, scope, data, summary, created_at)
                    VALUES (:ts, 'signal_event', 'market', '{}', :s, :ts)
                """), {"ts": old_ts, "s": f"old-{i}"})

        deleted = episodic.cleanup_old(days=90)
        assert deleted == 3
