"""降级验证引擎：验证 agent 的预测是否被市场印证。

核心设计原则（见 docs/MEMORY-SYSTEM-PLAN.md §6）：
- 报价优先（三重保险：efinance → tencent → stale cache）
- 资金流可选（拿不到不 block，退化为纯报价验证）
- 数据完全不可用 → 标 unverifiable，不猜
- 3 次 data_unavailable → expired（不算 hit 也不算 missed）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from mommy_chaogu.agent.prediction_tracker import _TIMEFRAME_DAYS

_log = logging.getLogger(__name__)


# ---------- 数据结构 ----------


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """单条预测验证的结果。"""

    status: str  # "hit" / "missed" / "expired" / "data_unavailable" / "still_pending"
    price: float | None = None
    change_pct: float | None = None
    score: float = 0.0
    reason: str = ""


# ---------- timeframe 解析 ----------
#
# _TIMEFRAME_DAYS 从 prediction_tracker 导入（权威来源），
# 保证 verify_after（可验证时间）与 _is_expired（过期时间）用同一天数。


def _parse_timeframe_days(timeframe: str) -> int:
    """timeframe 字符串 → 天数。"""
    return _TIMEFRAME_DAYS.get(timeframe, 5)


def _is_expired(created_at: str, timeframe: str, now: datetime | None = None) -> bool:
    """是否已超过 timeframe 窗口。"""
    if now is None:
        now = datetime.now(UTC)
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return False
    return now > created + timedelta(days=_parse_timeframe_days(timeframe))


# ---------- 评分 ----------


def _score_direction(direction: str, change_pct: float) -> tuple[str, float]:
    """方向预测评分。

    Returns:
        (status, score) — status 是 "hit" 或 "missed"
    """
    if direction == "bullish":
        if change_pct > 2:
            return ("hit", 1.0)
        if change_pct > 0:
            return ("hit", 0.7)
        if change_pct > -2:
            return ("missed", 0.3)
        return ("missed", 0.0)

    if direction == "bearish":
        if change_pct < -2:
            return ("hit", 1.0)
        if change_pct < 0:
            return ("hit", 0.7)
        if change_pct < 2:
            return ("missed", 0.3)
        return ("missed", 0.0)

    # neutral — 不验证方向
    return ("hit", 0.5)


def _score_target(
    target_price: float,
    actual_price: float,
    direction: str,
    entry_price: float | None,
) -> tuple[str, float]:
    """目标价预测评分。"""
    distance = abs(actual_price - target_price) / target_price if target_price else 1.0

    if distance < 0.02:
        return ("hit", 1.0)
    if distance < 0.05:
        return ("hit", 0.8)

    # 方向对了但没到目标价
    if direction == "bullish" and entry_price is not None and actual_price > entry_price:
        return ("hit", 0.5)
    if direction == "bearish" and entry_price is not None and actual_price < entry_price:
        return ("hit", 0.5)

    return ("missed", 0.2)


# ---------- 核心验证 ----------


def verify_one(
    pred: dict[str, Any],
    adapter: Any,
    cache_store: Any | None = None,
    now: datetime | None = None,
) -> VerifyResult:
    """验证单条预测。

    Args:
        pred: 预测 dict（来自 PredictionTracker.get_pending 返回格式）
        adapter: MarketDataAdapter（需要 get_quote / get_today_money_flow）
        cache_store: CacheStore（需要 get_quote），可选
        now: 当前时间（测试用）

    Returns:
        VerifyResult
    """
    if now is None:
        now = datetime.now(UTC)

    code = pred["code"]
    direction = pred["direction"]

    # ---------- 检查是否超时 ----------
    created_at = pred.get("created_at", "")
    timeframe = pred.get("timeframe", "5d")
    if _is_expired(created_at, timeframe, now):
        return VerifyResult(status="expired", reason="超过 timeframe 窗口")

    # ---------- 第一优先：报价验证 ----------
    quote = None
    quote_source = ""

    # 尝试 adapter
    try:
        quote = adapter.get_quote(code)
        if quote is not None:
            quote_source = "adapter"
    except Exception as e:
        _log.debug("verify: adapter.get_quote(%s) failed: %s", code, e)

    # adapter 失败 → cache
    if quote is None and cache_store is not None:
        try:
            cache_entry = cache_store.get_quote(code)
            if cache_entry is not None:
                quote = cache_entry.quote if hasattr(cache_entry, "quote") else cache_entry
                quote_source = "stale_cache"
                _log.info("verify: using stale cache for %s", code)
        except Exception as e:
            _log.debug("verify: cache_store.get_quote(%s) failed: %s", code, e)

    # 报价完全不可用
    if quote is None:
        return VerifyResult(
            status="data_unavailable",
            reason="报价数据完全不可用（adapter + cache 均失败）",
        )

    # 提取价格和涨跌幅
    actual_price = float(getattr(quote, "price", 0))
    change_pct = float(getattr(quote, "change_pct", 0))

    if actual_price == 0:
        return VerifyResult(
            status="data_unavailable",
            reason="报价价格为 0，数据无效",
        )

    # ---------- 验证逻辑 ----------
    target_price = pred.get("target_price")
    entry_price = pred.get("entry_price")

    # 有目标价 → 目标价验证
    if target_price is not None and target_price > 0:
        status, score = _score_target(
            target_price=target_price,
            actual_price=actual_price,
            direction=direction,
            entry_price=entry_price,
        )
        return VerifyResult(
            status=status,
            price=actual_price,
            change_pct=change_pct,
            score=score,
            reason=f"目标价验证 ({quote_source})",
        )

    # 无目标价 → 方向验证
    status, score = _score_direction(direction, change_pct)
    return VerifyResult(
        status=status,
        price=actual_price,
        change_pct=change_pct,
        score=score,
        reason=f"方向验证 ({quote_source})",
    )


def verify_pending(
    tracker: Any,
    episodic: Any | None,
    adapter: Any,
    cache_store: Any | None = None,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> dict[str, int]:
    """批量验证所有到期的 pending 预测。

    Args:
        tracker: PredictionTracker
        episodic: EpisodicMemory（用于写回验证结果事件），可选
        adapter: MarketDataAdapter
        cache_store: CacheStore，可选
        max_attempts: 最大验证尝试次数，超过则标 expired
        now: 当前时间（测试用）

    Returns:
        统计 dict: {"total": N, "hit": X, "missed": Y, "data_unavailable": Z, "expired": W}
    """
    if now is None:
        now = datetime.now(UTC)

    verify_before = now.isoformat()
    pending = tracker.get_pending(verify_before)

    results = {"total": len(pending), "hit": 0, "missed": 0, "data_unavailable": 0, "expired": 0}

    for pred in pending:
        pred_id = pred["id"]
        attempts = pred.get("verify_attempts", 0)

        # 超过最大尝试次数 → expired
        if attempts >= max_attempts:
            tracker.update_status(pred_id, status="expired")
            results["expired"] += 1
            _log.info("verify: pred #%d expired (max attempts reached)", pred_id)
            continue

        result = verify_one(pred, adapter, cache_store, now)

        if result.status == "data_unavailable":
            tracker.increment_attempts(pred_id, result.reason)
            results["data_unavailable"] += 1
            _log.info("verify: pred #%d data_unavailable (attempt %d)", pred_id, attempts + 1)
            continue

        if result.status == "still_pending":
            # 还没到验证窗口
            continue

        if result.status == "expired":
            tracker.update_status(pred_id, status="expired")
            results["expired"] += 1
            continue

        # hit 或 missed
        data_coverage_verify = {"quote": result.price is not None}
        tracker.update_status(
            pred_id,
            status=result.status,
            actual_price=result.price,
            actual_change_pct=result.change_pct,
            accuracy_score=result.score,
            data_coverage=data_coverage_verify,
        )
        results[result.status] += 1

        # 回填源事件的 prediction_id（traceability）
        source_event_id = pred.get("source_event_id")
        if source_event_id is not None and episodic is not None:
            try:
                episodic.update_prediction_id(source_event_id, pred_id)
            except Exception as e:
                _log.warning(
                    "verify: failed to backfill prediction_id on event #%s: %s",
                    source_event_id,
                    e,
                )

        # 写回 episodic（验证结果也是一种事件）
        if episodic is not None:
            emoji = "✅" if result.status == "hit" else "❌"
            episodic.write(
                event_type="analysis_record",
                scope=f"stock:{pred['code']}",
                code=pred["code"],
                name=pred.get("name"),
                summary=(
                    f"预测验证：{pred['prediction'][:40]} → {emoji} {result.status.upper()}"
                    f"（score {result.score:.1f}）"
                ),
                data={
                    "prediction_id": pred_id,
                    "result": result.status,
                    "actual_price": result.price,
                    "actual_change_pct": result.change_pct,
                    "score": result.score,
                    "reason": result.reason,
                },
                source="verify_engine",
                confidence=result.score,
                prediction_id=pred_id,
            )

    _log.info(
        "verify_pending: %d total, %d hit, %d missed, %d data_unavailable, %d expired",
        results["total"],
        results["hit"],
        results["missed"],
        results["data_unavailable"],
        results["expired"],
    )
    return results
