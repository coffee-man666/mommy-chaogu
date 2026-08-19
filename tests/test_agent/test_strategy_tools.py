"""User-visible Strategy Distillation vertical-slice tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.agent.tools.strategies import DEFS
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.strategy.models import StrategyCard


def _card(*, summary: str = "价格到达观察位时提醒，其余形态由用户人工确认。") -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "价格观察与均线压制",
        "source": {
            "type": "text",
            "title": "用户在当前对话提供的方法",
            "reference": "conversation:strategy-example",
            "content_hash": "a" * 64,
            "hash_scope": "supplied_excerpt",
            "excerpts": ["价格跌破 100 时提醒我；均线压制形态还要结合图形判断。"],
        },
        "original_intent": "把自己的观察方法留给 Agent，以后看别的股票也能复用。",
        "summary": summary,
        "applies_to": ["A 股个股", "日线观察"],
        "conditions": [
            {
                "id": "price-watch",
                "category": "risk",
                "statement": "价格低于 100 时提醒。",
                "automation": "supported",
                "reason": "现有报价与价格阈值告警可以直接表达。",
                "evidence_tools": ["get_quote"],
                "monitor_rule": {"condition": "price_below", "threshold": "100"},
            },
            {
                "id": "ema-suppression",
                "category": "observation",
                "statement": "观察 EMA55/EMA89 云带是否继续压制价格。",
                "automation": "manual",
                "reason": "独立算法包尚未与主程序的可靠数据口径接通。",
                "evidence_tools": ["research_stock"],
                "monitor_rule": None,
            },
        ],
        "assumptions": ["使用日线收盘确认"],
        "limitations": ["当前不提供历史回测或收益承诺"],
        "user_revisions": ["用户把价格阈值改为 100"],
    }


def _registry(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(
        ToolContext(
            adapter=MagicMock(),
            agent_db=tmp_path / "agent.db",
            portfolio_db=tmp_path / "portfolio.db",
        )
    )


def _call(registry: ToolRegistry, name: str, args: dict[str, object]) -> dict[str, object]:
    result = json.loads(registry.call(name, args))
    assert isinstance(result, dict)
    return result


def _save(registry: ToolRegistry, card: dict[str, object] | None = None) -> dict[str, object]:
    return _call(
        registry,
        "strategy_save",
        {
            "card": card or _card(),
            "user_confirmed": True,
            "confirmation_note": "用户看过最终人类可读卡片并明确说保存。",
        },
    )


def test_card_rejects_fake_monitor_support() -> None:
    card = _card()
    conditions = card["conditions"]
    assert isinstance(conditions, list)
    manual = conditions[1]
    assert isinstance(manual, dict)
    manual["monitor_rule"] = {"condition": "price_above", "threshold": 120}

    with pytest.raises(ValidationError, match="supported"):
        StrategyCard.model_validate(card)


def test_save_tool_schema_has_resolvable_root_definitions() -> None:
    parameters = next(item.parameters for item in DEFS if item.name == "strategy_save")
    properties = parameters["properties"]
    assert isinstance(properties, dict)
    card_schema = properties["card"]
    assert isinstance(card_schema, dict)

    assert "$defs" in parameters
    assert "$defs" not in card_schema
    assert "#/$defs/StrategySource" in json.dumps(card_schema)


def test_card_does_not_accept_unscoped_source_hash() -> None:
    card = _card()
    source = card["source"]
    assert isinstance(source, dict)
    source.pop("hash_scope")

    with pytest.raises(ValidationError, match="hash_scope"):
        StrategyCard.model_validate(card)


def test_supported_condition_must_name_current_evidence_tool() -> None:
    card = _card()
    conditions = card["conditions"]
    assert isinstance(conditions, list)
    supported = conditions[0]
    assert isinstance(supported, dict)
    supported["evidence_tools"] = []

    with pytest.raises(ValidationError, match="evidence tool"):
        StrategyCard.model_validate(card)


def test_unconfirmed_draft_is_not_persisted(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = _call(
        registry,
        "strategy_save",
        {
            "card": _card(),
            "user_confirmed": False,
            "confirmation_note": "",
        },
    )

    assert result["saved"] is False
    assert "尚未保存" in str(result["error"])
    listed = _call(registry, "strategy_list", {})
    assert listed["count"] == 0


def test_list_query_treats_like_wildcards_as_literals(tmp_path: Path) -> None:
    """搜索字面 % / _ 时不得当通配符误匹配所有卡片。"""
    registry = _registry(tmp_path)
    percent_card = _card()
    percent_card["title"] = "涨100%后的减仓观察"  # type: ignore[assignment]
    saved = _call(
        registry,
        "strategy_save",
        {
            "card": percent_card,
            "user_confirmed": True,
            "confirmation_note": "用户确认保存。",
        },
    )
    assert saved["saved"] is True
    assert _save(registry)["saved"] is True  # 第二张：标题不含 %

    literal_percent = _call(registry, "strategy_list", {"query": "%"})
    assert literal_percent["count"] == 1
    titles = [item["title"] for item in literal_percent["strategies"]]
    assert "涨100%后的减仓观察" in titles

    # 未转义时 "%" 构成的模式 "%%" 会匹配所有卡片；只命中 1 张说明 % 按字面量处理。
    # （"_" 不做此断言：card_json 的字段名本身含下划线，跨字段命中是预期行为。）
    normal = _call(registry, "strategy_list", {"query": "价格观察"})
    assert normal["count"] == 1


def test_save_reopen_and_duplicate_preserve_source_and_revision(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = _save(registry)
    duplicate = _save(registry)

    assert first["saved"] is True
    assert first["version"] == 1
    assert duplicate["reused"] is True
    assert duplicate["strategy_id"] == first["strategy_id"]

    reopened = _call(
        registry,
        "strategy_get",
        {"strategy_id": first["strategy_id"]},
    )
    card = reopened["card"]
    assert isinstance(card, dict)
    source = card["source"]
    assert isinstance(source, dict)
    assert source["reference"] == "conversation:strategy-example"
    revisions = reopened["revisions"]
    assert isinstance(revisions, list)
    assert revisions[0]["revision_note"] == "首次确认保存"
    assert revisions[0]["user_confirmed"] is True
    assert "confirmation_note" not in revisions[0]
    assert len(json.dumps(reopened, ensure_ascii=False).encode("utf-8")) < 8_192


def test_card_rejects_payload_too_large_for_reliable_agent_transport() -> None:
    card = _card(summary="长" * 4_000)
    source = card["source"]
    assert isinstance(source, dict)
    source["excerpts"] = ["摘录" * 500]

    with pytest.raises(ValidationError, match="策略卡过长"):
        StrategyCard.model_validate(card)


def test_confirmed_revision_is_versioned_and_conflicts_are_clear(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = _save(registry)
    changed = _card(summary="价格阈值只负责提醒，EMA 云带继续由用户看图确认。")

    revised = _call(
        registry,
        "strategy_save",
        {
            "card": changed,
            "strategy_id": first["strategy_id"],
            "expected_version": 1,
            "revision_note": "用户强调价格告警不等于形态判断。",
            "user_confirmed": True,
            "confirmation_note": "用户确认修改后的最终卡片并要求保存。",
        },
    )
    assert revised["version"] == 2

    stale = _call(
        registry,
        "strategy_save",
        {
            "card": _card(summary="另一个修改"),
            "strategy_id": first["strategy_id"],
            "expected_version": 1,
            "revision_note": "过期修改",
            "user_confirmed": True,
            "confirmation_note": "用户确认",
        },
    )
    assert stale["saved"] is False
    assert "v2" in str(stale["error"])

    reopened = _call(registry, "strategy_get", {"strategy_id": first["strategy_id"]})
    assert reopened["version"] == 2
    revisions = reopened["revisions"]
    assert isinstance(revisions, list)
    assert [item["revision_note"] for item in revisions] == [
        "首次确认保存",
        "用户强调价格告警不等于形态判断。",
    ]


def test_large_card_history_stays_valid_json_at_agent_boundary(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = _save(registry, _card(summary="长" * 800))
    version = 1
    for index in range(1, 6):
        result = _call(
            registry,
            "strategy_save",
            {
                "card": _card(summary="长" * 800 + str(index)),
                "strategy_id": first["strategy_id"],
                "expected_version": version,
                "revision_note": "修改" * 250,
                "user_confirmed": True,
                "confirmation_note": "用户确认修订。",
            },
        )
        version = int(result["version"])

    raw = registry.call("strategy_get", {"strategy_id": first["strategy_id"]})

    reopened = json.loads(raw)
    assert reopened["version"] == 6
    assert len(raw.encode("utf-8")) <= 7_500


def test_prepare_application_requests_current_evidence_without_claiming_a_result(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    saved = _save(registry)

    prepared = _call(
        registry,
        "strategy_prepare_application",
        {"strategy_id": saved["strategy_id"], "code": "600519", "days": 20},
    )

    assert prepared["evidence_request"] == {
        "tool": "research_stock",
        "arguments": {"code": "600519", "days": 20},
    }
    checklist = prepared["condition_checklist"]
    assert isinstance(checklist, list)
    assert [item["automation"] for item in checklist] == ["supported", "manual"]
    assert all(item["allowed_outcomes"] == ["满足", "不满足", "无法判断"] for item in checklist)
    assert "回测" not in json.dumps(prepared, ensure_ascii=False)


def test_manual_condition_cannot_be_disguised_as_monitor(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    saved = _save(registry)

    result = _call(
        registry,
        "strategy_prepare_monitor",
        {
            "strategy_id": saved["strategy_id"],
            "condition_id": "ema-suppression",
            "code": "600519",
        },
    )

    assert result["activated"] is False
    assert "人工检查" in str(result["error"])


def test_monitor_requires_second_consent_and_links_back_to_card(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    saved = _save(registry)
    args = {
        "strategy_id": saved["strategy_id"],
        "condition_id": "price-watch",
        "code": "600519",
        "name": "贵州茅台",
    }

    candidate = _call(registry, "strategy_prepare_monitor", args)
    assert candidate["activated"] is False
    assert candidate["requires_separate_confirmation"] is True
    assert candidate["rule"] == {"condition": "price_below", "threshold": "100"}
    assert "价格低于 100" in str(candidate["trigger_explanation"])

    refused = _call(
        registry,
        "strategy_activate_monitor",
        {**args, "user_confirmed": False, "confirmation_note": ""},
    )
    assert refused["activated"] is False
    assert CustomAlertStore(tmp_path / "portfolio.db").list_all() == []

    activated = _call(
        registry,
        "strategy_activate_monitor",
        {
            **args,
            "user_confirmed": True,
            "confirmation_note": "用户看过价格阈值候选后单独同意启用。",
        },
    )
    repeated = _call(
        registry,
        "strategy_activate_monitor",
        {
            **args,
            "user_confirmed": True,
            "confirmation_note": "用户重试同一操作。",
        },
    )
    assert activated["activated"] is True
    assert activated["reused"] is False
    assert repeated["reused"] is True
    assert repeated["alert_id"] == activated["alert_id"]
    assert len(CustomAlertStore(tmp_path / "portfolio.db").list_all()) == 1

    reopened = _call(registry, "strategy_get", {"strategy_id": saved["strategy_id"]})
    monitors = reopened["monitors"]
    assert isinstance(monitors, list)
    assert monitors[0]["active"] is True
    assert monitors[0]["condition_id"] == "price-watch"


def test_archive_is_explicit_and_does_not_silently_delete_monitor(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    saved = _save(registry)
    monitor_args = {
        "strategy_id": saved["strategy_id"],
        "condition_id": "price-watch",
        "code": "600519",
        "user_confirmed": True,
        "confirmation_note": "用户单独同意启用。",
    }
    _call(registry, "strategy_activate_monitor", monitor_args)

    not_confirmed = _call(
        registry,
        "strategy_archive",
        {
            "strategy_id": saved["strategy_id"],
            "user_confirmed": False,
            "confirmation_note": "",
        },
    )
    assert not_confirmed["archived"] is False

    archived = _call(
        registry,
        "strategy_archive",
        {
            "strategy_id": saved["strategy_id"],
            "user_confirmed": True,
            "confirmation_note": "用户明确要求归档策略卡。",
        },
    )
    assert archived["archived"] is True
    assert "不会被静默删除" in str(archived["message"])
    assert len(CustomAlertStore(tmp_path / "portfolio.db").list_all()) == 1

    cannot_apply = _call(
        registry,
        "strategy_prepare_application",
        {"strategy_id": saved["strategy_id"], "code": "600519"},
    )
    assert "已归档" in str(cannot_apply["error"])


def test_unchanged_monitor_rule_is_reused_after_strategy_revision(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    saved = _save(registry)
    monitor_args = {
        "strategy_id": saved["strategy_id"],
        "condition_id": "price-watch",
        "code": "600519",
        "user_confirmed": True,
        "confirmation_note": "用户单独同意启用。",
    }
    first_monitor = _call(registry, "strategy_activate_monitor", monitor_args)

    revised = _call(
        registry,
        "strategy_save",
        {
            "card": _card(summary="只修改摘要，不改变价格监控规则。"),
            "strategy_id": saved["strategy_id"],
            "expected_version": 1,
            "revision_note": "用户只修改了摘要。",
            "user_confirmed": True,
            "confirmation_note": "用户确认修改后的卡片并要求保存。",
        },
    )
    assert revised["version"] == 2

    second_monitor = _call(
        registry,
        "strategy_activate_monitor",
        {**monitor_args, "confirmation_note": "用户确认继续使用同一价格提醒。"},
    )

    assert second_monitor["reused"] is True
    assert second_monitor["alert_id"] == first_monitor["alert_id"]
    assert len(CustomAlertStore(tmp_path / "portfolio.db").list_all()) == 1
    reopened = _call(registry, "strategy_get", {"strategy_id": saved["strategy_id"]})
    monitors = reopened["monitors"]
    assert isinstance(monitors, list)
    assert {item["strategy_version"] for item in monitors} == {1, 2}
