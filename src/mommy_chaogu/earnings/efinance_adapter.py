"""earnings 模块 — EfinanceAdapter 实现。

数据源：东方财富 efinance
- `ef.stock.get_all_company_performance(date_str)` 拉某报告期全市场业绩（5500+ 行）
- 字段：股票代码/股票简称/公告日期/净利润/净利润同比增长/...
- 单次请求覆盖全市场，filter 出我们关注的 41 家公司

period 映射：
    "H1 2026" → "2026-06-30"
    "Q3 2026" → "2026-09-30"
    "FY 2026" → "2026-12-31"

注意：此 adapter 依赖网络（efinance 调用东方财富接口）。
测试时用 monkeypatch mock 掉 ef.stock.get_all_company_performance。
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from mommy_chaogu.earnings.types import EarningsActual, EarningsCalendar, EarningsSource

__all__ = [
    "EfinanceEarningsAdapter",
    "_period_to_date",
]


def _period_to_date(period: str) -> str:
    """把内部 period 格式（'H1 2026'）转 efinance ISO 日期（'2026-06-30'）。

    支持：
        H1 YYYY  → YYYY-06-30
        Q3 YYYY  → YYYY-09-30
        FY YYYY  → YYYY-12-31
    """
    parts = period.strip().split()
    if len(parts) != 2:
        raise ValueError(f"period 格式错误，应为 'H1/Q3/FY YYYY'，实际 {period!r}")
    half, year = parts
    year_int = int(year)
    mapping = {"H1": "06-30", "Q3": "09-30", "FY": "12-31"}
    if half not in mapping:
        raise ValueError(f"不支持的 period 类型: {half!r}（仅 H1/Q3/FY）")
    return f"{year_int}-{mapping[half]}"


class EfinanceEarningsAdapter:
    """从东方财富拉取业绩数据。

    优点：
- 单次请求覆盖全市场（5535 只），无需逐只查询
- 字段完整（净利润 / 同比 / 公告日期 / 季报环比 / 季报同比 / EPS / ROE / 毛利率）
- 数据稳定（efinance 已验证）

    缺点：
- 全市场数据量大，filter 时只取关注的 code
- period 必须能映射到 ISO 日期（H1/Q3/FY YYYY）
    """

    name: str = "efinance"

    # 字段名映射（避免硬编码中文，便于 mock 测试）
    FIELD_CODE: ClassVar[str] = "股票代码"
    FIELD_NAME: ClassVar[str] = "股票简称"
    FIELD_DISCLOSURE: ClassVar[str] = "公告日期"
    FIELD_NET_PROFIT: ClassVar[str] = "净利润"
    FIELD_NET_PROFIT_YOY: ClassVar[str] = "净利润同比增长"
    FIELD_REVENUE: ClassVar[str] = "营业收入"
    FIELD_REVENUE_YOY: ClassVar[str] = "营业收入同比增长"
    FIELD_EPS: ClassVar[str] = "每股收益"

    def fetch_actual(
        self,
        code: str,
        period: str,
        *,
        since: date | None = None,
    ) -> list[EarningsActual]:
        """拉取某只股票在某报告期的实际业绩。

        实现：拉一次全市场（缓存到 instance），filter 该 code。
        """
        try:
            df = self._fetch_full_market(period)
        except Exception:
            return []

        return self._extract_actuals(df, code, period, since=since)

    def fetch_calendar(
        self,
        code: str,
        *,
        since: date | None = None,
    ) -> list[EarningsCalendar]:
        """拉取某只股票的公告日历（从全市场业绩里拿公告日期）。"""
        # 公告日历需要看所有已披露的报告期
        # 这里简化：用最近的 period（最新季报）
        try:
            dates = self._get_available_periods()
        except Exception:
            return []

        if not dates:
            return []

        # 拉最新一期的全市场数据，filter 该 code
        latest_period_iso = dates[0]
        period_label = self._iso_to_period(latest_period_iso)
        try:
            df = self._fetch_full_market(period_label)
        except Exception:
            return []

        rows = df[df[self.FIELD_CODE].astype(str) == code]
        if rows.empty:
            return []

        row = rows.iloc[0]
        disc = row[self.FIELD_DISCLOSURE]
        disc_date = self._to_date(disc)
        if disc_date is None:
            return []
        if since is not None and disc_date < since:
            return []

        return [
            EarningsCalendar(
                code=code,
                name=str(row[self.FIELD_NAME]),
                period=period_label,
                disclosure_date=disc_date,
                is_estimated=False,
                source="efinance",
            )
        ]

    # ---------- 内部方法 ----------

    def _fetch_full_market(self, period: str) -> Any:
        """拉一次全市场业绩 DataFrame。

        包装一层方便 monkeypatch 测试。
        """
        import warnings

        import efinance as ef

        date_str = _period_to_date(period)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ef.stock.get_all_company_performance(date_str)

    def _get_available_periods(self) -> list[str]:
        """获取所有可用的报告期 ISO 日期（最新优先）。"""
        import warnings

        import efinance as ef

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = ef.stock.get_all_report_dates()
        if df is None or df.empty:
            return []
        # 第一列是报告日期
        col = df.columns[0]
        return [str(d) for d in df[col].tolist()]

    def _extract_actuals(
        self,
        df: Any,
        code: str,
        period: str,
        *,
        since: date | None = None,
    ) -> list[EarningsActual]:
        """从全市场 DataFrame 提取指定 code 的 EarningsActual。"""
        if df is None or df.empty:
            return []

        # filter
        rows = df[df[self.FIELD_CODE].astype(str) == code]
        if rows.empty:
            return []

        actuals: list[EarningsActual] = []
        for _, r in rows.iterrows():
            disc_date = self._to_date(r[self.FIELD_DISCLOSURE])
            if disc_date is None:
                continue
            if since is not None and disc_date < since:
                continue

            try:
                actual = EarningsActual(
                    code=code,
                    name=str(r[self.FIELD_NAME]),
                    period=period,
                    actual_value=Decimal(str(r[self.FIELD_NET_PROFIT])),
                    growth_pct=self._to_decimal(r[self.FIELD_NET_PROFIT_YOY]),
                    disclosure_date=disc_date,
                    source=EarningsSource.REPORT,
                    note=f"efinance {period} 全市场业绩",
                    fetched_at=datetime.now(UTC),
                )
            except (ValueError, TypeError, KeyError):
                # 单条数据异常，跳过（不破坏整体拉取）
                continue

            actuals.append(actual)

        return actuals

    @staticmethod
    def _to_date(value: Any) -> date | None:
        """pandas Timestamp / datetime / date / str → date。"""
        if value is None:
            return None
        try:
            import pandas as pd

            if isinstance(value, pd.Timestamp):
                result = value.date()
                return date(result.year, result.month, result.day)
        except ImportError:
            pass
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        """float / int / Decimal / NaN → Decimal 或 None。"""
        if value is None:
            return None
        try:
            import math

            if isinstance(value, float) and math.isnan(value):
                return None
        except (TypeError, ValueError):
            pass
        try:
            return Decimal(str(value))
        except (ValueError, TypeError, ArithmeticError):
            return None

    @staticmethod
    def _iso_to_period(iso: str) -> str:
        """'2026-06-30' → 'H1 2026'。"""
        try:
            d = date.fromisoformat(iso[:10])
        except ValueError:
            return f"H1 {iso[:4]}"  # fallback
        if d.month <= 6:
            return f"H1 {d.year}"
        if d.month <= 9:
            return f"Q3 {d.year}"
        return f"FY {d.year}"
