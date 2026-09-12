from __future__ import annotations

from mommy_chaogu.workflow.spec import StepSpec, WorkflowSpec
from mommy_chaogu.workflow.store import WorkflowStore


def _spec(description: str = "first") -> WorkflowSpec:
    return WorkflowSpec(
        id="user_store",
        trigger_patterns=["store"],
        description=description,
        steps=[StepSpec("screen_inflow_stocks", "筛选")],
    )


def test_store_crud_and_update_preserves_hits(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "agent.db")
    store.save(_spec(), "source")
    assert store.load("user_store") == _spec()
    store.increment_hit("user_store")
    store.increment_hit("user_store")
    store.save(_spec("updated"), "new source")
    rows = store.load_all()
    assert rows[0][0].description == "updated"
    assert rows[0][1]["hit_count"] == 2
    assert store.delete("user_store") is True
    assert store.delete("user_store") is False
    store.close()


# ---------------------------------------------------------------------------
# 补充覆盖：坏 spec 行、metadata、排序、last_used、持久化重开
# ---------------------------------------------------------------------------


def test_load_missing_returns_none(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "agent.db")
    assert store.load("user_nope") is None
    assert store.metadata("user_nope") is None
    store.close()


def test_corrupt_spec_row_retained_as_none(tmp_path) -> None:
    """坏 spec 行在 load_all_records 保留为 None（供 stale 报告），load_all 跳过。"""
    from sqlalchemy import text

    store = WorkflowStore(tmp_path / "agent.db")
    store.save(_spec(), "source")
    with store.engine.begin() as conn:
        conn.execute(
            text("UPDATE custom_workflows SET spec_json = '{not json' WHERE id = 'user_store'")
        )
    records = store.load_all_records()
    assert len(records) == 1
    assert records[0][0] is None
    assert records[0][1]["id"] == "user_store"  # meta 仍在
    assert store.load_all() == []  # 坏行被跳过
    store.close()


def test_load_all_orders_by_created_at_then_id(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "agent.db")
    for i in range(3):
        store.save(
            WorkflowSpec(
                id=f"user_{i}",
                trigger_patterns=[f"t{i}"],
                description=f"d{i}",
                steps=[StepSpec("screen_inflow_stocks", "筛选")],
            )
        )
    ids = [meta["id"] for _spec, meta in store.load_all()]
    assert ids == ["user_0", "user_1", "user_2"]
    store.close()


def test_metadata_shape_excludes_spec_json(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "agent.db")
    store.save(_spec(), "原始描述文本")
    meta = store.metadata("user_store")
    assert meta is not None
    assert "spec_json" not in meta
    assert meta["source_text"] == "原始描述文本"
    assert meta["hit_count"] == 0
    assert meta["last_used"] is None
    assert meta["created_at"]
    store.close()


def test_increment_hit_updates_last_used(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "agent.db")
    store.save(_spec(), "source")
    store.increment_hit("user_store")
    meta = store.metadata("user_store")
    assert meta is not None
    assert meta["hit_count"] == 1
    assert meta["last_used"] is not None
    # 不存在的 id 不抛错、不建行
    store.increment_hit("user_ghost")
    assert store.metadata("user_ghost") is None
    store.close()


def test_roundtrip_preserves_optional_fields(tmp_path) -> None:
    """summary_template / use_llm_summary / params 序列化往返不丢。"""
    spec = WorkflowSpec(
        id="user_rich",
        trigger_patterns=["动量"],
        description="带模板",
        steps=[StepSpec("get_market_indexes", "指数")],
        summary_template="总结：{context}",
        use_llm_summary=False,
        params={"limit": 5},
    )
    store = WorkflowStore(tmp_path / "agent.db")
    store.save(spec)
    loaded = store.load("user_rich")
    assert loaded == spec
    assert loaded is not None
    assert loaded.summary_template == "总结：{context}"
    assert loaded.use_llm_summary is False
    assert loaded.params == {"limit": 5}
    store.close()


def test_reopen_persists_across_instances(tmp_path) -> None:
    """store 关闭重开后数据仍在（SQLite 持久化，非内存库）。"""
    db = tmp_path / "agent.db"
    store = WorkflowStore(db)
    store.save(_spec(), "source")
    store.increment_hit("user_store")
    store.close()

    store2 = WorkflowStore(db)
    meta = store2.metadata("user_store")
    assert meta is not None
    assert meta["hit_count"] == 1
    assert store2.load("user_store") == _spec()
    store2.close()
