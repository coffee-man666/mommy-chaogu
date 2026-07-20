"""Pydantic 响应模型（API 契约）。

Decimal 全部转 str（避免 float 精度问题，符合团队约定）。
datetime 全部 ISO 8601 + UTC。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QuoteOut(BaseModel):
    """单股报价。"""

    model_config = ConfigDict(extra="ignore")

    code: str
    name: str
    market: str = "SH"  # SH / SZ
    price: Decimal
    change: Decimal
    change_pct: Decimal
    volume: int  # 股
    turnover: Decimal  # 元
    open: Decimal
    high: Decimal
    low: Decimal
    prev_close: Decimal
    pe: Decimal | None = None
    pb: Decimal | None = None
    turnover_rate: Decimal | None = None  # 换手率 %
    volume_ratio: Decimal | None = None  # 量比
    main_net_inflow: Decimal | None = None  # 主力净流入（元）
    timestamp: datetime  # 数据时间 (quote_ts)
    fetched_at: datetime  # 拉取时间
    data_age_seconds: int = 0  # 数据年龄（秒）


class SnapshotOut(BaseModel):
    """一次完整快照。"""

    timestamp: datetime
    quotes: list[QuoteOut]
    total_main_net: Decimal
    n_codes: int
    n_up: int
    n_down: int
    n_flat: int


class BarOut(BaseModel):
    """K 线一根。"""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal


class OrderBookLevelOut(BaseModel):
    price: Decimal
    volume: int


class OrderBookOut(BaseModel):
    code: str
    timestamp: datetime
    bids: list[OrderBookLevelOut]
    asks: list[OrderBookLevelOut]


class WatchlistStockOut(BaseModel):
    code: str
    name: str
    group: str
    note: str = ""
    added_at: datetime


class WatchlistGroupOut(BaseModel):
    name: str
    description: str = ""
    n_stocks: int


class AddStockIn(BaseModel):
    code: str
    group: str
    note: str = ""


class AddGroupIn(BaseModel):
    name: str
    description: str = ""


class SignalOut(BaseModel):
    timestamp: datetime
    code: str
    name: str
    rule_id: str
    severity: Literal["info", "warning", "critical"]
    title: str
    detail: str
    trigger_value: Decimal | None = None
    threshold_value: Decimal | None = None


class CacheStatsOut(BaseModel):
    hits: int = 0
    fetches: int = 0
    fetch_ok: int = 0
    fetch_fail: int = 0
    miss: int = 0
    hit_rate: float = 0.0
    freshness: list[dict[str, Any]] = Field(default_factory=list)


class HealthOut(BaseModel):
    ok: bool
    adapter_name: str
    uptime_seconds: float
    last_snapshot_at: datetime | None = None


# ---------- Market Ranking ----------


class IndexOut(BaseModel):
    """大盘指数。"""

    code: str
    name: str
    price: Decimal
    change_pct: Decimal
    prev_close: Decimal


class SectorOut(BaseModel):
    """板块报价。"""

    code: str
    name: str
    change_pct: Decimal
    price: Decimal


# ---------- Portfolio ----------


class PositionOut(BaseModel):
    """单笔持仓。"""

    id: int
    code: str
    name: str | None = None
    buy_price: Decimal
    shares: int
    buy_date: date | None = None
    note: str = ""
    created_at: datetime
    updated_at: datetime


class PositionDetailOut(BaseModel):
    """持仓详情（含盈亏计算）。"""

    id: int
    code: str
    name: str | None = None
    avg_cost: Decimal
    shares: int
    current_price: Decimal | None = None
    market_value: Decimal | None = None
    total_cost: Decimal
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    buy_date: date | None = None
    note: str = ""
    created_at: datetime
    updated_at: datetime


class PortfolioSummaryOut(BaseModel):
    """持仓总览。"""

    positions: list[PositionDetailOut]
    total_cost: Decimal
    total_market_value: Decimal | None = None
    total_unrealized_pnl: Decimal | None = None
    total_unrealized_pnl_pct: Decimal | None = None
    n_positions: int


class AddPositionIn(BaseModel):
    code: str
    name: str | None = None
    buy_price: Decimal
    shares: int
    buy_date: str | None = None  # YYYY-MM-DD
    note: str = ""


class AddAdjustmentIn(BaseModel):
    action: Literal["buy", "sell", "dividend"]
    price: Decimal
    shares: int
    note: str = ""


class AdjustmentOut(BaseModel):
    id: int
    position_id: int
    action: str
    price: Decimal
    shares: int
    timestamp: datetime
    note: str = ""


class WSQuoteMessage(BaseModel):
    """WebSocket 推送：报价更新。"""

    type: Literal["quote_update"] = "quote_update"
    snapshot: SnapshotOut


class WSSignalMessage(BaseModel):
    """WebSocket 推送：信号触发（与 /ws/signals 实际帧一致，复数数组）。"""

    type: Literal["signal_triggered"] = "signal_triggered"
    signals: list[SignalOut]


class WSErrorMessage(BaseModel):
    """WebSocket 推送：错误。"""

    type: Literal["error"] = "error"
    message: str
