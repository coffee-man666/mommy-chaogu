"""/api/earnings 路由：业绩数据。

端点：
- GET /api/earnings/calendar       — 财报日历
- GET /api/earnings/stock/{code}   — 个股业绩（实际值）
- GET /api/earnings/scores/{code}  — 个股业绩评分
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Query

from mommy_chaogu.db_paths import REFERENCE_DB
from mommy_chaogu.earnings.store import EarningsStore

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/earnings", tags=["earnings"])


@lru_cache(maxsize=1)
def _store() -> EarningsStore:
    return EarningsStore(REFERENCE_DB)


@router.get("/calendar")
async def get_calendar(
    since: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    days_ahead: int | None = Query(None, description="未来 N 天内"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """财报日历。"""
    store = _store()
    try:
        cal = store.list_calendars(
            since_date=since,
            days_ahead=days_ahead,
        )
        items = [
            {
                "code": c.code,
                "name": c.name,
                "period": c.period,
                "disclosure_date": c.disclosure_date.isoformat(),
                "is_estimated": c.is_estimated,
                "source": c.source,
            }
            for c in cal[:limit]
        ]
        return {"items": items, "total": len(items)}
    except Exception as e:
        _log.warning("get_calendar failed: %s", e)
        return {"items": [], "total": 0}


@router.get("/stock/{code}")
async def get_stock_earnings(
    code: str,
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """个股业绩实际值。"""
    store = _store()
    try:
        actuals = store.list_actuals()
        items = [
            {
                "code": a.code,
                "name": a.name,
                "period": a.period,
                # EarningsActual 真实字段：disclosure_date（披露日期）、
                # actual_value（净利润）、growth_pct（同比增速）。
                # 此前路由读 report_date/revenue/eps 等不存在字段，
                # AttributeError 被 except 吞掉导致该端点恒返回空。
                "report_date": a.disclosure_date.isoformat(),
                "net_profit": str(a.actual_value),
                "net_profit_yoy": str(a.growth_pct) if a.growth_pct is not None else None,
                "source": a.source.value,
                "note": a.note,
            }
            for a in actuals
            if a.code == code
        ][:limit]
        return {"items": items, "total": len(items)}
    except Exception as e:
        _log.warning("get_stock_earnings failed: %s", e)
        return {"items": [], "total": 0}


@router.get("/scores/{code}")
async def get_stock_scores(code: str) -> dict[str, Any]:
    """个股业绩评分（actual vs 前瞻的比对结果）。"""
    store = _store()
    try:
        scores = store.list_scores()
        items = [
            {
                "code": s.code,
                "name": s.name,
                "period": s.period,
                "predicted_low": str(s.predicted_low),
                "predicted_high": str(s.predicted_high),
                "predicted_mid": str(s.predicted_mid),
                "actual_value": str(s.actual_value),
                "actual_growth": str(s.actual_growth) if s.actual_growth is not None else None,
                "gap_to_mid": str(s.gap_to_mid) if s.gap_to_mid is not None else None,
                "gap_to_high": str(s.gap_to_high) if s.gap_to_high is not None else None,
                "verdict": s.verdict.value,
                "confidence": str(s.confidence),
            }
            for s in scores
            if s.code == code
        ]
        return {"items": items, "total": len(items)}
    except Exception as e:
        _log.warning("get_stock_scores failed: %s", e)
        return {"items": [], "total": 0}
