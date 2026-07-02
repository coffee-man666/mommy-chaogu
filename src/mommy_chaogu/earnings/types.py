"""earnings 模块 — 类型定义。

核心数据契约：
- EarningsActual：单只股票在一个报告期实际披露的业绩
- EarningsCalendar：单只股票的公告日期
- EarningsScore：actual vs predicted 的比对结果
- EarningsVerdict：超预期 / 符合 / 低于预期的枚举

所有金额用 Decimal（元为单位，不做单位换算），所有时间戳用 UTC。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class EarningsVerdict(StrEnum):
    """actual vs predicted 比对结果。"""

    SUPER_BEAT = "super_beat"  # actual > predicted_high（强烈超预期）
    BEAT = "beat"  # predicted_mid < actual <= predicted_high（略超）
    MEET = "meet"  # predicted_low <= actual <= predicted_mid（符合预期）
    MISS = "miss"  # predicted_mid > actual >= predicted_low（略低于）
    DEEP_MISS = "deep_miss"  # actual < predicted_low（大幅低于）
    UNKNOWN = "unknown"  # 数据不足


class EarningsSource(StrEnum):
    """实际业绩数据来源类型。"""

    FORECAST = "forecast"  # 业绩预告（粗范围）
    EXPRESS = "express"  # 业绩快报（精确数字）
    REPORT = "report"  # 半年报/年报全文
    GUIDANCE = "guidance"  # 券商独立调研


VERDICT_LABEL: dict[EarningsVerdict, str] = {
    EarningsVerdict.SUPER_BEAT: "🟢 超预期",
    EarningsVerdict.BEAT: "🟢 略超",
    EarningsVerdict.MEET: "🟡 符合",
    EarningsVerdict.MISS: "🟠 略低",
    EarningsVerdict.DEEP_MISS: "🔴 大幅低于",
    EarningsVerdict.UNKNOWN: "⚪ 未知",
}


@dataclass(frozen=True, slots=True)
class EarningsActual:
    """单只股票在一个报告期实际披露的业绩。"""

    code: str
    name: str
    period: str  # "H1 2026" / "Q3 2026" / "FY 2026"
    actual_value: Decimal  # 净利润（元，Decimal 精度）
    growth_pct: Decimal | None  # 同比增速 %
    disclosure_date: date  # 披露日期
    source: EarningsSource  # 数据来源类型
    note: str | None = None  # 备注（如预告原文）
    fetched_at: datetime | None = None  # 拉取时间（UTC）


@dataclass(frozen=True, slots=True)
class EarningsCalendar:
    """单只股票的公告日期（披露日历）。"""

    code: str
    name: str
    period: str
    disclosure_date: date
    is_estimated: bool  # 是否估计值
    source: str  # 数据来源（如"交易所公告"/"东财"）


@dataclass(frozen=True, slots=True)
class EarningsScore:
    """actual vs predicted 的比对结果。"""

    code: str
    name: str
    period: str
    predicted_low: Decimal  # 预测增速下限 (%)
    predicted_high: Decimal  # 预测增速上限 (%)
    predicted_mid: Decimal  # 预测中位数 (%)
    actual_value: Decimal  # 实际净利润（元）
    actual_growth: Decimal | None  # 实际增速 (%)
    gap_to_mid: Decimal | None  # actual_growth - predicted_mid
    gap_to_high: Decimal | None  # actual_growth - predicted_high
    verdict: EarningsVerdict  # 比对结论
    confidence: Decimal  # 置信度 0~1（基于预测区间宽度）

    @property
    def is_above_predicted_high(self) -> bool:
        return self.verdict in (EarningsVerdict.SUPER_BEAT,)

    @property
    def is_below_predicted_low(self) -> bool:
        return self.verdict in (EarningsVerdict.DEEP_MISS,)
