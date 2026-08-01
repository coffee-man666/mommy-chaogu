"""/api/overview 路由：今日一屏聚合。

一次请求返回指数、自选摘要、持仓提醒、主题列表和信号摘要。
只编排现有 service/store，不复制行情或业务计算逻辑。
每个区块独立标记 ok/stale/unavailable，部分失败不拖垮整页。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from mommy_chaogu.cache import CacheStore
from mommy_chaogu.market_data import MarketDataAdapter
from mommy_chaogu.market_data.rankings import fetch_indexes
from mommy_chaogu.portfolio import PortfolioStore
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.deps import (
    get_adapter,
    get_cache_store,
    get_portfolio_store,
    get_watchlist_store,
)
from mommy_chaogu.web.schemas import (
    BlockStatus,
    OverviewIndex,
    OverviewIndexesBlock,
    OverviewPortfolioAlert,
    OverviewPortfolioBlock,
    OverviewResponse,
    OverviewSignalsBlock,
    OverviewSignalSummary,
    OverviewThemesBlock,
    OverviewThemeSummary,
    OverviewWatchlistBlock,
    OverviewWatchlistItem,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/overview", tags=["overview"])

# 只展示 4 个核心指数
_CORE_INDEX_NAMES = {"上证指数", "深证成指", "创业板指", "沪深300"}

# 持仓提醒阈值：涨跌超 ±5% 才展示
_ALERT_PNL_THRESHOLD = Decimal("5")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------- 指数 ----------


def _fetch_indexes() -> OverviewIndexesBlock:
    now = _utcnow()
    try:
        raw = fetch_indexes()
    except Exception as exc:
        _log.warning("overview indexes fetch failed: %s", exc)
        return OverviewIndexesBlock(
            indexes=[],
            block=BlockStatus(status="unavailable", message="指数数据获取失败"),
        )

    indexes = [
        OverviewIndex(name=i.name, price=i.price, change_pct=i.change_pct)
        for i in raw
        if i.name in _CORE_INDEX_NAMES
    ]
    if not indexes:
        return OverviewIndexesBlock(
            indexes=[],
            block=BlockStatus(status="unavailable", message="未获取到指数数据"),
        )
    return OverviewIndexesBlock(
        indexes=indexes,
        block=BlockStatus(status="ok", as_of=now),
    )


# ---------- 自选股 ----------


def _build_watchlist(
    service: BackgroundService | None,
    store: WatchlistStore,
) -> OverviewWatchlistBlock:
    # 优先用后台快照（内存缓存，无网络开销）
    snap = service.latest_snapshot if service else None
    if snap is not None:
        items = [
            OverviewWatchlistItem(
                code=row.entry.code,
                name=row.entry.name or row.quote.name,
                price=row.quote.price,
                change_pct=row.quote.change_pct,
                group=row.group_name,
                data_age_seconds=int((_utcnow() - row.quote.timestamp).total_seconds())
                if row.quote.timestamp
                else 0,
            )
            for row in snap.rows
        ]
        return OverviewWatchlistBlock(
            total=snap.n_codes,
            n_up=snap.n_up,
            n_down=snap.n_down,
            n_flat=snap.n_flat,
            items=items,
            block=BlockStatus(status="ok", as_of=service.last_poll_at() if service else None),
        )

    # 快照尚未生成 — 返回静态自选列表（无行情）
    entries = store.list_entries()
    if not entries:
        return OverviewWatchlistBlock(
            total=0,
            n_up=0,
            n_down=0,
            n_flat=0,
            items=[],
            block=BlockStatus(status="ok", as_of=_utcnow(), message="自选股为空"),
        )
    items = [
        OverviewWatchlistItem(
            code=e.code,
            name=e.name or "",
            price=Decimal("0"),
            change_pct=Decimal("0"),
            group=e.group.name if e.group else "",
        )
        for e in entries
    ]
    return OverviewWatchlistBlock(
        total=len(items),
        n_up=0,
        n_down=0,
        n_flat=0,
        items=items,
        block=BlockStatus(
            status="stale",
            as_of=_utcnow(),
            message="行情快照尚未生成，显示自选列表",
        ),
    )


# ---------- 持仓 ----------


def _build_portfolio(
    store: PortfolioStore,
    adapter: MarketDataAdapter,
    snapshot_prices: dict[str, Decimal] | None,
) -> OverviewPortfolioBlock:
    positions = store.list_positions()
    if not positions:
        return OverviewPortfolioBlock(
            n_positions=0,
            alerts=[],
            block=BlockStatus(status="ok", as_of=_utcnow(), message="无持仓"),
        )

    # 收集所有持仓代码，先从快照拿价格，不够的再走 adapter
    codes = list({p.code for p in positions})
    prices: dict[str, Decimal] = {}
    if snapshot_prices:
        prices.update({c: p for c, p in snapshot_prices.items() if c in codes})
    missing = [c for c in codes if c not in prices]
    if missing:
        try:
            for c in missing:
                q = adapter.get_quote(c)
                if q is not None:
                    prices[c] = q.price
        except Exception as exc:
            _log.warning("overview portfolio price fetch failed: %s", exc)

    try:
        raw = store.summary(prices)
    except Exception as exc:
        _log.warning("overview portfolio summary failed: %s", exc)
        return OverviewPortfolioBlock(
            n_positions=len(positions),
            alerts=[],
            block=BlockStatus(status="unavailable", message="持仓汇总计算失败"),
        )

    # 只返回有显著变化的持仓作为提醒
    alerts: list[OverviewPortfolioAlert] = []
    for item in raw["positions"]:
        pnl_pct = item.get("unrealized_pnl_pct")
        if pnl_pct is not None and abs(Decimal(str(pnl_pct))) >= _ALERT_PNL_THRESHOLD:
            pos = item["position"]
            alerts.append(
                OverviewPortfolioAlert(
                    code=pos.code,
                    name=pos.name,
                    unrealized_pnl_pct=Decimal(str(pnl_pct)),
                    market_value=item.get("market_value"),
                    shares=item.get("shares", 0),
                )
            )

    status = "ok" if len(prices) == len(codes) else "stale"
    message = None
    if status == "stale":
        message = f"{len(codes) - len(prices)} 只持仓价格未获取"

    return OverviewPortfolioBlock(
        n_positions=raw["n_positions"],
        total_unrealized_pnl=raw.get("total_unrealized_pnl"),
        total_unrealized_pnl_pct=raw.get("total_unrealized_pnl_pct"),
        alerts=alerts,
        block=BlockStatus(status=status, as_of=_utcnow(), message=message),
    )


# ---------- 主题 ----------


def _build_themes(
    store: WatchlistStore,
    cache_store: CacheStore,
    service: BackgroundService | None,
) -> OverviewThemesBlock:
    try:
        from mommy_chaogu.services.basket_service import BasketService

        quote_overrides = {}
        if service and service.latest_snapshot is not None:
            quote_overrides = {row.entry.code: row.quote for row in service.latest_snapshot.rows}
        basket_service = BasketService(store)
        baskets = [
            item for item in basket_service.list_baskets(include_hidden=False) if item["followed"]
        ][:4]
        for code in {member["code"] for basket in baskets for member in basket["members"]}:
            if code in quote_overrides:
                continue
            cached = cache_store.get_quote(code)
            if cached is not None:
                quote_overrides[code] = cached.quote
        summaries = BasketService(store, quote_overrides=quote_overrides).summarize_many(baskets)
        items = []
        for basket in baskets:
            summary = summaries[basket["id"]]
            items.append(
                OverviewThemeSummary(
                    id=basket["id"],
                    source_id=basket["source_id"],
                    kind=basket["kind"],
                    name=basket["name"],
                    description=basket["description"],
                    total_stocks=basket["total_stocks"],
                    reason=basket["reason"],
                    **summary,
                )
            )
    except Exception as exc:
        _log.warning("overview themes load failed: %s", exc)
        return OverviewThemesBlock(
            items=[],
            block=BlockStatus(status="unavailable", message="主题数据加载失败"),
        )

    item_times = [item.as_of for item in items if item.as_of is not None]
    status = "ok"
    message = None
    if items and all(item.status == "unavailable" for item in items):
        status = "unavailable"
        message = "关注篮子行情暂不可用"
    elif any(item.status != "ok" for item in items):
        status = "stale"
        message = "部分篮子行情不完整"
    return OverviewThemesBlock(
        items=items,
        block=BlockStatus(
            status=status,
            as_of=min(item_times) if item_times else _utcnow(),
            message=message,
        ),
    )


# ---------- 信号 ----------


def _build_signals(service: BackgroundService | None) -> OverviewSignalsBlock:
    signals: list[Any] = service.latest_signals if service else []
    if not signals:
        return OverviewSignalsBlock(
            summary=None,
            block=BlockStatus(status="ok", as_of=_utcnow(), message="暂无信号"),
        )

    n_warning = sum(1 for s in signals if getattr(s, "severity", "") == "warning")
    n_critical = sum(1 for s in signals if getattr(s, "severity", "") == "critical")
    latest = signals[-1] if signals else None

    return OverviewSignalsBlock(
        summary=OverviewSignalSummary(
            n_recent=len(signals),
            n_warning=n_warning,
            n_critical=n_critical,
            latest_title=getattr(latest, "title", None) if latest else None,
            latest_severity=getattr(latest, "severity", None) if latest else None,
        ),
        block=BlockStatus(status="ok", as_of=service.last_poll_at() if service else None),
    )


# ---------- 聚合端点 ----------


@router.get("", response_model=OverviewResponse)
def get_overview(
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
    watchlist_store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
    adapter: Annotated[MarketDataAdapter, Depends(get_adapter)],
    cache_store: Annotated[CacheStore, Depends(get_cache_store)],
) -> OverviewResponse:
    """一次请求返回今日总览：指数 + 自选 + 持仓 + 主题 + 信号。

    每个区块独立编排，部分失败不拖垮整页。
    """
    # 后台服务可能未启动（测试环境）— 容忍
    try:
        service = get_service()
    except RuntimeError:
        service = None

    # 指数（网络请求 + 映射）
    try:
        indexes_block = _fetch_indexes()
    except Exception:
        _log.exception("overview indexes block failed")
        indexes_block = OverviewIndexesBlock(
            indexes=[],
            block=BlockStatus(status="unavailable", message="指数数据获取失败"),
        )

    # 自选股（内存缓存）
    try:
        watchlist_block = _build_watchlist(service, watchlist_store)
    except Exception:
        _log.exception("overview watchlist block failed")
        watchlist_block = OverviewWatchlistBlock(
            total=0,
            n_up=0,
            n_down=0,
            n_flat=0,
            items=[],
            block=BlockStatus(status="unavailable", message="自选股数据加载失败"),
        )

    # 从快照中提取价格给持仓复用（减少网络调用）
    snap_prices: dict[str, Decimal] | None = None
    try:
        if service and service.latest_snapshot is not None:
            snap_prices = {row.entry.code: row.quote.price for row in service.latest_snapshot.rows}
    except Exception:
        snap_prices = None

    # 持仓（可能需要额外拉价）
    try:
        portfolio_block = _build_portfolio(store, adapter, snap_prices)
    except Exception:
        _log.exception("overview portfolio block failed")
        portfolio_block = OverviewPortfolioBlock(
            n_positions=0,
            alerts=[],
            block=BlockStatus(status="unavailable", message="持仓数据加载失败"),
        )

    # 主题（静态 JSON + 映射）
    try:
        themes_block = _build_themes(watchlist_store, cache_store, service)
    except Exception:
        _log.exception("overview themes block failed")
        themes_block = OverviewThemesBlock(
            items=[],
            block=BlockStatus(status="unavailable", message="主题数据加载失败"),
        )

    # 信号（内存缓存）
    try:
        signals_block = _build_signals(service)
    except Exception:
        _log.exception("overview signals block failed")
        signals_block = OverviewSignalsBlock(
            summary=None,
            block=BlockStatus(status="unavailable", message="信号数据加载失败"),
        )

    return OverviewResponse(
        indexes=indexes_block,
        watchlist=watchlist_block,
        portfolio=portfolio_block,
        themes=themes_block,
        signals=signals_block,
    )
