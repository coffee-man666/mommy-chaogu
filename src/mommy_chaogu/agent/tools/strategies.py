"""Strategy Distillation tools: approved cards, reuse, and consent-gated monitors."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json
from mommy_chaogu.codes import STOCK_CODE_RE as _CODE_RE
from mommy_chaogu.strategy.models import AutomationStatus, StrategyCard
from mommy_chaogu.strategy.store import (
    StrategyConflictError,
    StrategyStore,
    StrategyStoreError,
)

_CARD_SCHEMA = StrategyCard.model_json_schema()
# Pydantic emits references such as ``#/$defs/StrategySource``. The card
# schema is nested under the tool's ``card`` property, so its definitions must
# be lifted to the tool-schema root or those references are invalid.
_CARD_DEFS = _CARD_SCHEMA.pop("$defs", {})
_MAX_STRATEGY_RESPONSE_BYTES = 7_500


DEFS: list[ToolDef] = [
    ToolDef(
        name="strategy_save",
        description=(
            "PERSONAL 写操作：仅在用户看过最终人类可读策略卡并明确要求保存后，"
            "校验并保存策略卡；也可保存用户再次确认的修订版本。未确认的草稿禁止调用。"
        ),
        parameters={
            "type": "object",
            "$defs": _CARD_DEFS,
            "properties": {
                "card": _CARD_SCHEMA,
                "user_confirmed": {
                    "type": "boolean",
                    "description": "只有用户明确说保存/确认保存后才能为 true",
                },
                "confirmation_note": {
                    "type": "string",
                    "description": "简要记录用户如何确认，例如‘用户看过最终卡片并要求保存’",
                },
                "strategy_id": {
                    "type": "string",
                    "description": "修改既有策略时填写；新建时省略",
                },
                "expected_version": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "修改既有策略时填写当前版本，防止覆盖更新",
                },
                "revision_note": {
                    "type": "string",
                    "description": "修改既有策略时，用用户语言说明改了什么",
                },
            },
            "required": ["card", "user_confirmed", "confirmation_note"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="strategy_list",
        description="PERSONAL 读操作：列出本机已确认保存的策略卡摘要。",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "archived", "all"],
                    "default": "active",
                },
                "query": {"type": "string", "description": "可选标题或内容关键词"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5, "default": 5},
            },
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="strategy_get",
        description=(
            "PERSONAL 读操作：重新打开一张策略卡，返回来源、当前版本、修订说明和已关联监控。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
            },
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="strategy_archive",
        description=("PERSONAL 写操作：在用户明确确认后归档策略卡。不会静默删除已经创建的监控。"),
        parameters={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
                "confirmation_note": {"type": "string"},
            },
            "required": ["strategy_id", "user_confirmed", "confirmation_note"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="strategy_prepare_application",
        description=(
            "PERSONAL 读操作：准备‘按这套方法看某只股票今天’的证据请求和逐条件检查表。"
            "本工具不声称策略有效，也不代替宿主 Agent 调用 research_stock 和解释证据。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}(?:[.-][A-Z])?|\\d{6})$",
                    "description": "要应用策略的 A 股或美股代码",
                },
                "days": {"type": "integer", "minimum": 5, "maximum": 60, "default": 20},
            },
            "required": ["strategy_id", "code"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="strategy_prepare_monitor",
        description=(
            "PERSONAL 读操作：把策略卡中现有告警系统确实支持的一项规则准备成监控候选。"
            "只展示候选，不启用；必须让用户另行确认后才能调用 strategy_activate_monitor。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "condition_id": {"type": "string"},
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}(?:[.-][A-Z])?|\\d{6})$",
                },
                "name": {
                    "type": "string",
                    "maxLength": 100,
                    "description": "股票名称，可选",
                },
            },
            "required": ["strategy_id", "condition_id", "code"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="strategy_activate_monitor",
        description=(
            "PERSONAL 写操作：仅在展示过监控候选且用户第二次明确同意后启用该监控，"
            "并记录它关联的策略卡、版本和来源。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "condition_id": {"type": "string"},
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}(?:[.-][A-Z])?|\\d{6})$",
                },
                "name": {
                    "type": "string",
                    "maxLength": 100,
                    "description": "股票名称，可选",
                },
                "user_confirmed": {
                    "type": "boolean",
                    "description": "只有用户看过候选并明确同意启用后才能为 true",
                },
                "confirmation_note": {
                    "type": "string",
                    "description": "简要记录这次独立的监控授权",
                },
            },
            "required": [
                "strategy_id",
                "condition_id",
                "code",
                "user_confirmed",
                "confirmation_note",
            ],
            "additionalProperties": False,
        },
    ),
]


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors(include_url=False)
    if not errors:
        return "策略卡格式无效"
    first = errors[0]
    location = ".".join(str(item) for item in first.get("loc", ()))
    detail = str(first.get("msg", "格式无效"))
    return f"策略卡字段 {location or 'card'}：{detail}"


def _agent_db(ctx: ToolContext) -> Any:
    db_path = ctx.resolved_agent_db
    if db_path is None:
        raise ValueError("agent_db 未配置，无法保存或读取策略卡")
    return db_path


def _clean_code(raw: Any) -> str:
    code = str(raw or "").strip().upper()
    if not _CODE_RE.fullmatch(code):
        raise ValueError("股票代码格式无效")
    return code


def _load_active(store: StrategyStore, strategy_id: str) -> tuple[dict[str, Any], StrategyCard]:
    record = store.get(strategy_id)
    if record["status"] != "active":
        raise StrategyConflictError("这张策略卡已归档，不能用于新的研究或监控")
    return record, StrategyCard.model_validate(record["card"])


def _with_store(ctx: ToolContext) -> StrategyStore:
    return StrategyStore(_agent_db(ctx))


def _source_receipt(card: StrategyCard) -> dict[str, Any]:
    """Return enough provenance for a workflow without repeating excerpts."""
    source = card.source
    return {
        "type": source.type.value,
        "title": source.title,
        "reference": source.reference,
        "content_hash": source.content_hash,
        "hash_scope": source.hash_scope.value if source.hash_scope else None,
        "excerpt_count": len(source.excerpts),
    }


def _bounded_record_json(record: dict[str, Any]) -> str:
    """Keep strategy_get valid JSON under the registry's 8 KiB limit.

    The current approved card is never clipped. Older audit summaries are
    progressively omitted and explicitly marked truncated when a large card
    would otherwise be cut into invalid JSON by the shared tool boundary.
    """
    revisions = record.get("revisions")
    if isinstance(revisions, list):
        for item in revisions:
            if isinstance(item, dict) and isinstance(item.get("revision_note"), str):
                note = item["revision_note"]
                if len(note) > 160:
                    item["revision_note"] = note[:159] + "…"
                    item["note_truncated"] = True
    monitors = record.get("monitors")
    if not isinstance(monitors, list):
        monitors = []

    def encoded() -> str:
        return _json(record)

    payload = encoded()
    while len(payload.encode("utf-8")) > _MAX_STRATEGY_RESPONSE_BYTES:
        if isinstance(revisions, list) and len(revisions) > 1:
            revisions.pop(0)
            record["revision_history_truncated"] = True
        elif len(monitors) > 1:
            monitors.pop(0)
            record["monitor_history_truncated"] = True
        elif monitors:
            monitors.clear()
            record["monitor_history_truncated"] = True
        elif isinstance(revisions, list) and revisions:
            revisions.clear()
            record["revision_history_truncated"] = True
        else:
            break
        payload = encoded()
    return payload


def _handle_save(ctx: ToolContext, args: dict[str, Any]) -> str:
    if args.get("user_confirmed") is not True:
        return _json(
            {
                "error": "尚未保存：请先把最终策略卡展示给用户，并取得明确的保存确认。",
                "saved": False,
            }
        )
    try:
        card = StrategyCard.model_validate(args.get("card"))
        with _with_store(ctx) as store:
            return _json(
                store.save(
                    card,
                    confirmation_note=str(args.get("confirmation_note", "")),
                    strategy_id=(str(args["strategy_id"]) if args.get("strategy_id") else None),
                    expected_version=(
                        int(args["expected_version"])
                        if args.get("expected_version") is not None
                        else None
                    ),
                    revision_note=(
                        str(args["revision_note"])
                        if args.get("revision_note") is not None
                        else None
                    ),
                )
            )
    except ValidationError as exc:
        return _json({"error": _validation_message(exc), "saved": False})
    except (StrategyStoreError, TypeError, ValueError) as exc:
        return _json({"error": str(exc), "saved": False})


def _handle_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        with _with_store(ctx) as store:
            cards = store.list(
                status=str(args.get("status", "active")),
                query=str(args["query"]) if args.get("query") else None,
                limit=int(args.get("limit", 5)),
            )
        return _json({"strategies": cards, "count": len(cards)})
    except (StrategyStoreError, TypeError, ValueError) as exc:
        return _json({"error": str(exc)})


def _active_alert_ids(ctx: ToolContext) -> set[int] | None:
    db_path = ctx.resolved_portfolio_db
    if db_path is None:
        return None
    from mommy_chaogu.signals.custom_alerts import CustomAlertStore

    with CustomAlertStore(db_path) as alerts:
        return {item.id for item in alerts.list_all() if item.id is not None and item.enabled}


def _handle_get(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        with _with_store(ctx) as store:
            record = store.get(str(args.get("strategy_id", "")))
        active_ids = _active_alert_ids(ctx)
        for monitor in record["monitors"]:
            monitor["active"] = (
                None if active_ids is None else int(monitor["alert_id"]) in active_ids
            )
        record["message"] = (
            f"已打开《{record['card']['title']}》v{record['version']}；"
            "来源、能力边界和修订记录如下。"
        )
        return _bounded_record_json(record)
    except (StrategyStoreError, TypeError, ValueError) as exc:
        return _json({"error": str(exc)})


def _handle_archive(ctx: ToolContext, args: dict[str, Any]) -> str:
    if args.get("user_confirmed") is not True:
        return _json({"error": "尚未归档：需要用户明确确认。", "archived": False})
    if not str(args.get("confirmation_note", "")).strip():
        return _json({"error": "归档需要记录用户确认。", "archived": False})
    try:
        with _with_store(ctx) as store:
            result = store.archive(str(args.get("strategy_id", "")))
        return _json(result)
    except (StrategyStoreError, TypeError, ValueError) as exc:
        return _json({"error": str(exc), "archived": False})


def _handle_prepare_application(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        code = _clean_code(args.get("code"))
        days = max(5, min(int(args.get("days", 20)), 60))
        with _with_store(ctx) as store:
            record, card = _load_active(store, str(args.get("strategy_id", "")))
        checklist = [
            {
                "condition_id": item.id,
                "category": item.category.value,
                "statement": item.statement,
                "automation": item.automation.value,
                "reason": item.reason,
                "evidence_tools": item.evidence_tools,
                "allowed_outcomes": ["满足", "不满足", "无法判断"],
            }
            for item in card.conditions
        ]
        return _json(
            {
                "strategy_id": record["strategy_id"],
                "strategy_version": record["version"],
                "strategy_title": card.title,
                "source": _source_receipt(card),
                "subject": {"type": "stock", "code": code},
                "evidence_request": {
                    "tool": "research_stock",
                    "arguments": {"code": code, "days": days},
                },
                "condition_checklist": checklist,
                "instructions": [
                    "先调用 evidence_request 指定的研究工具，不能把本响应当作行情证据。",
                    "只依据带时间戳的当前证据逐项回答满足、不满足或无法判断。",
                    "manual/unavailable 条件不得猜测；说明用户可以怎样人工确认或当前缺什么。",
                    "结论是按用户方法整理的当前观察，不是收益承诺或自动交易建议。",
                ],
            }
        )
    except (StrategyStoreError, TypeError, ValueError, ValidationError) as exc:
        return _json({"error": str(exc)})


def _monitor_candidate(
    store: StrategyStore,
    *,
    strategy_id: str,
    condition_id: str,
    code: str,
    name: str | None,
) -> tuple[dict[str, Any], StrategyCard, Any, dict[str, Any]]:
    record, card = _load_active(store, strategy_id)
    condition = card.condition(condition_id)
    if condition is None:
        raise ValueError(f"策略卡中没有条件 {condition_id}")
    if condition.automation != AutomationStatus.SUPPORTED or condition.monitor_rule is None:
        raise ValueError(
            "这项条件当前不能自动监控；请保留为人工检查，不要改写成其他方便实现的规则。"
        )
    rule = condition.monitor_rule
    display_name = (name or code).strip() or code
    if len(display_name) > 100:
        raise ValueError("股票名称不能超过 100 个字符")
    alert_name = f"{display_name} · {card.title}"[:64]
    phrases = {
        "price_above": "价格高于",
        "price_below": "价格低于",
        "change_pct_above": "涨跌幅高于",
        "change_pct_below": "涨跌幅低于",
    }
    candidate = {
        "strategy_id": strategy_id,
        "strategy_version": record["version"],
        "strategy_title": card.title,
        "source": _source_receipt(card),
        "condition_id": condition.id,
        "condition_statement": condition.statement,
        "code": code,
        "name": display_name,
        "alert_name": alert_name,
        "rule": {
            "condition": rule.condition.value,
            "threshold": str(rule.threshold),
        },
        "trigger_explanation": (
            f"当 {display_name} {phrases[rule.condition.value]} {rule.threshold} 时提醒；"
            f"它对应策略条件：{condition.statement}"
        ),
    }
    return record, card, condition, candidate


def _handle_prepare_monitor(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        code = _clean_code(args.get("code"))
        strategy_id = str(args.get("strategy_id", ""))
        condition_id = str(args.get("condition_id", ""))
        with _with_store(ctx) as store:
            _, _, _, candidate = _monitor_candidate(
                store,
                strategy_id=strategy_id,
                condition_id=condition_id,
                code=code,
                name=str(args["name"]) if args.get("name") else None,
            )
        candidate.update(
            {
                "activated": False,
                "requires_separate_confirmation": True,
                "next_step": (
                    "先把触发条件、阈值、数据依赖和原因展示给用户。只有用户明确同意启用后，"
                    "才调用 strategy_activate_monitor。"
                ),
            }
        )
        return _json(candidate)
    except (StrategyStoreError, TypeError, ValueError, ValidationError) as exc:
        return _json({"error": str(exc), "activated": False})


def _handle_activate_monitor(ctx: ToolContext, args: dict[str, Any]) -> str:
    if args.get("user_confirmed") is not True:
        return _json(
            {
                "error": "尚未启用：保存策略卡的确认不等于启用监控；需要用户对候选单独确认。",
                "activated": False,
            }
        )
    confirmation = str(args.get("confirmation_note", "")).strip()
    if not confirmation:
        return _json({"error": "启用监控需要记录这次独立确认。", "activated": False})
    portfolio_db = ctx.resolved_portfolio_db
    if portfolio_db is None:
        return _json({"error": "portfolio_db 未配置，无法启用监控", "activated": False})

    from mommy_chaogu.signals.custom_alerts import CustomAlertStore

    try:
        code = _clean_code(args.get("code"))
        strategy_id = str(args.get("strategy_id", ""))
        condition_id = str(args.get("condition_id", ""))
        with _with_store(ctx) as store:
            record, card, condition, candidate = _monitor_candidate(
                store,
                strategy_id=strategy_id,
                condition_id=condition_id,
                code=code,
                name=str(args["name"]) if args.get("name") else None,
            )
            rule = condition.monitor_rule
            assert rule is not None
            existing = store.monitor_link(
                strategy_id=strategy_id,
                strategy_version=int(record["version"]),
                condition_id=condition_id,
                code=code,
                rule_condition=rule.condition.value,
                threshold=rule.threshold,
            )

            with CustomAlertStore(portfolio_db) as alerts:
                active_ids = {item.id for item in alerts.list_all() if item.enabled}
                if existing is not None and int(existing["alert_id"]) in active_ids:
                    if int(existing["strategy_version"]) != int(record["version"]):
                        store.record_monitor(
                            strategy_id=strategy_id,
                            strategy_version=int(record["version"]),
                            condition_id=condition_id,
                            code=code,
                            alert_id=int(existing["alert_id"]),
                            alert_name=str(existing["alert_name"]),
                            rule_condition=rule.condition.value,
                            threshold=rule.threshold,
                            confirmation_note=confirmation,
                        )
                    return _json(
                        {
                            **candidate,
                            "activated": True,
                            "reused": True,
                            "alert_id": int(existing["alert_id"]),
                            "message": "这项策略监控已经启用，没有创建重复告警。",
                        }
                    )
                alert = alerts.add(
                    code=code,
                    name=str(candidate["alert_name"]),
                    condition=rule.condition.value,
                    threshold=Decimal(rule.threshold),
                )
                assert alert.id is not None
                try:
                    store.record_monitor(
                        strategy_id=strategy_id,
                        strategy_version=int(record["version"]),
                        condition_id=condition_id,
                        code=code,
                        alert_id=alert.id,
                        alert_name=alert.name,
                        rule_condition=rule.condition.value,
                        threshold=rule.threshold,
                        confirmation_note=confirmation,
                    )
                except Exception:
                    alerts.remove(alert.id)
                    raise

        return _json(
            {
                **candidate,
                "activated": True,
                "reused": False,
                "alert_id": alert.id,
                "message": (
                    f"已启用监控，并关联到《{card.title}》v{record['version']}；"
                    "可用 manage_alert list 查看、用 manage_alert remove 关闭。"
                ),
            }
        )
    except (StrategyStoreError, TypeError, ValueError, ValidationError) as exc:
        return _json({"error": str(exc), "activated": False})


HANDLERS: dict[str, ToolHandler] = {
    "strategy_save": _handle_save,
    "strategy_list": _handle_list,
    "strategy_get": _handle_get,
    "strategy_archive": _handle_archive,
    "strategy_prepare_application": _handle_prepare_application,
    "strategy_prepare_monitor": _handle_prepare_monitor,
    "strategy_activate_monitor": _handle_activate_monitor,
}
