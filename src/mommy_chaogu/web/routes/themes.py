"""/api/themes 路由：主题/产业链观察列表。

数据来源（由 ThemeService 统一加载）：
- data/supply_chains/*.json — 供应链 JSON（半导体/创新药/机器人/材料）
- data/earnings_preview.json — 中报观察列表

端点：
- GET /api/themes                — 所有主题列表
- GET /api/themes/{theme_id}     — 单个主题详情（含成分股）
- GET /api/themes/{theme_id}/quotes — 主题成分股实时行情
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from mommy_chaogu.services.theme_service import ThemeService

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/themes", tags=["themes"])


@router.get("")
async def list_themes() -> dict[str, Any]:
    """所有主题列表（不含成分股详情）。"""
    svc = ThemeService()
    items = svc.list_themes()
    return {"items": items, "total": len(items)}


@router.get("/{theme_id}")
async def get_theme(theme_id: str) -> dict[str, Any]:
    """单个主题详情（含成分股）。"""
    svc = ThemeService()
    theme = svc.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail=f"主题不存在: {theme_id}")
    return theme


@router.get("/{theme_id}/quotes")
async def get_theme_quotes(
    theme_id: str,
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    """主题成分股实时行情。

    从主题定义取出 codes，批量调行情接口。
    """
    from mommy_chaogu.web.deps import get_adapter

    svc = ThemeService(adapter=get_adapter())
    theme = svc.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail=f"主题不存在: {theme_id}")

    items = svc.get_theme_quotes(theme_id, limit=limit)

    # API 层面向前端：行情用 str（保留 Decimal 精度），区分成功/失败两种 item 格式。
    results: list[dict[str, Any]] = []
    for it in items:
        if it["error"] is not None:
            # 行情拉取失败：精简错误 item
            results.append(
                {
                    "code": it["code"],
                    "name": it["name"],
                    "price": "",
                    "change_pct": "",
                    "subcategory": it["subcategory"],
                    "level": it["level"],
                    "error": it["error"],
                }
            )
        elif it["price"] is None:
            # adapter 返回空行情：跳过（与原实现一致）
            continue
        else:
            results.append(
                {
                    "code": it["code"],
                    "name": it["name"],
                    "price": str(it["price"]),
                    "change_pct": str(it["change_pct"]),
                    "volume": it["volume"],
                    "turnover_rate": str(it["turnover_rate"]) if it["turnover_rate"] else None,
                    "pe": str(it["pe"]) if it["pe"] else None,
                    "main_net_inflow": str(it["main_net_inflow"])
                    if it["main_net_inflow"]
                    else None,
                    "subcategory": it["subcategory"],
                    "level": it["level"],
                    "role": it["role"],
                    # 业绩数据（earnings_watch 主题特有）
                    "growth_text": it["growth_text"],
                    "growth_low": it["growth_low"],
                    "growth_high": it["growth_high"],
                    "core_driver": it["core_driver"],
                    "highlight": it["highlight"],
                }
            )

    return {
        "theme_id": theme_id,
        "theme_name": theme["name"],
        "items": results,
        "total": len(results),
    }
