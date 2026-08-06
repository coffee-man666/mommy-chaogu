from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.cli_commands import workflow as workflow_cli
from mommy_chaogu.workflow.spec import WorkflowSpec
from mommy_chaogu.workflow.store import WorkflowStore


def _spec(tool_name: str = "screen_inflow_stocks") -> WorkflowSpec:
    return WorkflowSpec.from_dict(
        {
            "id": "user_smoke",
            "trigger_patterns": ["smoke opinion"],
            "description": "smoke",
            "steps": [{"tool_name": tool_name, "display_name": "检查"}],
        }
    )


def test_dry_run_validates_against_actual_registry_without_calling_adapter() -> None:
    from scripts.smoke_workflow import _dry_run_validate

    adapter = MagicMock()
    issues = _dry_run_validate(_spec(), ToolRegistry(ToolContext(adapter=adapter)))

    assert issues == []
    adapter.get_today_money_flow.assert_not_called()
    adapter.get_quote.assert_not_called()


def test_dry_run_rejects_tool_missing_from_runtime_registry() -> None:
    from scripts.smoke_workflow import _dry_run_validate

    registry = MagicMock()
    registry.tool_names.return_value = ["get_quote"]

    with pytest.raises(ValueError, match="未在当前 ToolRegistry 注册"):
        _dry_run_validate(_spec(), registry)


def test_real_runtime_builder_only_opens_market_cache(tmp_path: Path, monkeypatch) -> None:
    from scripts import smoke_workflow

    market_db = tmp_path / "market.db"
    monkeypatch.setattr(smoke_workflow, "MARKET_DB", market_db)
    adapter, registry = smoke_workflow._build_real_runtime()
    try:
        assert "screen_inflow_stocks" in registry.tool_names()
        assert market_db.exists()
    finally:
        adapter.close()


def test_create_dry_run_uses_compiler_without_persisting(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    db = tmp_path / "agent.db"
    monkeypatch.setattr(workflow_cli, "AGENT_DB", db)
    compiled = _spec()

    class FakeCompiler:
        def compile(self, viewpoint: str, *, current_spec=None):  # type: ignore[no-untyped-def]
            assert viewpoint == "smoke opinion"
            assert current_spec is None
            return SimpleNamespace(kind="spec", spec=compiled, questions=[], errors=[], guidance="")

    monkeypatch.setattr(workflow_cli, "_compiler", lambda exclude_id=None: FakeCompiler())
    assert workflow_cli._cmd_compile(MagicMock(viewpoint="smoke opinion", dry_run=True)) == 0
    assert "user_smoke" in capsys.readouterr().out
    assert not db.exists()


def test_create_and_update_cli_persist_compiled_specs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "agent.db"
    monkeypatch.setattr(workflow_cli, "AGENT_DB", db)
    created = _spec()
    updated = WorkflowSpec.from_dict(
        {
            **created.to_dict(),
            "description": "updated smoke",
        }
    )
    calls: list[WorkflowSpec | None] = []

    class FakeCompiler:
        def __init__(self, result: WorkflowSpec) -> None:
            self._result = result

        def compile(self, viewpoint: str, *, current_spec=None):  # type: ignore[no-untyped-def]
            assert viewpoint in {"create smoke", "update smoke"}
            calls.append(current_spec)
            return SimpleNamespace(
                kind="spec", spec=self._result, questions=[], errors=[], guidance=""
            )

    monkeypatch.setattr(workflow_cli, "_compiler", lambda exclude_id=None: FakeCompiler(created))
    assert workflow_cli._cmd_compile(MagicMock(viewpoint="create smoke", dry_run=False)) == 0

    store = WorkflowStore(db)
    try:
        assert store.load("user_smoke") is not None
    finally:
        store.close()

    monkeypatch.setattr(workflow_cli, "_compiler", lambda exclude_id=None: FakeCompiler(updated))
    assert workflow_cli._cmd_update(SimpleNamespace(id="user_smoke", viewpoint="update smoke")) == 0
    assert calls[-1] is not None
    assert calls[-1].id == "user_smoke"

    store = WorkflowStore(db)
    try:
        saved = store.load("user_smoke")
        assert saved is not None
        assert saved.description == "updated smoke"
    finally:
        store.close()
