"""earnings 模块 — 业绩前瞻 + 实际披露 + 比对打分。

主入口：EarningsService

用法：
    from mommy_chaogu.earnings import (
        EarningsAdapter,
        MockEarningsAdapter,
        EfinanceEarningsAdapter,
        EarningsService,
        EarningsStore,
    )

    # Mock（测试用）
    adapter = MockEarningsAdapter()

    # 真实数据（efinance，依赖网络）
    adapter = EfinanceEarningsAdapter()

    store = EarningsStore(Path("data/earnings_actual.db"))
    service = EarningsService(adapter, store, Path("data/earnings_preview.db"))

    # 1. 拉取 actual
    codes = ["603662", "603986"]
    result = service.pull_actual(codes, "H1 2026")

    # 2. 批量比对
    result = service.score_all("H1 2026")

    # 3. 看未来 7 天披露日历
    upcoming = service.watch_calendar(days_ahead=7)

    # 4. 看 verdict 分布
    summary = service.summary("H1 2026")
"""

from __future__ import annotations

from mommy_chaogu.earnings.adapter import (
    EarningsAdapter,
    MockEarningsAdapter,
)
from mommy_chaogu.earnings.efinance_adapter import EfinanceEarningsAdapter
from mommy_chaogu.earnings.service import EarningsService, ServiceResult
from mommy_chaogu.earnings.store import EarningsStore
from mommy_chaogu.earnings.types import (
    VERDICT_LABEL,
    EarningsActual,
    EarningsCalendar,
    EarningsScore,
    EarningsSource,
    EarningsVerdict,
)

__all__ = [
    "VERDICT_LABEL",
    "EarningsActual",
    "EarningsAdapter",
    "EarningsCalendar",
    "EarningsScore",
    "EarningsService",
    "EarningsSource",
    "EarningsStore",
    "EarningsVerdict",
    "EfinanceEarningsAdapter",
    "MockEarningsAdapter",
    "ServiceResult",
]
