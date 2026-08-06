from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools import ToolContext
from mommy_chaogu.cli_commands import workflow as workflow_cli
from mommy_chaogu.market_data.types import BarInterval, Money, MoneyFlow
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


def _regex_spec() -> WorkflowSpec:
    return WorkflowSpec.from_dict(
        {
            "id": "user_regex_cli",
            "trigger_patterns": ["regex cli test"],
            "description": "regex CLI test",
            "steps": [
                {
                    "tool_name": "check_kline_signal",
                    "display_name": "检查 K 线",
                    "inputs": {
                        "codes": {
                            "kind": "user_regex",
                            "pattern": r"(\d{6})",
                        },
                        "signal": {"kind": "literal", "value": "volume_breakout"},
                    },
                }
            ],
        }
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


def test_run_user_regex_with_input(tmp_path: Path, monkeypatch, capsys) -> None:
    db = tmp_path / "agent.db"
    monkeypatch.setattr(workflow_cli, "AGENT_DB", db)
    store = workflow_cli.WorkflowStore(db)
    try:
        store.save(_regex_spec())
    finally:
        store.close()

    adapter = MagicMock()
    adapter.get_bars.return_value = []
    monkeypatch.setattr(workflow_cli, "_build_agent_context", lambda: ToolContext(adapter=adapter))
    args = SimpleNamespace(
        id="user_regex_cli",
        overrides=[],
        user_input="分析 600519",
    )

    assert workflow_cli._cmd_run(args) == 0
    adapter.get_bars.assert_called_once_with("600519", interval=BarInterval.D1, limit=30)
    assert "user_regex_cli" in capsys.readouterr().out


def test_run_extractor_failure_is_friendly_without_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    db = tmp_path / "agent.db"
    monkeypatch.setattr(workflow_cli, "AGENT_DB", db)
    store = workflow_cli.WorkflowStore(db)
    try:
        store.save(_regex_spec())
    finally:
        store.close()

    adapter = MagicMock()
    monkeypatch.setattr(workflow_cli, "_build_agent_context", lambda: ToolContext(adapter=adapter))
    args = SimpleNamespace(id="user_regex_cli", overrides=[], user_input="")

    assert workflow_cli._cmd_run(args) == 1
    output = capsys.readouterr().out
    assert "工作流参数解析失败" in output
    assert "Traceback" not in output
    adapter.get_bars.assert_not_called()


def test_run_parser_accepts_input_and_explains_debug_output() -> None:
    parser = workflow_cli.build_workflow_parser()
    args = parser.parse_args(["run", "user_regex_cli", "--input", "分析 600519"])
    assert args.user_input == "分析 600519"
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    run_choice = next(action for action in subparsers._choices_actions if action.dest == "run")
    assert "无 LLM 总结" in run_choice.help
