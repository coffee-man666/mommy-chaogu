"""主题工具：主题/产业链列表、主题成分股行情。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _json

DEFS: list[ToolDef] = [
    ToolDef(
        name="list_themes",
        description=(
            "列出所有可用的主题/产业链观察列表（半导体、创新药、机器人、材料、中报等）。"
            "返回每个主题的 ID、名称、股票数量、子板块。"
            "当用户提到'半导体供应链'、'创新药'、'机器人'等产业链时，先用此工具获取主题列表。"
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="get_theme_stocks",
        description=(
            "获取某个主题/产业链的成分股列表 + 实时行情。"
            "参数 theme_id 从 list_themes 获取（如 semiconductor/innovative_drug/humanoid_robot/earnings_watch）。"
            "返回每只股票的代码、名称、报价、涨跌幅、主力净流入、子板块分类等。"
            "当用户想看某个产业链的股票时用此工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "theme_id": {
                    "type": "string",
                    "description": "主题 ID（如 semiconductor, innovative_drug, humanoid_robot, materials, earnings_watch）",
                },
            },
            "required": ["theme_id"],
        },
    ),
]


def _handle_list_themes(_ctx: ToolContext, _args: dict[str, Any]) -> str:
    """列出所有主题/产业链。"""
    from mommy_chaogu.services.theme_service import ThemeService

    svc = ThemeService()
    # 工具层面向 LLM，description 截断到 120 字以节省 token。
    themes = [
        {
            "id": t["id"],
            "name": t["name"],
            "total_stocks": t["total_stocks"],
            "subcategories": t["subcategories"],
            "description": t["description"][:120],
        }
        for t in svc.list_themes()
    ]
    return _json(themes)


def _handle_get_theme_stocks(ctx: ToolContext, args: dict[str, Any]) -> str:
    """获取主题成分股 + 实时行情。"""
    from mommy_chaogu.services.theme_service import ThemeService

    theme_id = args.get("theme_id", "")
    if not theme_id:
        return _json({"error": "缺少 theme_id 参数"})

    svc = ThemeService(adapter=ctx.adapter)
    items = svc.get_theme_quotes(theme_id)

    if not items:
        return _json({"error": f"主题不存在或无数据: {theme_id}"})

    # 工具层面向 LLM：行情用 float，只保留关键字段。
    results: list[dict[str, Any]] = []
    for it in items:
        item: dict[str, Any] = {
            "code": it["code"],
            "name": it["name"],
            "subcategory": it["subcategory"],
            "level": it["level"],
            "role": it["role"],
        }
        if it.get("growth_text"):
            item["growth_text"] = it["growth_text"]
            item["core_driver"] = it.get("core_driver", "")
        if it["price"] is not None:
            item["price"] = float(it["price"])
            item["change_pct"] = float(it["change_pct"])
            item["volume"] = it["volume"]
            item["pe"] = float(it["pe"]) if it["pe"] else None
            item["main_net_inflow"] = (
                float(it["main_net_inflow"]) if it["main_net_inflow"] else None
            )
        results.append(item)

    return _json(results)


HANDLERS: dict[str, ToolHandler] = {
    "list_themes": _handle_list_themes,
    "get_theme_stocks": _handle_get_theme_stocks,
}
