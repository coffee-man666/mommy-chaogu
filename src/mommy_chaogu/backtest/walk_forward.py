"""Walk-forward 测试框架：验证进化系统是否过拟合。

核心思路（walk-forward / out-of-sample 检验）：

1. 把已验证预测按时间排序，前一部分做 **训练集**（提炼知识），后一部分做
   **测试集**（out-of-sample 评估）。
2. 在训练集上模拟 consolidator 的 ``pattern_observed`` 提取——从命中/失误里
   归纳出"方向偏好"（例如某 scope 上 bullish 命中率高，就提炼出一条 bullish
   倾向的知识）。
3. 在测试集上评估"有知识"命中率 vs"无知识（基线）"命中率。
4. 若训练集命中率远高于测试集，说明知识只拟合了历史、未能泛化 → 过拟合。

``overfitting_score = train_hit_rate - test_hit_rate``，越大越可疑。

用 :func:`mommy_chaogu.backtest.scoring.score_direction` 统一评分口径，
与回测脚本 / verify_engine 保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mommy_chaogu.backtest.scoring import score_direction

__all__ = ["WalkForwardResult", "walk_forward_test"]


@dataclass
class WalkForwardResult:
    """Walk-forward 测试结果。

    Attributes:
        train_hit_rate: 训练集命中率（0-1）。
        test_hit_rate: 测试集命中率（0-1）。
        train_size: 训练集样本数。
        test_size: 测试集样本数。
        overfitting_score: ``train_hit_rate - test_hit_rate``，正值表示训练集
            明显好于测试集（可能过拟合）。
        baseline_test_hit_rate: 测试集上"无知识"基线命中率（多数方向），用于
            和 ``test_hit_rate``（有知识）对比，正值说明知识有增量价值。
        knowledge: 从训练集提炼出的知识摘要（scope → 偏好方向 + 命中率）。
    """

    train_hit_rate: float
    test_hit_rate: float
    train_size: int
    test_size: int
    overfitting_score: float
    baseline_test_hit_rate: float = 0.0
    knowledge: dict[str, dict[str, Any]] = field(default_factory=dict)

    def format_report(self) -> str:
        """返回人类可读的格式化报告字符串。"""
        lines = [
            "===== Walk-Forward Test Report =====",
            f"Train set: {self.train_size} samples, hit rate = {self.train_hit_rate:.1%}",
            f"Test  set: {self.test_size} samples, hit rate = {self.test_hit_rate:.1%}",
            f"Overfitting score (train - test): {self.overfitting_score:+.1%}",
        ]
        if self.test_size > 0:
            lines.append(
                f"Baseline test hit rate (no-knowledge): {self.baseline_test_hit_rate:.1%}"
            )
            delta = self.test_hit_rate - self.baseline_test_hit_rate
            lines.append(f"Knowledge lift (test - baseline): {delta:+.1%}")
        if self.knowledge:
            lines.append("Extracted knowledge (from train set):")
            for scope, info in sorted(self.knowledge.items()):
                lines.append(
                    f"  {scope}: {info['preferred_direction']} "
                    f"(train hit rate {info['hit_rate']:.1%}, n={info['samples']})"
                )
        if self.overfitting_score > 0.15:
            lines.append("⚠️  train >> test — 可能过拟合")
        elif self.train_size > 0 and self.test_size > 0:
            lines.append("✅  train ≈ test — 泛化良好")
        return "\n".join(lines)


def _change_pct_of(pred: dict[str, Any]) -> float | None:
    """从预测字典取实际涨跌幅（%），兼容多种字段名。"""
    for key in ("actual_change_pct", "change_pct", "actual_pct"):
        v = pred.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _direction_of(pred: dict[str, Any]) -> str:
    """归一化方向字段为 score_direction 接受的小写方向。"""
    raw = str(pred.get("direction", "")).strip().lower()
    # 兼容历史数据里 "up"/"down" 写法
    mapping = {"up": "bullish", "down": "bearish", "flat": "neutral"}
    return mapping.get(raw, raw)


def _hit_rate(predictions: list[dict[str, Any]]) -> float:
    """计算一组预测的方向命中率（用 score_direction 评分，status==hit）。"""
    if not predictions:
        return 0.0
    hits = 0
    for pred in predictions:
        change = _change_pct_of(pred)
        if change is None:
            continue
        status, _ = score_direction(_direction_of(pred), change)
        if status == "hit":
            hits += 1
    judged = sum(1 for p in predictions if _change_pct_of(p) is not None)
    return hits / judged if judged > 0 else 0.0


def _extract_knowledge(
    train: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """在训练集上模拟 consolidator 的 pattern_observed 提取。

    按 scope（``pred.get("scope")`` 或 ``pred.get("code")``）分组，对每组统计
    各方向的命中率，选出命中率最高的方向作为该组的"提炼知识"。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for pred in train:
        scope = pred.get("scope") or pred.get("code") or "market"
        groups.setdefault(str(scope), []).append(pred)

    knowledge: dict[str, dict[str, Any]] = {}
    for scope, preds in groups.items():
        dir_hits: dict[str, list[bool]] = {}
        for pred in preds:
            change = _change_pct_of(pred)
            if change is None:
                continue
            direction = _direction_of(pred)
            status, _ = score_direction(direction, change)
            dir_hits.setdefault(direction, []).append(status == "hit")
        if not dir_hits:
            continue
        # 选命中率最高（且样本≥2）的方向作为偏好
        best_dir = ""
        best_rate = -1.0
        best_n = 0
        for direction, flags in dir_hits.items():
            rate = sum(1 for f in flags if f) / len(flags)
            if rate > best_rate:
                best_rate = rate
                best_dir = direction
                best_n = len(flags)
        if best_dir:
            knowledge[scope] = {
                "preferred_direction": best_dir,
                "hit_rate": best_rate,
                "samples": best_n,
            }
    return knowledge


