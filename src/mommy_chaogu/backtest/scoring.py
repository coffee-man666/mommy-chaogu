"""统一评分模块：给回测脚本提供可互比的方向命中率评分。

之前有 4 条路径各自实现了 verify/scoring 逻辑，评分口径不一致：

- ``scripts/backtest_evolution.py`` — 方向命中率 + ±2% 死区（无 neutral）
- ``scripts/backtest_llm.py`` — 同上 + neutral 分支
- ``src/mommy_chaogu/backtest/engine.py`` — 做多 P&L（return > 0 = win）
- ``scripts/prepare_agent_backtest.py`` — 手动

本模块抽出统一的 ``score_direction``，所有回测脚本共用同一套评分口径。

.. note::
    ``agent/verify_engine.py`` 里的 ``_score_direction`` 用在 **实时验证流程**，
    与本模块 **刻意不复用**：实时验证里 neutral 固定返回 ``(hit, 0.5)``，
    会虚增命中率；本模块对回测用更严格的 ±2% 死区，neutral 必须落在死区内
    才算 hit。
"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.verify_engine import VerifyResult

__all__ = ["VerifyResult", "score_direction", "verify_prediction"]

# ±2% 死区阈值（与 verify_engine / backtest_evolution 保持一致）
DEAD_ZONE_PCT = 2.0


def score_direction(direction: str, change_pct: float) -> tuple[str, float]:
    """对单条方向预测评分，返回 ``(status, score)``。

    Args:
        direction: ``"bullish"`` / ``"bearish"`` / ``"neutral"``
        change_pct: 实际涨跌幅（%），正数=涨，负数=跌

    Returns:
        ``(status, score)`` —— status 为 ``"hit"`` 或 ``"missed"``，
        score 在 ``[0.0, 1.0]``。

    评分规则（±2% 死区）:

    - **bullish**:
        - ``> 2``  → ``(hit, 1.0)``
        - ``> 0``  → ``(hit, 0.7)``
        - ``> -2`` → ``(missed, 0.3)``
        - 其他     → ``(missed, 0.0)``
    - **bearish**:
        - ``< -2`` → ``(hit, 1.0)``
        - ``< 0``  → ``(hit, 0.7)``
        - ``< 2``  → ``(missed, 0.3)``
        - 其他     → ``(missed, 0.0)``
    - **neutral**: 涨跌幅绝对值 ``<= 2`` → ``(hit, 0.5)``，否则 ``(missed, 0.3)``
    """
    if direction == "bullish":
        if change_pct > DEAD_ZONE_PCT:
            return ("hit", 1.0)
        if change_pct > 0:
            return ("hit", 0.7)
        if change_pct > -DEAD_ZONE_PCT:
            return ("missed", 0.3)
        return ("missed", 0.0)

    if direction == "bearish":
        if change_pct < -DEAD_ZONE_PCT:
            return ("hit", 1.0)
        if change_pct < 0:
            return ("hit", 0.7)
        if change_pct < DEAD_ZONE_PCT:
            return ("missed", 0.3)
        return ("missed", 0.0)

    # neutral — ±2% 死区内才算 hit（修复 verify_engine 固定 hit 的虚增问题）
    if abs(change_pct) <= DEAD_ZONE_PCT:
        return ("hit", 0.5)
    return ("missed", 0.3)


def verify_prediction(
    pred: dict[str, Any],
    actual_price: float,
    actual_change_pct: float,
) -> VerifyResult:
    """统一验证入口：对一条预测 + 实际行情，返回 ``VerifyResult``。

    Args:
        pred: 预测字典，至少需包含 ``"direction"`` 字段
        actual_price: 验证时点的实际价格
        actual_change_pct: 验证时点相对 entry 的实际涨跌幅（%）

    Returns:
        ``VerifyResult``，``status`` / ``score`` 来自 :func:`score_direction`，
        并回填 ``price`` 和 ``change_pct``。
    """
    direction = str(pred.get("direction", "")).strip().lower()
    status, score = score_direction(direction, actual_change_pct)
    return VerifyResult(
        status=status,
        price=actual_price,
        change_pct=actual_change_pct,
        score=score,
        reason=f"统一评分：direction={direction} change_pct={actual_change_pct:+.2f}%",
    )
