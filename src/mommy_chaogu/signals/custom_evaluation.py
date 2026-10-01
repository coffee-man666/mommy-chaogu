"""自定义告警的常驻评估：CustomAlert + 实时 Quote → Signal。

阶段五（右侧确认常驻化）的共用评估函数：三处 ``alerter.evaluate`` 调用点
（web/background 的 ``_tick``、monitor/poller 的 ``run``、
``mommy monitor snapshot --with-signals``）都旁挂本模块，避免三份拷贝。

设计要点（见 docs/plans/trading-method-landing.md 阶段五任务 2）：
- CustomAlert 分支**直接吃 Quote、不构造 SnapshotRow**——SnapshotRow 依赖
  自选股 entry，而 custom_alerts 是独立表、code 任意；评估循环的取数代码集
  应为 ``watchlist.get_all_codes() ∪ enabled custom_alerts 的 codes``。
- 告警代码的 Quote 缺失时经 ``fetch_quote`` 逐码补拉（容忍失败）。
- 命中转 Signal（severity=warning）进既有 SignalNotifier/Deduper 与微信
  sender——推送限流天然继承（一码一规一天），不新造机制。
- 环境变量 ``MOMMY_ALERTS_BUILTIN_ONLY`` 可一键停用整个新评估分支
  （含 earnings 日频评估），回到仅内置 7 条规则（回滚开关，§5 R3）。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime

from mommy_chaogu.market_data.types import Quote
from mommy_chaogu.signals.custom_alerts import CustomAlert, CustomAlertStore
from mommy_chaogu.signals.types import Signal, SignalSeverity

__all__ = [
    "MOMMY_ALERTS_BUILTIN_ONLY_ENV",
    "builtin_alerts_only",
    "evaluate_custom_alerts",
    "load_enabled_custom_alerts",
]

_log = logging.getLogger(__name__)

#: 置为真值时停用新增评估分支（自定义告警 + earnings 日频评估），回到仅内置规则。
MOMMY_ALERTS_BUILTIN_ONLY_ENV = "MOMMY_ALERTS_BUILTIN_ONLY"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

# 条件 → 人话短语（与 strategies.py 的 phrases 对齐，方向按「触发时」描述）
_CONDITION_PHRASES: dict[str, str] = {
    "price_above": "价格上穿",
    "price_below": "价格跌破",
    "change_pct_above": "涨幅超过",
    "change_pct_below": "跌幅超过",
}

#: 自定义告警信号的 rule_id 前缀（Deduper 按 code+rule_id 一天一条）
_RULE_ID_PREFIX = "custom_alert"


def builtin_alerts_only() -> bool:
    """新增评估分支是否被环境变量一键停用。"""
    raw = os.environ.get(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "")
    return raw.strip().lower() in _TRUE_VALUES


def load_enabled_custom_alerts(store: CustomAlertStore | None) -> list[CustomAlert]:
    """读取启用的自定义告警；store 未注入或开关停用时返回空。"""
    if store is None or builtin_alerts_only():
        return []
    try:
        return [a for a in store.list_all() if a.enabled]
    except Exception:
        _log.exception("custom alert store read failed, skip this round")
        return []


def evaluate_custom_alerts(
    alerts: Iterable[CustomAlert],
    quotes: Mapping[str, Quote],
    *,
    fetch_quote: Callable[[str], Quote | None] | None = None,
    now: datetime | None = None,
) -> list[Signal]:
    """对一批告警逐条评估，命中转为 Signal。

    - ``quotes``：已有报价（如 Snapshot 行内的 Quote），按 code 索引；
    - ``fetch_quote``：告警代码不在 ``quotes`` 里时的补拉入口
      （adapter.get_quote）；单码失败只记日志，不影响其他告警；
    - 评估与命中计数写 INFO 日志（与 poller tick 同级，验收「评估可观测」）。
    """
    alert_list = list(alerts)
    if not alert_list:
        return []
    ts = now or datetime.now(UTC)
    quote_map: dict[str, Quote] = dict(quotes)
    hits: list[Signal] = []
    for alert in alert_list:
        quote = quote_map.get(alert.code)
        if quote is None and fetch_quote is not None:
            try:
                quote = fetch_quote(alert.code)
            except Exception as e:
                _log.warning("fetch_quote(%s) for custom alert failed: %s", alert.code, e)
                quote = None
            if quote is not None:
                quote_map[alert.code] = quote
        if quote is None:
            continue
        if not CustomAlertStore.evaluate(alert, quote):
            continue
        hits.append(_to_signal(alert, quote, ts))
    _log.info(
        "custom alerts evaluated=%d quotes=%d hits=%d",
        len(alert_list),
        len(quote_map),
        len(hits),
    )
    return hits


def _to_signal(alert: CustomAlert, quote: Quote, ts: datetime) -> Signal:
    """一条命中的告警 → Signal 对象（进既有 SignalNotifier / 微信管道）。"""
    is_pct = alert.condition.startswith("change_pct")
    trigger = quote.change_pct if is_pct else quote.price
    phrase = _CONDITION_PHRASES.get(alert.condition, alert.condition)
    current = f"当前涨跌幅 {quote.change_pct}%" if is_pct else f"当前价 {quote.price}"
    rule_id = f"{_RULE_ID_PREFIX}_{alert.id}" if alert.id is not None else _RULE_ID_PREFIX
    return Signal(
        timestamp=ts,
        code=quote.code,
        name=alert.name or quote.name,
        rule_id=rule_id,
        severity=SignalSeverity.WARNING,
        title=f"{alert.name} {phrase} {alert.threshold}",
        detail=(
            f"{current}（自定义告警：condition={alert.condition}，threshold={alert.threshold}）"
        ),
        metrics={
            "condition": alert.condition,
            "threshold": str(alert.threshold),
            "alert_id": alert.id,
        },
        trigger_value=trigger,
        threshold_value=alert.threshold,
    )
