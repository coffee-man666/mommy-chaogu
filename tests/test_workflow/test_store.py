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
