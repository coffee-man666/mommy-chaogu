"""/api/themes 路由：主题/产业链观察列表。

数据来源：
- data/supply_chains/*.json — 供应链 JSON（半导体/创新药/机器人/材料）
- data/earnings_preview.json — 中报观察列表
- data/reference.db semicon_stocks — 半导体详细数据

端点：
- GET /api/themes                — 所有主题列表
- GET /api/themes/{theme_id}     — 单个主题详情（含成分股）
- GET /api/themes/{theme_id}/quotes — 主题成分股实时行情
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/themes", tags=["themes"])

_DATA_DIR = Path("data/supply_chains")
_EARNINGS_FILE = Path("data/earnings_preview.json")


def _load_json(path: Path) -> dict[str, Any]:
    """安全加载 JSON 文件。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _log.warning("theme file not found: %s", path)
        return {}
    except Exception as e:
        _log.warning("failed to load %s: %s", path, e)
        return {}


def _load_all_themes() -> dict[str, dict[str, Any]]:
    """加载所有主题数据。"""
    themes: dict[str, dict[str, Any]] = {}

    # supply_chains/*.json
    if _DATA_DIR.exists():
        for f in sorted(_DATA_DIR.glob("*.json")):
            data = _load_json(f)
            if not data:
                continue
            meta = data.get("meta", {})
            theme_id = meta.get("id", f.stem)
            stocks = data.get("stocks", [])
            themes[theme_id] = {
                "id": theme_id,
                "name": meta.get("name", f.stem),
                "description": meta.get("description", ""),
                "subcategories": meta.get("subcategories", []),
                "chain_positions": meta.get("chain_positions", []),
                "total_stocks": len(stocks),
                "stocks": stocks,
                "source": "supply_chain",
            }

    # earnings_preview.json → 中报观察
    if _EARNINGS_FILE.exists():
        data = _load_json(_EARNINGS_FILE)
        stocks = data.get("stocks", [])
        if stocks:
            themes["earnings_watch"] = {
                "id": "earnings_watch",
                "name": "中报观察",
                "description": data.get("meta", {}).get(
                    "description", "2026 H1 中报高增长观察列表"
                ),
                "subcategories": sorted(
                    {s.get("sector", "") for s in stocks if s.get("sector")}
                ),
                "chain_positions": [],
                "total_stocks": len(stocks),
                "stocks": stocks,
                "source": "earnings_preview",
            }

    return themes


@router.get("")
async def list_themes() -> dict[str, Any]:
    """所有主题列表（不含成分股详情）。"""
    themes = _load_all_themes()
    items = [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "total_stocks": t["total_stocks"],
            "subcategories": t["subcategories"],
            "source": t["source"],
        }
        for t in themes.values()
    ]
    return {"items": items, "total": len(items)}


@router.get("/{theme_id}")
async def get_theme(theme_id: str) -> dict[str, Any]:
    """单个主题详情（含成分股）。"""
    themes = _load_all_themes()
    if theme_id not in themes:
        raise HTTPException(status_code=404, detail=f"主题不存在: {theme_id}")
    return themes[theme_id]


@router.get("/{theme_id}/quotes")
async def get_theme_quotes(
    theme_id: str,
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    """主题成分股实时行情。

    从主题定义取出 codes，批量调行情接口。
    """
    from mommy_chaogu.web.deps import get_adapter

    themes = _load_all_themes()
    if theme_id not in themes:
        raise HTTPException(status_code=404, detail=f"主题不存在: {theme_id}")

    theme = themes[theme_id]
    stocks = theme["stocks"]
    codes = [s.get("code", "") for s in stocks][:limit]
    codes = [c for c in codes if c]

    if not codes:
        return {"items": [], "total": 0}

    adapter = get_adapter()
    results: list[dict[str, Any]] = []

    for stock in stocks[:limit]:
        code = stock.get("code", "")
        if not code:
            continue
        try:
            q = adapter.get_quote(code)
            if q:
                results.append(
                    {
                        "code": code,
                        "name": stock.get("name", q.name),
                        "price": str(q.price),
                        "change_pct": str(q.change_pct),
                        "volume": q.volume,
                        "turnover_rate": str(q.turnover_rate)
                        if q.turnover_rate
                        else None,
                        "pe": str(q.pe) if q.pe else None,
                        "main_net_inflow": str(q.main_net_inflow)
                        if q.main_net_inflow
                        else None,
                        "subcategory": stock.get("subcategory", stock.get("sector", "")),
                        "level": stock.get("level", stock.get("chain_position", "")),
                        "role": stock.get("role", ""),
                        # 业绩数据（earnings_watch 主题特有）
                        "growth_text": stock.get("growth_text", ""),
                        "growth_low": stock.get("growth_low"),
                        "growth_high": stock.get("growth_high"),
                        "core_driver": stock.get("core_driver", ""),
                        "highlight": stock.get("highlight", ""),
                    }
                )
        except Exception as e:
            _log.debug("quote failed for %s: %s", code, e)
            results.append(
                {
                    "code": code,
                    "name": stock.get("name", ""),
                    "price": "",
                    "change_pct": "",
                    "subcategory": stock.get("subcategory", stock.get("sector", "")),
                    "level": stock.get("level", ""),
                    "error": str(e),
                }
            )

    return {"theme_id": theme_id, "theme_name": theme["name"], "items": results, "total": len(results)}
