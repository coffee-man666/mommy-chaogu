"""行情数据源抽象接口（Protocol）。

业务层只依赖这套接口，不关心数据来自 efinance、AKShare、Tushare 还是自爬。
每个实现负责：
1. 把第三方数据格式映射成通用 dataclass
2. 处理 API 异常/限流/字段缺失
3. 提供降级策略（如单股实时坏掉时用全市场 + 过滤）

设计原则：
- 用 `runtime_checkable` Protocol 而不是 ABC，duck typing 更 Pythonic
- 同步接口（阻塞），上层用 asyncio.to_thread 包成异步
- 所有方法要幂等且无副作用
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MoneyFlow,
    OrderBook,
    Quote,
    Tick,
)


@runtime_checkable
class MarketDataAdapter(Protocol):
    """行情数据源接口契约。"""

    name: str  # 数据源标识，例 "efinance" / "akshare" / "tushare"

    # ---------- 实时报价 ----------

    def get_quote(self, code: str) -> Quote | None:
        """拉取单只标的当前实时报价。失败/无数据返回 None，不抛异常。"""
        ...

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量拉取实时报价，按 code 去重，自动跳过失败的。

        实现注意：若数据源不支持批量，可循环单股调用，失败的跳过。
        """
        ...

    def list_market_quotes(self) -> list[Quote]:
        """拉全市场所有标的实时快照。返回数量可能很大（5000+），按需使用。"""
        ...

    # ---------- 盘口 ----------

    def get_order_book(self, code: str) -> OrderBook | None:
        """拉取 5 档盘口。不支持的标的返回 None。"""
        ...

    # ---------- K 线 ----------

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """拉取 K 线。

        - interval: K 线周期
        - adjustment: 复权方式
        - start/end: 区间过滤（闭区间），None 表示不限
        - limit: 最大返回条数，None 表示全量
        """
        ...

    # ---------- Tick / 成交明细 ----------

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        """当日成交明细（按时间倒序或正序按实现定义，调用方不依赖顺序）。"""
        ...

    # ---------- 资金流 ----------

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        """当日按时间点的资金流。"""
        ...

    def get_history_money_flow(
        self, code: str, days: int = 30
    ) -> list[MoneyFlow]:
        """历史资金流（默认 30 天）。"""
        ...

    # ---------- 板块 ----------

    def get_belonging_boards(self, code: str) -> list[Board]:
        """股票所属板块列表。"""
        ...

    # ---------- 健康检查 ----------

    def health_check(self) -> bool:
        """数据源是否可用（可选 ping 一次行情接口）。"""
        ...


# ---------- 工具函数 ----------

def filter_by_market(
    quotes: list[Quote], markets: list[str] | None = None
) -> list[Quote]:
    """按市场类型过滤报价列表。markets 例：['SH', 'SZ']。None 不过滤。"""
    if markets is None:
        return quotes
    market_set = {m.upper() for m in markets}
    return [q for q in quotes if q.market.value in market_set]


def find_quote(quotes: list[Quote], code: str) -> Quote | None:
    """在报价列表中按 code 查找（O(n)，小数据集够用）。"""
    for q in quotes:
        if q.code == code:
            return q
    return None
