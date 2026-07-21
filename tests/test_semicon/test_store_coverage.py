"""SemiconStore CRUD + 查询测试（PLAN 三档 #12 覆盖率提升）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.semicon.store import (
    ChainPosition,
    SemiconStore,
    StockAlreadyExistsError,
    StockNotFoundError,
    Subcategory,
)


@pytest.fixture
def store(tmp_path: Path) -> SemiconStore:
    return SemiconStore(tmp_path / "test_semicon.db")


class TestSemiconCRUD:
    def test_add_and_get(self, store: SemiconStore) -> None:
        stock = store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        assert stock.code == "600519"
        assert stock.name == "贵州茅台"

        fetched = store.get("600519")
        assert fetched is not None
        assert fetched.name == "贵州茅台"

    def test_add_duplicate_raises(self, store: SemiconStore) -> None:
        store.add("600519", "茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        with pytest.raises(StockAlreadyExistsError):
            store.add("600519", "茅台2", ChainPosition.UPSTREAM, Subcategory.MCU)

    def test_get_nonexistent_returns_none(self, store: SemiconStore) -> None:
        assert store.get("999999") is None

    def test_require_nonexistent_raises(self, store: SemiconStore) -> None:
        with pytest.raises(StockNotFoundError):
            store.require("999999")

    def test_remove(self, store: SemiconStore) -> None:
        store.add("600519", "茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        store.remove("600519")
        assert store.get("600519") is None

    def test_remove_nonexistent_raises(self, store: SemiconStore) -> None:
        with pytest.raises(StockNotFoundError):
            store.remove("999999")

    def test_update_fields(self, store: SemiconStore) -> None:
        store.add("600519", "茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        updated = store.update(
            "600519",
            name="贵州茅台更新",
            subcategory=Subcategory.PROCESSOR,
            note="测试备注",
        )
        assert updated.name == "贵州茅台更新"
        assert updated.subcategory == Subcategory.PROCESSOR
        assert updated.note == "测试备注"

    def test_update_nonexistent_raises(self, store: SemiconStore) -> None:
        with pytest.raises(StockNotFoundError):
            store.update("999999", name="x")


class TestSemiconBulkUpsert:
    def test_insert_new(self, store: SemiconStore) -> None:
        rows = [
            ("600519", "茅台", "下游", "存储", None, "主板", None),
            ("000001", "平安", "下游", "MCU", None, "主板", None),
        ]
        result = store.bulk_upsert(rows)
        assert result["inserted"] == 2
        assert result["updated"] == 0
        assert result["skipped"] == 0

    def test_skip_existing(self, store: SemiconStore) -> None:
        store.add("600519", "茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        rows = [("600519", "茅台2", "上游", "MCU", None, "主板", None)]
        result = store.bulk_upsert(rows, overwrite=False)
        assert result["inserted"] == 0
        assert result["skipped"] == 1
        # 未覆盖
        stock = store.get("600519")
        assert stock.subcategory == Subcategory.MEMORY

    def test_overwrite_existing(self, store: SemiconStore) -> None:
        store.add("600519", "茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        rows = [("600519", "茅台2", "上游", "MCU", None, "主板", None)]
        result = store.bulk_upsert(rows, overwrite=True)
        assert result["updated"] == 1
        stock = store.get("600519")
        assert stock.name == "茅台2"
        assert stock.chain_position == "上游"


class TestSemiconQuery:
    @pytest.fixture
    def populated_store(self, store: SemiconStore) -> SemiconStore:
        store.add("600519", "茅台", ChainPosition.DOWNSTREAM, Subcategory.MEMORY)
        store.add("000001", "平安", ChainPosition.DOWNSTREAM, Subcategory.MCU)
        store.add("688981", "中芯", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY)
        return store

    def test_list_all(self, populated_store: SemiconStore) -> None:
        stocks = populated_store.list_all()
        assert len(stocks) == 3

    def test_list_by_chain(self, populated_store: SemiconStore) -> None:
        downstream = populated_store.list_by_chain(ChainPosition.DOWNSTREAM)
        assert len(downstream) == 2
        midstream = populated_store.list_by_chain(ChainPosition.MIDSTREAM)
        assert len(midstream) == 1

    def test_list_by_subcategory(self, populated_store: SemiconStore) -> None:
        memory = populated_store.list_by_subcategory(Subcategory.MEMORY)
        assert len(memory) == 1
        assert memory[0].code == "600519"

    def test_list_codes(self, populated_store: SemiconStore) -> None:
        codes = populated_store.list_codes()
        assert len(codes) == 3
        assert codes == sorted(codes)

    def test_count_by_chain(self, populated_store: SemiconStore) -> None:
        counts = populated_store.count_by_chain()
        chain_map = dict(counts)
        assert chain_map[ChainPosition.DOWNSTREAM] == 2
        assert chain_map[ChainPosition.MIDSTREAM] == 1

    def test_count_by_subcategory(self, populated_store: SemiconStore) -> None:
        counts = populated_store.count_by_subcategory()
        assert len(counts) >= 2

    def test_search_by_name(self, populated_store: SemiconStore) -> None:
        results = populated_store.search("茅台")
        assert len(results) == 1
        assert results[0].code == "600519"

    def test_search_no_match(self, populated_store: SemiconStore) -> None:
        results = populated_store.search("不存在的公司")
        assert len(results) == 0

    def test_empty_store_queries(self, store: SemiconStore) -> None:
        assert store.list_all() == []
        assert store.list_codes() == []
        assert store.count_by_chain() == []
        assert store.count_by_subcategory() == []
