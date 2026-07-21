"""/api/signals 路由：历史信号。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from mommy_chaogu.signals import Alerter, SignalStore
from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.deps import get_alerter, get_signal_store
from mommy_chaogu.web.mappers import signal_to_out
from mommy_chaogu.web.schemas import SignalOut

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/recent", response_model=list[SignalOut])
def recent_signals(
    service: Annotated[BackgroundService, Depends(get_service)],
) -> list[SignalOut]:
    """最近一次轮询触发的信号（实时）。"""
    return [signal_to_out(s) for s in service.latest_signals]


@router.get("/history", response_model=list[SignalOut])
def history_signals(
    store: Annotated[SignalStore, Depends(get_signal_store)],
    alerter: Annotated[Alerter, Depends(get_alerter)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    rule_id: Annotated[str | None, Query()] = None,
) -> list[SignalOut]:
    """历史信号（#10 改为读 signal_events 表，读库失败/为空时回退日志解析）。"""
    # 主路径：结构化库查询
    try:
        rows = store.list(limit=limit, rule_id=rule_id)
        if rows:
            return [_row_to_signal_out(r) for r in rows]
    except Exception:
        pass

    # 回退：旧文本日志解析（兼容未迁移的环境）
    return _fallback_log_parse(alerter, limit, rule_id)


def _row_to_signal_out(row: dict[str, Any]) -> SignalOut:
    """SignalStore.list() 的 dict 行 → SignalOut。"""
    ts = row["timestamp"]
    if not isinstance(ts, str):
        ts = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return SignalOut(
        timestamp=ts,
        code=row["code"],
        name=row["name"],
        rule_id=row["rule_id"],
        severity=row["severity"],
        title=row["title"],
        detail=row["detail"],
        trigger_value=row.get("trigger_value"),
        threshold_value=row.get("threshold_value"),
    )


def _fallback_log_parse(alerter: Alerter, limit: int, rule_id: str | None) -> list[SignalOut]:
    """旧文本日志解析（回退路径，保留兼容）。"""
    if alerter.log_path is None or not alerter.log_path.exists():
        return []
    log_path: Path = alerter.log_path
    lines = log_path.read_text(encoding="utf-8").splitlines()
    recent = lines[-limit:] if lines else []

    results: list[SignalOut] = []
    for line in recent:
        try:
            parsed = _parse_signal_line(line)
            if parsed is None:
                continue
            if rule_id and parsed.rule_id != rule_id:
                continue
            results.append(parsed)
        except Exception:
            continue
    return results


def _parse_signal_line(line: str) -> SignalOut | None:
    """解析单条信号日志行（旧格式，回退用）。

    格式：timestamp [severity] code name rule_id: detail
    """
    import re

    pattern = (
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
        r"\[(\w+)\s*\]\s+"
        r"(\d+)\s+(\S+)\s+"
        r"(\w+):\s+(.+)$"
    )
    m = re.match(pattern, line)
    if not m:
        return None
    ts_str, severity, code, name, rule_id_str, detail = m.groups()
    return SignalOut(
        timestamp=datetime.fromisoformat(ts_str),
        code=code,
        name=name,
        rule_id=rule_id_str,
        severity=severity.lower().strip(),
        title=f"{name} {rule_id_str}",
        detail=detail,
    )
