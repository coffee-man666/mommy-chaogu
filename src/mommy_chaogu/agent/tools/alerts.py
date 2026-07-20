"""告警工具：自定义价格/涨跌幅告警的增删查。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json

DEFS: list[ToolDef] = [
    ToolDef(
        name="manage_alert",
        description="设置或查看自定义价格告警（如'600519跌破1600提醒'）。",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "操作类型：add 添加 / list 列出 / remove 删除",
                },
                "code": {
                    "type": "string",
                    "description": "股票代码（action=list 时可选）",
                },
                "condition": {
                    "type": "string",
                    "enum": [
                        "price_above",
                        "price_below",
                        "change_pct_above",
                        "change_pct_below",
                    ],
                    "description": "触发条件（add 时必填）",
                },
                "threshold": {
                    "type": "number",
                    "description": "阈值（add 时必填，price_above/below 为价格，change_pct_* 为百分比）",
                },
                "name": {
                    "type": "string",
                    "description": "股票名称（add 时可选，默认用 code）",
                },
                "alert_id": {
                    "type": "integer",
                    "description": "告警 ID（remove 时必填）",
                },
            },
            "required": ["action"],
        },
    ),
]


def _handle_manage_alert(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.db_path is None:
        return _json({"error": "db_path 未配置，无法管理告警"})

    from mommy_chaogu.signals.custom_alerts import (
        CustomAlertNotFoundError,
        CustomAlertStore,
        InvalidConditionError,
    )

    store = CustomAlertStore(ctx.db_path)
    action = args["action"]

    if action == "add":
        code = args.get("code")
        if not code:
            return _json({"error": "action=add 需要 code 参数"})
        condition = args.get("condition")
        if not condition:
            return _json({"error": "action=add 需要 condition 参数"})
        threshold_raw = args.get("threshold")
        if threshold_raw is None:
            return _json({"error": "action=add 需要 threshold 参数"})
        name = args.get("name") or code
        threshold = Decimal(str(threshold_raw))
        try:
            alert = store.add(code, name, condition, threshold)
        except InvalidConditionError as e:
            return _json({"error": str(e)})
        return _json(
            {
                "id": alert.id,
                "code": alert.code,
                "name": alert.name,
                "condition": alert.condition,
                "threshold": float(alert.threshold),
                "enabled": alert.enabled,
                "message": f"已设置告警：{name} {condition} {threshold}",
            }
        )

    elif action == "list":
        code = args.get("code")
        alerts = store.list_for_code(code) if code else store.list_all()
        return _json(
            {
                "alerts": [
                    {
                        "id": a.id,
                        "code": a.code,
                        "name": a.name,
                        "condition": a.condition,
                        "threshold": float(a.threshold),
                        "enabled": a.enabled,
                    }
                    for a in alerts
                ],
                "count": len(alerts),
            }
        )

    elif action == "remove":
        alert_id = args.get("alert_id")
        if alert_id is None:
            return _json({"error": "action=remove 需要 alert_id 参数"})
        try:
            store.remove(int(alert_id))
        except CustomAlertNotFoundError as e:
            return _json({"error": str(e)})
        return _json({"message": f"已删除告警 id={alert_id}"})

    return _json({"error": f"未知 action: {action!r}"})


HANDLERS: dict[str, ToolHandler] = {
    "manage_alert": _handle_manage_alert,
}
