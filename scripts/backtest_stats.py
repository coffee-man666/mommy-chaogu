"""回测统计工具：Wilson 置信区间、精确二项检验、买入持有基准。

被 ``backtest_evolution.py`` 和 ``backtest_llm.py`` 复用，给命中率报告加上
统计显著性信息，并和"等权买入持有"基准做横向对比。

不依赖 scipy（项目未引入），二项检验用 ``math.comb`` 手写精确分布。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "binomial_test",
    "compute_buyhold_baseline",
    "format_hit_rate",
    "wilson_ci",
]


def wilson_ci(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 置信区间（默认 95%，z=1.96）。

    返回 ``(low, high)``，单位为比例（0-1）。

    ``total == 0``（无样本）时返回 ``(0.0, 1.0)`` —— 信息量最小、区间最宽。
    """
    if total <= 0:
        return (0.0, 1.0)
    hits = max(0, min(hits, total))
    phat = hits / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (phat + z2 / (2 * total)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / total + z2 / (4 * total * total))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _mass(k: int, total: int, p: float) -> float:
    """二项分布 P(X=k)，total 次独立试验每次成功概率 p。"""
    return math.comb(total, k) * (p**k) * ((1 - p) ** (total - k))


def binomial_test(hits: int, total: int, p: float = 0.5) -> float:
    """精确双侧二项检验。

    H0：真实成功率 == p。返回双侧 p 值（0-1）。

    采用与 R ``binom.test`` 一致的"小概率之和"方法：在 H0 下，把所有
    概率质量 **不超过** 观察结果概率质量的取值累加。

    ``total == 0`` 时无信息，返回 1.0。
    """
    if total <= 0:
        return 1.0
    if not (0.0 <= p <= 1.0):
        raise ValueError(f"p 必须在 [0, 1]，得到 {p}")
    hits = max(0, min(hits, total))
    p_obs = _mass(hits, total, p)
    result = 0.0
    for k in range(total + 1):
        pk = _mass(k, total, p)
        if pk <= p_obs + 1e-12:
            result += pk
    return min(1.0, result)


def _format_pvalue(p: float) -> str:
    """把 p 值格式化成短字符串，小 p 不被四舍五入成 0。"""
    if p < 0.001:
        return "p<0.001"
    if p < 0.01:
        return f"p={p:.3f}"
    return f"p={p:.2f}"


def format_hit_rate(hits: int, total: int) -> str:
    """格式化命中率为一行统计摘要。

    样例：``"53.0% (Wilson 95% CI: [43.3%, 62.5%], p=0.72)"``

    ``total == 0`` 时返回 ``"N/A (无样本)"``。
    """
    if total <= 0:
        return "N/A (无样本)"
    hits = max(0, min(hits, total))
    rate = hits / total * 100
    low, high = wilson_ci(hits, total)
    p_str = _format_pvalue(binomial_test(hits, total))
    return f"{rate:.1f}% (Wilson 95% CI: [{low * 100:.1f}%, {high * 100:.1f}%], {p_str})"


def _price_of(pred: dict[str, Any], *keys: str) -> float | None:
    """按优先级从预测字典里取价格字段（兼容 entry/entry_price 等命名）。"""
    for k in keys:
        v = pred.get(k)
        if v is not None:
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            return val
    return None


def compute_buyhold_baseline(
    predictions: list[dict[str, Any]],
    adapter: Any = None,
    cache_store: Any = None,
) -> dict[str, Any]:
    """计算等权买入持有（long-only）基准命中率。

    对同一组股票、同一时间窗口，假定每条预测都"看多持有"：
    用 ``entry_price``（预测创建时价格）和验证时的 ``actual_price`` 算涨跌，
    ``actual > entry``（涨了）就算 bullish 基准命中。

    返回 ``{"hits": int, "total": int, "rate": float}``（rate 为 0-1）。
    没有 ``actual_price`` 的预测（过期未验证）计入分母前即被剔除。

    ``adapter`` / ``cache_store`` 预留给"actual_price 缺失时按需回查"的场景，
    当前实现直接用 prediction 里已有的价格字段。
    """
    verifiable: list[tuple[float, float]] = []
    for pred in predictions:
        entry = _price_of(pred, "entry_price", "entry")
        actual = _price_of(pred, "actual_price", "actual")
        if entry is None or actual is None or entry <= 0:
            continue
        verifiable.append((entry, actual))

    total = len(verifiable)
    if total == 0:
        return {"hits": 0, "total": 0, "rate": 0.0}
    hits = sum(1 for entry, actual in verifiable if actual > entry)
    return {"hits": hits, "total": total, "rate": hits / total}


if __name__ == "__main__":
    # 自检：和已知参考值对比。
    assert wilson_ci(7, 10)[0] < 0.7 < wilson_ci(7, 10)[1]
    assert abs(binomial_test(7, 10) - 0.34375) < 1e-9
    print(format_hit_rate(7, 10))
    print(format_hit_rate(0, 0))
    print(format_hit_rate(10, 10))
