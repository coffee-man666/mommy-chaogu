"""vector_search 单测：向量检索。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.vector_search import VectorSearch, _pack_vector, _unpack_vector


@pytest.fixture
def episodic(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "test.db")


def make_mock_client(dim: int = 4) -> MagicMock:
    """构造 mock client，返回固定向量。"""
    client = MagicMock()

    def mock_embed(model: str, input: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        # 基于输入文本生成简单的伪向量（保证相似文本 → 相似向量）
        vec = [float(len(input) + i) / 100 for i in range(dim)]
        resp.data = [MagicMock()]
        resp.data[0].embedding = vec
        return resp

    client.embeddings.create.side_effect = mock_embed
    return client


def make_mock_client_with_vec(vec: list[float]) -> MagicMock:
    """构造 mock client，返回指定向量。"""
    client = MagicMock()
    resp = MagicMock()
    resp.data = [MagicMock()]
    resp.data[0].embedding = vec
    client.embeddings.create.return_value = resp
    return client


class TestPackUnpack:
    def test_pack_unpack_roundtrip(self) -> None:
        vec = [1.0, 2.0, 3.0, 4.0]
        packed = _pack_vector(vec)
        unpacked = _unpack_vector(packed, 4)
        assert len(unpacked) == 4
        assert abs(unpacked[0] - 1.0) < 0.001
        assert abs(unpacked[3] - 4.0) < 0.001


class TestVectorSearchInit:
    def test_init_creates_tables(self, episodic: EpisodicMemory) -> None:
        """初始化后元数据表存在。"""
        client = make_mock_client(dim=4)
        VectorSearch(episodic, client, model="test", dim=4)

        from sqlalchemy import text

        with episodic.engine.begin() as conn:
            # 元数据表应该存在
            result = conn.execute(text("SELECT COUNT(*) FROM episodic_embeddings")).scalar()
            assert result == 0


class TestStoreEmbedding:
    def test_store_and_stats(self, episodic: EpisodicMemory) -> None:
        """存储 embedding 后 stats 正确。"""
        # 先写入一个事件
        eid = episodic.write(
            event_type="analysis_record",
            scope="market",
            summary="测试事件",
            data={},
        )

        client = make_mock_client(dim=4)
        vs = VectorSearch(episodic, client, model="test", dim=4)

        vec = [1.0, 2.0, 3.0, 4.0]
        ok = vs.store_embedding(eid, vec)
        assert ok is True

        stats = vs.stats()
        assert stats["total_events"] == 1
        assert stats["embedded"] == 1
        assert stats["coverage"] == 1.0


class TestEmbedEvent:
    def test_embed_event_success(self, episodic: EpisodicMemory) -> None:
        """embed_event 成功存储。"""
        eid = episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            code="603662",
            name="柯力传感",
            summary="底部反转信号",
            data={"price": 80.0},
        )

        client = make_mock_client(dim=4)
        vs = VectorSearch(episodic, client, model="test", dim=4)

        ok = vs.embed_event(eid, "底部反转信号 price 80.0")
        assert ok is True

        stats = vs.stats()
        assert stats["embedded"] == 1

    def test_embed_event_api_failure(self, episodic: EpisodicMemory) -> None:
        """embedding API 失败返回 False。"""
        eid = episodic.write(
            event_type="analysis_record",
            scope="market",
            summary="测试",
            data={},
        )

        client = MagicMock()
        client.embeddings.create.side_effect = Exception("API down")

        vs = VectorSearch(episodic, client, model="test", dim=4)
        ok = vs.embed_event(eid, "测试")
        assert ok is False


class TestEmbedPending:
    def test_embed_pending(self, episodic: EpisodicMemory) -> None:
        """为未 embedding 的事件批量生成。"""
        for i in range(3):
            episodic.write(
                event_type="analysis_record",
                scope="market",
                summary=f"事件 {i}",
                data={"index": i},
            )

        client = make_mock_client(dim=4)
        vs = VectorSearch(episodic, client, model="test", dim=4)

        results = vs.embed_pending()
        assert results["embedded"] == 3
        assert results["failed"] == 0

        # 再跑一次应该都是 skipped（已经有 embedding 了）
        results2 = vs.embed_pending()
        assert results2["embedded"] == 0


class TestSearchSimilar:
    def test_search_returns_results(self, episodic: EpisodicMemory) -> None:
        """search_similar 返回相似事件。"""
        eid = episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            code="603662",
            name="柯力传感",
            summary="半导体暴跌主力流出",
            data={},
        )

        client = make_mock_client(dim=4)
        vs = VectorSearch(episodic, client, model="test", dim=4)

        # 手动存储一个已知向量
        vs.store_embedding(eid, [1.0, 0.0, 0.0, 0.0])

        # 用接近的向量搜索
        search_client = make_mock_client_with_vec([0.9, 0.1, 0.0, 0.0])
        vs._client = search_client  # type: ignore[attr-defined]

        results = vs.search_similar("半导体暴跌", top_k=5)
        assert len(results) >= 1
        assert results[0]["id"] == eid
        assert "distance" in results[0]

    def test_search_no_embeddings(self, episodic: EpisodicMemory) -> None:
        """没有 embedding 时返回空列表。"""
        episodic.write(
            event_type="analysis_record",
            scope="market",
            summary="测试",
            data={},
        )

        client = make_mock_client(dim=4)
        vs = VectorSearch(episodic, client, model="test", dim=4)

        results = vs.search_similar("测试查询", top_k=5)
        assert results == []

    def test_search_api_failure(self, episodic: EpisodicMemory) -> None:
        """embedding API 失败返回空列表。"""
        client = MagicMock()
        client.embeddings.create.side_effect = Exception("API down")

        vs = VectorSearch(episodic, client, model="test", dim=4)
        results = vs.search_similar("测试", top_k=5)
        assert results == []


class TestStats:
    def test_empty_stats(self, episodic: EpisodicMemory) -> None:
        """空库 stats。"""
        client = make_mock_client(dim=4)
        vs = VectorSearch(episodic, client, model="test", dim=4)

        stats = vs.stats()
        assert stats["total_events"] == 0
        assert stats["embedded"] == 0
        assert stats["coverage"] == 0.0
