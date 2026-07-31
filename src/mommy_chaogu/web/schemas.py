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


class AuthStatusOut(BaseModel):
    """Browser authentication mode without exposing credential material."""

    mode: Literal["none", "token", "pairing"]
    authenticated: bool


# ---------- Setup wizard ----------


class SetupProviderOut(BaseModel):
    """One selectable LLM provider (no secrets)."""

    id: str
    label: str
    default_model: str
    env_key: str


class SetupWeixinStatusOut(BaseModel):
    """Weixin messaging-channel pairing status (no secrets/paths)."""

    connected: bool
    online: bool


class SetupStatusOut(BaseModel):
    """Aggregate onboarding/config status for the setup wizard (no secrets)."""

    auth_mode: Literal["none", "token", "pairing"]
    llm_configured: bool
    provider: str
    model: str
    weixin: SetupWeixinStatusOut
    data_ok: bool


class SetupValidateIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1, max_length=512)


class SetupResultOut(BaseModel):
    ok: bool
    message: str


class SetupSaveIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1, max_length=512)


# ---------- Remote browser pairing ----------


class PairCodeIn(BaseModel):
    """6-digit one-time pairing code payload (manual validation at endpoint).

    The endpoint validates the code is exactly 6 ASCII digits using
    ``str.isascii()`` + ``str.isdigit()`` rather than a regex pattern, so
    Arabic-Indic and full-width digits are rejected. The submitted value is
    never echoed in any error response.
    """

    code: str


class PairResultOut(BaseModel):
    """Pairing result — safe enum + fixed message, no secrets."""

    ok: bool
    message: str


# ---------- Setup: Weixin messaging-channel pairing ----------


class WeixinStartOut(BaseModel):
    """Browser-safe QR pairing start response (no secrets/IDs)."""

    pairing_id: str
    qr_data_url: str
    expires_in_seconds: int
    status: Literal[
        "waiting",
        "scanned",
        "verification_required",
        "connected",
        "already_connected",
        "expired",
        "error",
    ]
    message: str


class WeixinPollIn(BaseModel):
    pairing_id: str = Field(min_length=1, max_length=128)
    verify_code: str = Field(default="", max_length=8, pattern=r"^\d*$")


class WeixinPollOut(BaseModel):
    """Poll result with safe enum + friendly message (no raw payloads)."""

    status: Literal[
        "waiting",
        "scanned",
        "verification_required",
        "connected",
        "already_connected",
        "expired",
        "error",
    ]
    message: str
    gateway_started: bool = False
    gateway_online: bool = False


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


class StockSearchOut(BaseModel):
    """股票名称/代码联想结果。"""

    code: str
    name: str
    source: Literal["watchlist", "semicon", "cache"]


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


# ---------- Overview 聚合 ----------


class BlockStatus(BaseModel):
    """每个聚合区块的独立状态标记。"""

    status: Literal["ok", "stale", "unavailable"]
    as_of: datetime | None = None
    message: str | None = None


class OverviewIndex(BaseModel):
    """紧凑指数条单项（只展示名称、点位、涨跌幅）。"""

    name: str
    price: Decimal
    change_pct: Decimal


class OverviewIndexesBlock(BaseModel):
    indexes: list[OverviewIndex]
    block: BlockStatus


class OverviewWatchlistItem(BaseModel):
    """自选股摘要条目。"""

    code: str
    name: str
    price: Decimal
    change_pct: Decimal
    group: str = ""
    data_age_seconds: int = 0


class OverviewWatchlistBlock(BaseModel):
    total: int
    n_up: int
    n_down: int
    n_flat: int
    items: list[OverviewWatchlistItem]
    block: BlockStatus


class OverviewPortfolioAlert(BaseModel):
    """持仓提醒（只包含需要关注的持仓）。"""

    code: str
    name: str | None = None
    unrealized_pnl_pct: Decimal | None = None
    market_value: Decimal | None = None
    shares: int = 0


class OverviewPortfolioBlock(BaseModel):
    n_positions: int
    total_unrealized_pnl: Decimal | None = None
    total_unrealized_pnl_pct: Decimal | None = None
    alerts: list[OverviewPortfolioAlert]
    block: BlockStatus


class OverviewThemeSummary(BaseModel):
    """关注主题/篮子摘要。"""

    id: str
    name: str
    description: str = ""
    total_stocks: int = 0


class OverviewThemesBlock(BaseModel):
    items: list[OverviewThemeSummary]
    block: BlockStatus


class OverviewSignalSummary(BaseModel):
    """近期信号摘要。"""

    n_recent: int
    n_warning: int
    n_critical: int
    latest_title: str | None = None
    latest_severity: Literal["info", "warning", "critical"] | None = None


class OverviewSignalsBlock(BaseModel):
    summary: OverviewSignalSummary | None
    block: BlockStatus


class OverviewResponse(BaseModel):
    """聚合总览响应 — 一次请求返回今日所有区块。"""

    indexes: OverviewIndexesBlock
    watchlist: OverviewWatchlistBlock
    portfolio: OverviewPortfolioBlock
    themes: OverviewThemesBlock
    signals: OverviewSignalsBlock
