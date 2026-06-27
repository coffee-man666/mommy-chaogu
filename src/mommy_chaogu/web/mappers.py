"""dataclass ↔ Pydantic 转换层。

原则：
- Decimal 全部保留为字符串（前端 Number 接收）
- datetime 全部 ISO 8601（FastAPI 自动处理）
- 不在 mapper 里做数据格式化（格式化在前端）
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from mommy_chaogu.monitor import Snapshot, SnapshotRow
from mommy_chaogu.signals.types import Signal, SignalSeverity
from mommy_chaogu.web.schemas import (
    BarOut,
    OrderBookLevelOut,
    OrderBookOut,
    QuoteOut,
    SignalOut,
    SnapshotOut,
    WatchlistGroupOut,
    WatchlistStockOut,
)
from mommy_chaogu.watchlist.models import Group, StockEntry


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _quote_to_out(row: SnapshotRow) -> QuoteOut:
    """SnapshotRow → QuoteOut。"""
    q = row.quote
    flow = row.latest_flow
    main_net = flow.main_net.amount if flow else None
    # 数据年龄（秒）—— 处理 naive datetime（第三方接口经常不返回 tz）
    ts = q.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = max(0, int((_utcnow() - ts).total_seconds()))
    return QuoteOut(
        code=q.code,
        name=q.name,
        market=q.market.value,
        price=q.price,
        change=q.change,
        change_pct=q.change_pct,
        volume=int(q.volume),
        turnover=q.turnover.amount,
        open=q.open,
        high=q.high,
        low=q.low,
        prev_close=q.prev_close,
        pe=q.pe_dynamic,
        pb=None,  # 项目当前 Quote 不提供静态 PB
        turnover_rate=q.turnover_rate,
        volume_ratio=q.volume_ratio,
        main_net_inflow=main_net,
        timestamp=q.timestamp,
        fetched_at=q.timestamp,  # 装饰器链里 Quote 暂时没区分这两个，先放同一个
        data_age_seconds=age,
    )


def snapshot_to_out(snapshot: Snapshot) -> SnapshotOut:
    """Snapshot → SnapshotOut。"""
    quotes = [_quote_to_out(r) for r in snapshot.rows]
    return SnapshotOut(
        timestamp=snapshot.timestamp,
        quotes=quotes,
        total_main_net=snapshot.total_main_net,
        n_codes=snapshot.n_codes,
        n_up=snapshot.n_up,
        n_down=snapshot.n_down,
        n_flat=snapshot.n_flat,
    )


def bar_to_out(bar: object) -> BarOut:
    """Bar → BarOut（mappers 模块要避免 efinance 类型耦合）。"""
    return BarOut(
        timestamp=bar.timestamp,  # type: ignore[attr-defined]
        open=bar.open.amount,  # type: ignore[attr-defined]
        high=bar.high.amount,  # type: ignore[attr-defined]
        low=bar.low.amount,  # type: ignore[attr-defined]
        close=bar.close.amount,  # type: ignore[attr-defined]
        volume=int(bar.volume),  # type: ignore[attr-defined]
        turnover=bar.turnover.amount,  # type: ignore[attr-defined]
    )


def orderbook_to_out(code: str, ob: object) -> OrderBookOut:
    bids = [
        OrderBookLevelOut(price=lv.price.amount, volume=int(lv.volume))  # type: ignore[attr-defined]
        for lv in ob.bids  # type: ignore[attr-defined]
    ]
    asks = [
        OrderBookLevelOut(price=lv.price.amount, volume=int(lv.volume))  # type: ignore[attr-defined]
        for lv in ob.asks  # type: ignore[attr-defined]
    ]
    return OrderBookOut(
        code=code,
        timestamp=ob.timestamp,  # type: ignore[attr-defined]
        bids=bids,
        asks=asks,
    )


def stock_entry_to_out(entry: StockEntry, group_name: str) -> WatchlistStockOut:
    """StockEntry → WatchlistStockOut。"""
    name = entry.name or entry.code
    if not entry.name and entry.code:
        # 尝试从缓存里取名字（fallback 用）
        try:
            from mommy_chaogu.cache.store import CacheStore

            from .deps import get_db_path

            with CacheStore(get_db_path()).session() as s:
                from sqlalchemy.sql import text

                rows = s.execute(
                    text("SELECT name FROM quote_cache WHERE code = :c LIMIT 1"),
                    {"c": entry.code},
                ).fetchall()
                if rows and rows[0][0]:
                    name = rows[0][0]
        except Exception:
            pass
    # 处理 naive datetime
    added_at = entry.created_at
    if added_at.tzinfo is None:
        added_at = added_at.replace(tzinfo=UTC)
    return WatchlistStockOut(
        code=entry.code,
        name=name,
        group=group_name,
        note=entry.note or "",
        added_at=added_at,
    )


def group_to_out(group: Group, n_stocks: int) -> WatchlistGroupOut:
    return WatchlistGroupOut(
        name=group.name,
        description=group.description or "",
        n_stocks=n_stocks,
    )


def signal_to_out(signal: Signal) -> SignalOut:
    return SignalOut(
        timestamp=signal.timestamp,
        code=signal.code,
        name=signal.name,
        rule_id=signal.rule_id,
        severity=signal.severity.value,
        title=signal.title,
        detail=signal.detail,
        trigger_value=signal.trigger_value,
        threshold_value=signal.threshold_value,
    )
