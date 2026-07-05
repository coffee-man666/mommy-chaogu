"""SemanticMemory 单测：SQLite 持久化知识记忆。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.agent.semantic_memory import SemanticMemory


@pytest.fixture
def semantic(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path / "test_semantic.db")


class TestSemanticCRUD:
    def test_upsert_returns_id(self, semantic: SemanticMemory) -> None:
        """upsert 返回自增 id。"""
        id1 = semantic.upsert(
            knowledge_type="sector_thesis",
            scope="sector:创新药",
            content="创新药板块进入上行周期",
        )
        id2 = semantic.upsert(
            knowledge_type="market_regime",
            scope="market",
            content="震荡市",
        )
        assert isinstance(id1, int)
        assert id2 == id1 + 1

    def test_upsert_and_get_by_id(self, semantic: SemanticMemory) -> None:
        """写入后 get_by_id 能取回所有字段，JSON 已解析。"""
        eid = semantic.upsert(
            knowledge_type="stock_insight",
            scope="stock:600519",
            content="茅台放量突破前高",
            confidence=0.9,
            source_ids=[101, 202],
        )
        entry = semantic.get_by_id(eid)
        assert entry is not None
        assert entry["id"] == eid
        assert entry["knowledge_type"] == "stock_insight"
        assert entry["scope"] == "stock:600519"
        assert entry["content"] == "茅台放量突破前高"
        assert entry["confidence"] == 0.9
        assert entry["source_event_ids"] == [101, 202]
        assert entry["status"] == "active"
        assert entry["hit_count"] == 0
        assert entry["miss_count"] == 0
        assert entry["created_at"] is not None
        assert entry["updated_at"] is not None

    def test_get_by_id_not_found(self, semantic: SemanticMemory) -> None:
        """不存在的 id 返回 None。"""
        assert semantic.get_by_id(9999) is None


class TestSemanticUpsert:
    def test_upsert_new_creates_active(self, semantic: SemanticMemory) -> None:
        """新条目状态为 active。"""
        eid = semantic.upsert(
            knowledge_type="pattern_observed",
            scope="market",
            content="放量突破后常有回踩",
        )
        entry = semantic.get_by_id(eid)
        assert entry is not None
        assert entry["status"] == "active"

    def test_upsert_same_scope_supersedes_old(self, semantic: SemanticMemory) -> None:
        """同 (knowledge_type, scope) 的旧 active 条目被标记为 superseded。"""
        old_id = semantic.upsert(
            knowledge_type="sector_thesis",
            scope="sector:半导体",
            content="半导体库存周期见底",
        )
        new_id = semantic.upsert(
            knowledge_type="sector_thesis",
            scope="sector:半导体",
            content="半导体需求超预期，价格拐点确认",
        )

        assert new_id != old_id
        old_entry = semantic.get_by_id(old_id)
        new_entry = semantic.get_by_id(new_id)
        assert old_entry is not None
        assert new_entry is not None
        assert old_entry["status"] == "superseded"
        assert new_entry["status"] == "active"

    def test_upsert_preserves_different_types(self, semantic: SemanticMemory) -> None:
        """同 scope 但不同 knowledge_type，两者都保持 active。"""
        id1 = semantic.upsert(
            knowledge_type="sector_thesis",
            scope="market",
            content="大盘结构性牛市",
        )
        id2 = semantic.upsert(
            knowledge_type="market_regime",
            scope="market",
            content="量能放大，情绪转暖",
        )
        e1 = semantic.get_by_id(id1)
        e2 = semantic.get_by_id(id2)
        assert e1 is not None and e2 is not None
        assert e1["status"] == "active"
        assert e2["status"] == "active"


class TestSemanticQuery:
    def test_query_by_scope(self, semantic: SemanticMemory) -> None:
        """按 scope 过滤。"""
        semantic.upsert("sector_thesis", "sector:创新药", "a")
        semantic.upsert("stock_insight", "stock:600519", "b")

        rows = semantic.query(scope="sector:创新药")
        assert len(rows) == 1
        assert rows[0]["scope"] == "sector:创新药"

    def test_query_by_type(self, semantic: SemanticMemory) -> None:
        """按 knowledge_type 过滤。"""
        semantic.upsert("sector_thesis", "sector:创新药", "a")
        semantic.upsert("market_regime", "market", "b")
        semantic.upsert("sector_thesis", "sector:半导体", "c")

        rows = semantic.query(knowledge_type="sector_thesis")
        assert len(rows) == 2
        assert all(r["knowledge_type"] == "sector_thesis" for r in rows)

    def test_query_status_filter(self, semantic: SemanticMemory) -> None:
        """status 过滤能取到 superseded 条目。"""
        semantic.upsert("sector_thesis", "sector:创新药", "v1")
        semantic.upsert("sector_thesis", "sector:创新药", "v2")

        active_rows = semantic.query(scope="sector:创新药", status="active")
        superseded_rows = semantic.query(scope="sector:创新药", status="superseded")
        assert len(active_rows) == 1
        assert len(superseded_rows) == 1

    def test_get_active(self, semantic: SemanticMemory) -> None:
        """get_active 按 updated_at 倒序返回 active 条目。"""
        for i in range(3):
            semantic.upsert("market_regime", "market", f"regime-{i}")
        # 第 4 次 supersede 前三条中的第一条不会被触发，因为是不同 scope
        semantic.upsert("market_regime", "market", "latest")

        rows = semantic.get_active(limit=10)
        assert len(rows) == 1
        assert rows[0]["content"] == "latest"

    def test_query_empty(self, semantic: SemanticMemory) -> None:
        """空库 query 返回空列表。"""
        assert semantic.query() == []


class TestSemanticSearch:
    def test_search_finds_keyword(self, semantic: SemanticMemory) -> None:
        """search 按 content 关键词命中。"""
        semantic.upsert("sector_thesis", "sector:创新药", "创新药进入上行周期")
        semantic.upsert("market_regime", "market", "震荡市格局")

        rows = semantic.search("上行")
        assert len(rows) == 1
        assert "上行" in rows[0]["content"]

    def test_search_no_match(self, semantic: SemanticMemory) -> None:
        """无匹配返回空列表。"""
        semantic.upsert("market_regime", "market", "震荡市")
        assert semantic.search("不存在的关键词") == []

    def test_search_case_insensitive(self, semantic: SemanticMemory) -> None:
        """LIKE 默认大小写不敏感（SQLite）。"""
        semantic.upsert("pattern_observed", "market", "Volume Spike Pattern")
        rows = semantic.search("volume spike")
        assert len(rows) == 1
        assert rows[0]["content"] == "Volume Spike Pattern"


class TestSemanticSupersede:
    def test_supersede_sets_status(self, semantic: SemanticMemory) -> None:
        """supersede 将状态置为 superseded。"""
        eid = semantic.upsert("market_regime", "market", "牛市初期")
        semantic.supersede(eid, reason="已被证伪")
        entry = semantic.get_by_id(eid)
        assert entry is not None
        assert entry["status"] == "superseded"
        assert "已被证伪" in entry["content"]

    def test_supersede_returns_id(self, semantic: SemanticMemory) -> None:
        """supersede 返回被 supersede 的条目 id。"""
        eid = semantic.upsert("market_regime", "market", "牛市初期")
        assert semantic.supersede(eid) == eid


class TestSemanticConfidence:
    def test_update_confidence(self, semantic: SemanticMemory) -> None:
        """update_confidence 更新置信度与 hit/miss 计数。"""
        eid = semantic.upsert("sector_thesis", "sector:创新药", "thesis")
        semantic.update_confidence(eid, confidence=0.95, hit_count=3, miss_count=1)
        entry = semantic.get_by_id(eid)
        assert entry is not None
        assert entry["confidence"] == 0.95
        assert entry["hit_count"] == 3
        assert entry["miss_count"] == 1

    def test_recalibrate_blends_old_and_new(self, semantic: SemanticMemory) -> None:
        """recalibrate: confidence = 0.5 * old + 0.5 * hit_rate。"""
        eid = semantic.upsert("sector_thesis", "sector:创新药", "thesis", confidence=0.8)
        semantic.recalibrate([{"entry_id": eid, "hit_rate": 0.6, "hit_count": 6, "miss_count": 4}])
        entry = semantic.get_by_id(eid)
        assert entry is not None
        assert entry["confidence"] == pytest.approx(0.5 * 0.8 + 0.5 * 0.6)
        assert entry["hit_count"] == 6
        assert entry["miss_count"] == 4


class TestSemanticSummary:
    def test_summary_counts(self, semantic: SemanticMemory) -> None:
        """summary 统计 total / active / superseded 及分组计数。"""
        semantic.upsert("sector_thesis", "sector:创新药", "v1")
        semantic.upsert("sector_thesis", "sector:创新药", "v2")  # supersede v1
        semantic.upsert("market_regime", "market", "regime")

        s = semantic.summary()
        assert s["total"] == 3
        assert s["active"] == 2
        assert s["superseded"] == 1
        assert s["by_type"] == {"sector_thesis": 2, "market_regime": 1}
        assert s["by_scope"] == {"sector:创新药": 2, "market": 1}

    def test_summary_empty(self, semantic: SemanticMemory) -> None:
        """空库 summary 为 0 / 空。"""
        s = semantic.summary()
        assert s["total"] == 0
        assert s["active"] == 0
        assert s["superseded"] == 0
        assert s["by_type"] == {}
        assert s["by_scope"] == {}


class TestSemanticPersistence:
    def test_reopen_preserves_data(self, tmp_path: Path) -> None:
        """重新打开同一 db 文件，数据还在。"""
        db = tmp_path / "persist.db"
        sm1 = SemanticMemory(db)
        eid = sm1.upsert(
            knowledge_type="stock_insight",
            scope="stock:600519",
            content="茅台长期受益于消费升级",
            confidence=0.85,
            source_ids=[10, 20],
        )

        sm2 = SemanticMemory(db)
        entry = sm2.get_by_id(eid)
        assert entry is not None
        assert entry["content"] == "茅台长期受益于消费升级"
        assert entry["confidence"] == 0.85
        assert entry["source_event_ids"] == [10, 20]


class TestInsightSummary:
    def test_save_insight_returns_id(self, semantic: SemanticMemory) -> None:
        """save_insight 返回自增 id。"""
        id1 = semantic.save_insight(
            {
                "period_start": "2026-06-23",
                "period_end": "2026-06-29",
                "summary": "本周复盘：3 条预测命中 2 条",
            }
        )
        id2 = semantic.save_insight(
            {
                "period_start": "2026-06-30",
                "period_end": "2026-07-06",
                "summary": "本周复盘：5 条预测命中 1 条",
            }
        )
        assert isinstance(id1, int)
        assert id2 == id1 + 1

    def test_get_latest_insight(self, semantic: SemanticMemory) -> None:
        """get_latest_insight 返回最近写入的一条。"""
        semantic.save_insight(
            {
                "period_start": "2026-06-23",
                "period_end": "2026-06-29",
                "summary": "第一周",
            }
        )
        semantic.save_insight(
            {
                "period_start": "2026-06-30",
                "period_end": "2026-07-06",
                "summary": "第二周",
                "key_observations": ["板块A走强", "板块B走弱"],
                "predictions_reviewed": 4,
                "hit_rate": 0.75,
                "confidence_adjustment": 0.05,
            }
        )

        latest = semantic.get_latest_insight()
        assert latest is not None
        assert latest["summary"] == "第二周"
        assert latest["period_start"] == "2026-06-30"
        assert latest["period_end"] == "2026-07-06"
        assert latest["key_observations"] == ["板块A走强", "板块B走弱"]
        assert latest["predictions_reviewed"] == 4
        assert latest["hit_rate"] == 0.75
        assert latest["confidence_adjustment"] == 0.05
        assert latest["created_at"] is not None

    def test_get_latest_insight_empty(self, semantic: SemanticMemory) -> None:
        """空库 get_latest_insight 返回 None。"""
        assert semantic.get_latest_insight() is None

    def test_save_insight_minimal_fields(self, semantic: SemanticMemory) -> None:
        """只传必填字段，其余取默认值。"""
        eid = semantic.save_insight(
            {
                "period_start": "2026-06-23",
                "period_end": "2026-06-29",
                "summary": "简短复盘",
            }
        )
        entry = semantic.get_latest_insight()
        assert entry is not None
        assert entry["id"] == eid
        assert entry["key_observations"] == []
        assert entry["predictions_reviewed"] == 0
        assert entry["hit_rate"] is None
        assert entry["confidence_adjustment"] is None

    def test_save_insight_persists_across_reopen(self, tmp_path: Path) -> None:
        """重新打开同一 db，insight_summary 数据还在。"""
        db = tmp_path / "insight_persist.db"
        sm1 = SemanticMemory(db)
        sm1.save_insight(
            {
                "period_start": "2026-06-23",
                "period_end": "2026-06-29",
                "summary": "持久化测试",
            }
        )

        sm2 = SemanticMemory(db)
        latest = sm2.get_latest_insight()
        assert latest is not None
        assert latest["summary"] == "持久化测试"