def _majority_direction(predictions: list[dict[str, Any]]) -> str:
    """返回一组预测里出现最多的方向（无知识基线策略）。"""
    counts: dict[str, int] = {}
    for pred in predictions:
        counts[_direction_of(pred)] = counts.get(_direction_of(pred), 0) + 1
    if not counts:
        return "neutral"
    return max(counts, key=counts.get)


def walk_forward_test(
    predictions: list[dict[str, Any]],
    train_ratio: float = 0.7,
) -> WalkForwardResult:
    """对一组已验证预测做 walk-forward 过拟合检验。

    Args:
        predictions: 已验证预测列表。每条至少需包含 ``direction`` 和
            ``actual_change_pct``（或 ``change_pct``）字段；可选 ``scope`` /
            ``code`` 用于分组提炼知识。会按 ``created_at``（缺失则按原顺序）
            排序后再切分。
        train_ratio: 训练集占比，``0 < train_ratio < 1``。

    Returns:
        :class:`WalkForwardResult`。

    边界处理：

    - 空列表 → 全 0 结果。
    - 不足 2 条 → 全部归训练集，测试集为空，``test_hit_rate = 0.0``。
    """
    if not predictions:
        return WalkForwardResult(
            train_hit_rate=0.0,
            test_hit_rate=0.0,
            train_size=0,
            test_size=0,
            overfitting_score=0.0,
        )
    if not (0.0 < train_ratio < 1.0):
        raise ValueError(f"train_ratio 必须在 (0, 1)，得到 {train_ratio}")

    # 按 created_at 排序（缺失的排到末尾，保持稳定）
    indexed = list(enumerate(predictions))
    indexed.sort(key=lambda pair: str(pair[1].get("created_at") or "9999"))
    ordered = [p for _, p in indexed]

    n = len(ordered)
    train_size = max(1, round(n * train_ratio))
    train_size = min(train_size, n)
    train = ordered[:train_size]
    test = ordered[train_size:]

    train_hit_rate = _hit_rate(train)
    test_hit_rate = _hit_rate(test)

    knowledge = _extract_knowledge(train)

    # 无知识基线：用训练集多数方向打测试集
    baseline_test_hit_rate = 0.0
    if test:
        majority_dir = _majority_direction(train)
        hits = 0
        judged = 0
        for pred in test:
            change = _change_pct_of(pred)
            if change is None:
                continue
            judged += 1
            status, _ = score_direction(majority_dir, change)
            if status == "hit":
                hits += 1
        baseline_test_hit_rate = hits / judged if judged > 0 else 0.0

    overfitting_score = train_hit_rate - test_hit_rate

    return WalkForwardResult(
        train_hit_rate=train_hit_rate,
        test_hit_rate=test_hit_rate,
        train_size=len(train),
        test_size=len(test),
        overfitting_score=overfitting_score,
        baseline_test_hit_rate=baseline_test_hit_rate,
        knowledge=knowledge,
    )
