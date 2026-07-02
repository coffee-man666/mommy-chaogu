"""earnings 模块 — 数据源 Adapter Protocol。

设计：与 MarketDataAdapter 模式一致 —— runtime_checkable Protocol，
方便 mock 测试 + 多数据源 fallback。

目前实现：
- MockEarningsAdapter：测试用，固定数据
- （未来）EfinanceEarningsAdapter：从东方财富拉业绩预告/快报
- （未来）TencentEarningsAdapter：从腾讯财经拉
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Protocol, runtime_checkable

from mommy_chaogu.earnings.types import EarningsActual, EarningsCalendar, EarningsSource


@runtime_checkable
class EarningsAdapter(Protocol):
    """业绩数据源接口。"""

    name: str

    def fetch_actual(
        self,
        code: str,
        period: str,
        *,
        since: date | None = None,
    ) -> list[EarningsActual]:
        """拉取某只股票在某报告期的实际披露业绩。

        返回空列表表示无数据或拉取失败（不抛异常）。
        """
        ...

    def fetch_calendar(
        self,
        code: str,
        *,
        since: date | None = None,
    ) -> list[EarningsCalendar]:
        """拉取某只股票的公告日历。

        返回空列表表示无数据或拉取失败（不抛异常）。
        """
        ...


# ---------- Mock 实现（测试 + 演示用）----------


class MockEarningsAdapter:
    """Mock 数据源，固定 41 家公司的假数据。

        用于：
    - 单元测试
    - 演示：手动触发 actual vs predicted 比对流程
    - 演练：实战前预演信号触发

    数据生成规则：
    - 80% 概率在预测区间内
    - 10% 概率超预测上限 20%
    - 10% 概率低于预测下限 20%
    """

    name = "mock"

    # 41 家公司的固定 seed（与 earnings_preview.db 同步）
    MOCK_DATA: ClassVar[dict[str, dict[str, object]]] = {
        "603662": {"name": "柯力传感", "low": 188.0, "high": 217.0},
        "603986": {"name": "兆易创新", "low": 1070.0, "high": 1370.0},
        "002745": {"name": "木林森", "low": 824.0, "high": 1286.0},
        "688383": {"name": "新益昌", "low": 430.0, "high": 671.0},
        "300223": {"name": "北京君正", "low": 440.0, "high": 520.0},
        "002617": {"name": "露笑科技", "low": 336.0, "high": 627.0},
        "688519": {"name": "南亚新材", "low": 354.0, "high": 505.0},
        "002876": {"name": "三孚新科", "low": 261.0, "high": 502.0},
        "301536": {"name": "星宸科技", "low": 336.0, "high": 627.0},
        "688072": {"name": "富创精密", "low": 188.0, "high": 217.0},
    }

    def fetch_actual(
        self,
        code: str,
        period: str,
        *,
        since: date | None = None,
    ) -> list[EarningsActual]:
        """返回 mock 数据（如果 code 在白名单内）。"""
        from datetime import datetime

        if code not in self.MOCK_DATA:
            return []

        info = self.MOCK_DATA[code]
        name = str(info["name"])

        # 披露日固定 2026-07-20
        disc_date = date(2026, 7, 20)
        if since is not None and disc_date < since:
            return []

        # 模拟：在预测区间中位数附近
        low = float(info["low"])  # type: ignore[arg-type]
        high = float(info["high"])  # type: ignore[arg-type]
        mid = (low + high) / 2

        # 假设 H1 2026 净利润 = 1 亿 × (1 + growth/100)
        # mock 净利润值（基于 PE 反推得近似值）
        mock_base = {
            "603662": 3.0e8,  # 3 亿
            "603986": 2.5e9,  # 25 亿（兆易体量大）
            "002745": 1.2e9,
            "688383": 4.0e8,
            "300223": 5.0e8,
            "002617": 8.0e8,
            "688519": 6.0e8,
            "002876": 5.0e8,
            "301536": 3.0e8,
            "688072": 2.5e8,
        }
        base = mock_base.get(code, 5e8)
        # 实际增速 = 中位数 + 随机扰动（这里固定 +0%，可改为 hash 模拟）
        from decimal import Decimal

        actual_growth = Decimal(str(mid))
        # 计算：base * (1 + mid/100)，全程 Decimal 保证精度
        base_d = Decimal(str(base))
        actual_value = base_d * (Decimal("1") + actual_growth / Decimal("100"))

        return [
            EarningsActual(
                code=code,
                name=name,
                period=period,
                actual_value=actual_value,
                growth_pct=actual_growth,
                disclosure_date=date(2026, 7, 20),
                source=EarningsSource.FORECAST,
                note=f"Mock: {code} {period} 业绩预告",
                fetched_at=datetime.utcnow(),
            )
        ]

    def fetch_calendar(
        self,
        code: str,
        *,
        since: date | None = None,
    ) -> list[EarningsCalendar]:
        """返回 mock 公告日期（固定 7/20）。"""
        if code not in self.MOCK_DATA:
            return []

        disc_date = date(2026, 7, 20)
        if since is not None and disc_date < since:
            return []

        info = self.MOCK_DATA[code]
        name = str(info["name"])

        return [
            EarningsCalendar(
                code=code,
                name=name,
                period="H1 2026",
                disclosure_date=date(2026, 7, 20),
                is_estimated=False,
                source="mock",
            )
        ]
