"""/api/signals 路由：历史信号。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.deps import get_alerter
from mommy_chaogu.web.mappers import signal_to_out
from mommy_chaogu.web.schemas import SignalOut
from mommy_chaogu.signals import Alerter

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/recent", response_model=list[SignalOut])
def recent_signals(
    service: Annotated[BackgroundService, Depends(get_service)],
) -> list[SignalOut]:
    """最近一次轮询触发的信号（实时）。"""
    return [signal_to_out(s) for s in service.latest_signals]


@router.get("/history", response_model=list[SignalOut])
def history_signals(
    alerter: Annotated[Alerter, Depends(get_alerter)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    rule_id: Annotated[str | None, Query()] = None,
) -> list[SignalOut]:
    """历史信号（从 data/signals.log 解析）。"""
    if alerter.log_path is None or not alerter.log_path.exists():
        return []
    log_path: Path = alerter.log_path

    # signals.log 格式：每行一条，json 或自定义文本
    # 简单实现：读后 N 行，解析
    lines = log_path.read_text(encoding="utf-8").splitlines()
    recent = lines[-limit:] if lines else []

    results: list[SignalOut] = []
    for line in recent:
        # 信号格式示例：
        # 2026-06-27 08:30:00 [INFO ] 600519 茅台 price_change: 现价 1850 涨 6.2% (阈值 5%)
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
    """解析单条信号日志行。

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
    ts_str, severity, code, name, rule_id, detail = m.groups()
    return SignalOut(
        timestamp=datetime.fromisoformat(ts_str),
        code=code,
        name=name,
        rule_id=rule_id,
        severity=severity.lower().strip(),
        title=f"{name} {rule_id}",
        detail=detail,
    )
