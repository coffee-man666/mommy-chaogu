from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools import ToolContext
from mommy_chaogu.cli_commands import workflow as workflow_cli
from mommy_chaogu.market_data.types import Money, MoneyFlow
from mommy_chaogu.workflow.spec import WorkflowSpec


def _flow() -> MoneyFlow:
    return MoneyFlow(
        code="600519",
        name="贵州茅台",
        timestamp=datetime(2026, 7, 1, 15),
        main_net=Money.from_yuan("100"),
        small_net=Money.from_yuan("0"),
        medium_net=Money.from_yuan("0"),
        large_net=Money.from_yuan("0"),
        super_large_net=Money.from_yuan("0"),
        main_net_ratio=Decimal("1"),
    )


def test_add_run_list_delete_full_chain(tmp_path: Path, monkeypatch, capsys) -> None:
    db = tmp_path / "agent.db"
    monkeypatch.setattr(workflow_cli, "AGENT_DB", db)
    source = tmp_path / "workflow.json"
    spec = WorkflowSpec.from_dict(
        {
            "id": "user_cli",
            "trigger_patterns": ["cli test"],
            "description": "CLI test",
            "steps": [
                {
                    "tool_name": "screen_inflow_stocks",
                    "display_name": "筛选",
                    "inputs": {"codes": {"kind": "literal", "value": ["600519"]}},
                }
            ],
        }
    )
    source.write_text(spec.to_json(), encoding="utf-8")
    args = MagicMock(file=str(source))
    assert workflow_cli._cmd_add(args) == 0

    adapter = MagicMock()
    adapter.get_today_money_flow.return_value = [_flow()]
    monkeypatch.setattr(workflow_cli, "_build_agent_context", lambda: ToolContext(adapter=adapter))
    run_args = MagicMock(id="user_cli", overrides=[])
    assert workflow_cli._cmd_run(run_args) == 0
    output = capsys.readouterr().out
    assert "user_cli" in output

    list_args = MagicMock()
    assert workflow_cli._cmd_list(list_args) == 0
    assert "hits=1" in capsys.readouterr().out

    assert workflow_cli._cmd_delete(MagicMock(id="user_cli")) == 0
    capsys.readouterr()
    assert workflow_cli._cmd_list(list_args) == 0
    assert "user_cli" not in capsys.readouterr().out
