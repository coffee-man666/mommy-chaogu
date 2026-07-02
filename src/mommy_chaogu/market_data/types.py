"""通用行情数据类型 - 业务层与具体数据源解耦。

设计原则：
- frozen=True：行情数据一旦拉取就不应被修改
- Money 用 Decimal：金融金额一律不用 float 避免精度漂移
- 字段命名统一英文 snake_case，源数据中文列名在 adapter 层做映射
- 所有时间字段用 datetime（naive 表示本地时间，含 tz 表示带时区）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

# ---------- 基础枚举 ----------


class MarketType(StrEnum):
    """市场类型。"""

    SH = "SH"  # 上交所（沪 A）
    SZ = "SZ"  # 深交所（深 A）
    BJ = "BJ"  # 北交所
    HK = "HK"  # 港股
    US = "US"  # 美股
    FUND = "FUND"  # 公募基金
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    INDEX = "INDEX"  # 指数
    UNKNOWN = "UNKNOWN"


class QuoteType(StrEnum):
    """行情品种类型。"""

    STOCK = "stock"
    INDEX = "index"
    FUND = "fund"
    FUTURE = "future"
    OPTION = "option"
    BOND = "bond"


class BarInterval(StrEnum):
    """K 线周期。"""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    M60 = "60m"
    D1 = "1d"
    W1 = "1w"
    M = "1M"


class AdjustmentType(StrEnum):
    """复权方式。"""

    NONE = "none"  # 不复权
    FORWARD = "forward"  # 前复权
    BACKWARD = "backward"  # 后复权


# ---------- 金额/价格类型 ----------


@dataclass(frozen=True, slots=True)
class Money:
    """带币种的钱。efinance 数据都是人民币，币种暂写死 CNY。"""

    amount: Decimal
    currency: str = "CNY"

    @classmethod
    def from_yuan(cls, v: float | int | str | Decimal) -> Money:
        return cls(Decimal(str(v)))

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


# ---------- 实时报价 ----------


@dataclass(frozen=True, slots=True)
class Quote:
    """单只标的一帧实时报价。"""

    code: str  # 股票代码（"600519"）
    name: str  # 股票名称（"XD贵州茅"）
    market: MarketType  # 市场类型
    quote_type: QuoteType
    price: Decimal  # 最新价
    open: Decimal  # 今开
    high: Decimal  # 最高
    low: Decimal  # 最低
    prev_close: Decimal  # 昨收
    change: Decimal  # 涨跌额
    change_pct: Decimal  # 涨跌幅（%）
    volume: int  # 成交量（股/份/手 - 跟品种相关）
    turnover: Money  # 成交额
    turnover_rate: Decimal | None  # 换手率（%，仅股票/基金）
    volume_ratio: Decimal | None  # 量比
    pe_dynamic: Decimal | None  # 动态市盈率
    total_market_cap: Money | None  # 总市值
    circulating_market_cap: Money | None  # 流通市值
    timestamp: datetime  # 数据时间
    quote_id: str | None = None  # 内部行情 ID（适配器内部用）
    extra: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"{self.code} {self.name} "
            f"{self.price} ({self.change_pct:+.2f}%) "
            f"@{self.timestamp:%H:%M:%S}"
        )


# ---------- 5档盘口（买卖队列） ----------


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    price: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class OrderBook:
    """5档盘口快照。efinance 的 quote_snapshot 给出买卖各 5 档。"""

    code: str
    name: str
    timestamp: datetime
    bids: tuple[OrderBookLevel, ...]  # 买 5 档，从高到低
    asks: tuple[OrderBookLevel, ...]  # 卖 5 档，从低到高
    last_price: Decimal | None = None
    last_volume: int | None = None

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None


# ---------- K 线 ----------


@dataclass(frozen=True, slots=True)
class Bar:
    """单根 K 线。"""

    code: str
    name: str
    interval: BarInterval
    adjustment: AdjustmentType
    timestamp: datetime  # K 线开始时间
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Money
    change_pct: Decimal | None = field(default=None)  # 涨跌幅 %
    turnover_rate: Decimal | None = field(default=None)  # 换手率 %
    amplitude: Decimal | None = field(default=None)  # 振幅 %


# ---------- Tick / 成交明细 ----------


@dataclass(frozen=True, slots=True)
class Tick:
    """单笔成交。"""

    code: str
    name: str
    timestamp: datetime
    price: Decimal
    volume: int
    prev_close: Decimal
    trade_count: int | None = None  # 单数（多少笔合并）


# ---------- 资金流 ----------


@dataclass(frozen=True, slots=True)
class MoneyFlow:
    """单只股票在某一时间点的资金流（主力/小中大单）。"""

    code: str
    name: str
    timestamp: datetime
    main_net: Money  # 主力净流入
    small_net: Money  # 小单净流入
    medium_net: Money  # 中单净流入
    large_net: Money  # 大单净流入
    super_large_net: Money  # 超大单净流入
    main_net_ratio: Decimal | None = None  # 主力净流入占比 %


# ---------- 板块 ----------


@dataclass(frozen=True, slots=True)
class Board:
    """所属板块（一只股票可能属于多个板块）。"""

    code: str  # 板块代码 "BK1575"
    name: str  # 板块名称 "白酒Ⅲ"
    change_pct: Decimal | None  # 板块涨幅 %
    stocks: tuple[str, ...] = ()  # 板块成分股（股票代码列表），按需填充
