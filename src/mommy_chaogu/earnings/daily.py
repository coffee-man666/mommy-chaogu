"""earnings 日频调度任务：收盘后 pull + score + evaluate → Signal。

阶段五（右侧确认常驻化）任务 4：``evaluate_all`` 此前生产零调用，
业绩披露后只能手动 pull+score。本模块把它接成 background 的日频任务——
每个交易日收盘后（Asia/Shanghai 15:35 起，当日一次）：

1. ``pull_actual``：对给定代码集逐报告期拉 actual 写入 store；
2. ``score_all``：actual vs 业绩前瞻逐期比对；
3. ``evaluate_all``：近期披露的 score + 未来 7 天披露日历 → Signal。

信号由调用方（web/background）送入既有 SignalNotifier / 微信管道；
``MOMMY_ALERTS_BUILTIN_ONLY`` 环境变量可一键停用本任务（回滚开关）。

诚实边界：
- 报告期启发式（``current_report_period``）是粗粒度推断，真正以
  earnings_preview 库里出现过的 report_period 为准；
- ``earnings_approaching`` 规则依赖日历表有未来披露日期（外部脚本或
  ``mommy-earnings`` 命令维护），日历为空时该规则自然不触发；
- pull 依赖 efinance 网络，失败时按既有语义计入 failed、不影响 evaluate。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from mommy_chaogu.earnings.service import EarningsService
from mommy_chaogu.earnings.signals import EarningsContext, evaluate_all
from mommy_chaogu.earnings.types import EarningsScore
from mommy_chaogu.signals.custom_evaluation import builtin_alerts_only
from mommy_chaogu.signals.types import Signal

__all__ = [
    "MARKET_TZ",
    "RUN_AT",
    "current_report_period",
    "run_daily",
    "should_run",
]

_log = logging.getLogger(__name__)

#: A 股时区（收盘调度按本地时间判断）
MARKET_TZ = ZoneInfo("Asia/Shanghai")

#: 每日运行时刻：15:00 收盘后留出缓冲
RUN_AT = time(15, 35)

#: 已披露业绩的信号回看窗口（天）——超过窗口的旧 score 不再每日重复评估
RECENT_DAYS = 7

#: 披露临近（T-N）规则的观察窗口（天），与 earnings_approaching 规则一致
APPROACHING_DAYS = 7


def should_run(now: datetime, last_run: date | None) -> bool:
    """是否应触发当日 earnings 任务：收盘后且当日尚未跑过。

    ``now`` 任意时区的 aware datetime（内部转 Asia/Shanghai）。
    """
    local = now.astimezone(MARKET_TZ)
    if local.time() < RUN_AT:
        return False
    return last_run is None or last_run < local.date()


def current_report_period(today: date) -> str:
    """按 A 股披露节奏推断当前披露季对应的报告期。

    粗粒度启发式（adapter 只支持 H1/Q3/FY 期别映射）：
    7-9 月 → 当年 H1；10-12 月 → 当年 Q3；1-6 月 → 上年 FY（年报季）。
    """
    if today.month >= 10:
        return f"Q3 {today.year}"
    if today.month >= 7:
        return f"H1 {today.year}"
    return f"FY {today.year - 1}"


def run_daily(
    service: EarningsService,
    codes: Sequence[str],
    *,
    today: date | None = None,
) -> list[Signal]:
    """pull + score + evaluate，返回信号列表。

    ``codes`` 为空或环境开关停用时直接返回（不触网络）。
    ``today`` 仅测试注入（默认取 Asia/Shanghai 当前日期）。
    """
    if not codes or builtin_alerts_only():
        return []
    today = today or datetime.now(MARKET_TZ).date()

    # 报告期 = 前瞻库出现过的期别 ∪ 按日期推断的当前期（去重、稳定排序）
    periods = sorted({*service.list_preview_periods(), current_report_period(today)})

    for period in periods:
        pull = service.pull_actual(list(codes), period)
        if pull.failed:
            _log.warning(
                "earnings daily pull period=%s ok=%d failed=%d (%s)",
                period,
                pull.ok,
                pull.failed,
                ",".join(pull.failed_codes[:10]),
            )
        score = service.score_all(period)
        _log.info("earnings daily period=%s pulled=%d scored=%d", period, pull.ok, score.ok)

    signals: list[Signal] = []
    signals.extend(_evaluate_scores(service, today))
    signals.extend(_evaluate_calendar(service, today))
    _log.info("earnings daily evaluate done: %d signals", len(signals))
    return signals


def _evaluate_scores(service: EarningsService, today: date) -> list[Signal]:
    """近期披露的 score → beat/meet/miss 类信号。

    只评估 actual 披露日在 ``RECENT_DAYS`` 天内的 score，避免历史结论
    每天重复推送（Bark Deduper 按「一码一规一天」限流，跨天会重推）。
    """
    signals: list[Signal] = []
    for score in service.store.list_scores():
        actual = service.store.get_actual(score.code, score.period)
        if actual is None:
            continue
        days_since = (today - actual.disclosure_date).days
        if not (0 <= days_since <= RECENT_DAYS):
            continue
        signals.extend(evaluate_all(_context_from_score(score, actual.disclosure_date, today)))
    return signals


def _evaluate_calendar(service: EarningsService, today: date) -> list[Signal]:
    """未来 N 天披露日历 + 前瞻预测 → approaching 信号。

    日历表为空（未维护）时自然返回空，不伪造披露日期。
    """
    signals: list[Signal] = []
    for cal in service.store.list_calendars(
        since_date=today.isoformat(),
        days_ahead=APPROACHING_DAYS,
    ):
        predicted = service.load_prediction(cal.code, cal.period)
        if predicted is None:
            continue
        name, _low, high = predicted
        signals.extend(
            evaluate_all(
                EarningsContext(
                    code=cal.code,
                    name=name,
                    period=cal.period,
                    disclosure_date=cal.disclosure_date,
                    today=today,
                    predicted_high=high,
                    score_verdict=None,
                    score_confidence=None,
                )
            )
        )
    return signals


def _context_from_score(score: EarningsScore, disclosure: date, today: date) -> EarningsContext:
    return EarningsContext(
        code=score.code,
        name=score.name,
        period=score.period,
        disclosure_date=disclosure,
        today=today,
        predicted_high=score.predicted_high,
        score_verdict=score.verdict.value,
        score_confidence=score.confidence,
    )
