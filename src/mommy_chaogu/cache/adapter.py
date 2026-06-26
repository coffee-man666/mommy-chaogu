"""CachedMarketDataAdapter：装饰器，包装任意 MarketDataAdapter 加缓存层。

设计哲学（按团长要求）：
1. 数据库有数据 → 直接返回 + 标注 fetched_at（妈妈看得见新鲜度）
2. 数据库没数据 → 尝试拉新（失败返回 None）
3. 拉新有节流：距离上次拉新尝试 < interval → 跳过（用旧数据）
4. 拉新失败 → 静默 + warning 日志，保留旧数据

接口契约：
- 实现 MarketDataAdapter Protocol（runtime_checkable）
- 业务层使用无感 — 像直接调底层 adapter 一样
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from mommy_chaogu.cache.config import CacheConfig
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data import MarketDataAdapter, Quote
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MoneyFlow,
    OrderBook,
)

_log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CachedMarketDataAdapter:
    """缓存装饰器。

    用法：
        base = EfinanceAdapter()
        store = CacheStore(Path("data/watchlist.db"))
        adapter = CachedMarketDataAdapter(base, store)
        # 用法和 base 一样，但会自动读/写缓存
        quote = adapter.get_quote("600519")
    """

    def __init__(
        self,
        inner: MarketDataAdapter,
        store: CacheStore,
        config: CacheConfig | None = None,
    ) -> None:
        self.inner = inner
        self.store = store
        self.config = config or CacheConfig()
        self.name = f"cached({inner.name})"
        # 内部状态：每个 (method, code) 上次尝试拉新的时间
        self._last_fetch_attempt: dict[str, datetime] = {}
        # 指标统计
        self.stats_counters: dict[str, int] = {
            "hits": 0,
            "fetches": 0,
            "fetch_ok": 0,
            "fetch_fail": 0,
            "miss": 0,
        }

    # ============================================================
    # 内部：拉新节流判断
    # ============================================================

    def _should_fetch(self, key: str, interval_seconds: int) -> bool:
        last = self._last_fetch_attempt.get(key)
        if last is None:
            return True
        return (_utcnow() - last).total_seconds() >= interval_seconds

    def _mark_fetched(self, key: str) -> None:
        self._last_fetch_attempt[key] = _utcnow()

    # ============================================================
    # 实时报价
    # ============================================================

    def get_quote(self, code: str) -> Quote | None:
        """优先级：缓存（若新） > 底层拉新 > 缓存（哪怕旧）> None"""
        cached = self.store.get_quote(code)
        key = f"quote:{code}"

        # 判断是否需要尝试拉新
        if self._should_fetch(key, self.config.quote_fetch_interval_seconds):
            self._mark_fetched(key)
            self.stats_counters["fetches"] += 1
            try:
                fresh = self.inner.get_quote(code)
            except Exception as e:
                self.stats_counters["fetch_fail"] += 1
                _log.warning("fetch quote(%s) failed: %s", code, e)
                fresh = None

            if fresh is not None:
                self.stats_counters["fetch_ok"] += 1
                try:
                    self.store.set_quote(code, fresh)
                except Exception as e:
                    _log.error("cache set_quote(%s) failed: %s", code, e)
                return fresh

            # 拉新失败
            if cached is not None:
                self.stats_counters["hits"] += 1
                _log.info("serving cached quote(%s) age=%.0fs (fetch failed)",
                          code, cached.age_seconds)
                return cached.quote  # type: ignore[return-value]

            self.stats_counters["miss"] += 1
            return None

        # 不到拉新间隔 → 直接用缓存
        if cached is not None:
            self.stats_counters["hits"] += 1
            return cached.quote  # type: ignore[return-value]
        # 缓存为空但不到拉新间隔（理论上不会发生，但兜底）
        self.stats_counters["miss"] += 1
        return None

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        out: list[Quote] = []
        for code in dict.fromkeys(codes):
            q = self.get_quote(code)
            if q is not None:
                out.append(q)
        return out

    def list_market_quotes(self) -> list[Quote]:
        """全市场快照：优先缓存（保留最新 + 历史），否则拉新并缓存。"""
        snap = self.store.get_latest_market_snapshot()
        key = "market_snapshot:all"
        should_fetch = self._should_fetch(key, self.config.market_snapshot_fetch_interval_seconds)

        if snap is not None and not should_fetch:
            self.stats_counters["hits"] += 1
            # 从快照还原 Quote 对象列表
            from mommy_chaogu.cache.serializer import quote_from_dict
            return [quote_from_dict(d) for d in snap[3]]

        # 尝试拉新
        self._mark_fetched(key)
        self.stats_counters["fetches"] += 1
        try:
            fresh = self.inner.list_market_quotes()
        except Exception as e:
            self.stats_counters["fetch_fail"] += 1
            _log.warning("fetch list_market_quotes failed: %s", e)
            fresh = None

        if fresh:
            self.stats_counters["fetch_ok"] += 1
            try:
                from mommy_chaogu.cache.serializer import quote_to_dict
                quote_dicts = [quote_to_dict(q) for q in fresh]
                quote_ts = fresh[0].timestamp if fresh else None
                self.store.save_market_snapshot(quote_dicts, quote_ts=quote_ts)
                self.store.trim_market_snapshots(self.config.market_snapshot_history_keep)
            except Exception as e:
                _log.error("cache save_market_snapshot failed: %s", e)
            return fresh

        # 拉新失败 → 用旧快照
        if snap is not None:
            self.stats_counters["hits"] += 1
            from mommy_chaogu.cache.serializer import quote_from_dict
            _log.info("serving cached market_snapshot age=%.0fs (fetch failed)",
                      (_utcnow() - snap[1]).total_seconds())
            return [quote_from_dict(d) for d in snap[3]]

        self.stats_counters["miss"] += 1
        return []

    # ============================================================
    # 5档盘口（不缓存，实时性要求太高）
    # ============================================================

    def get_order_book(self, code: str) -> OrderBook | None:
        return self.inner.get_order_book(code)

    # ============================================================
    # K 线（按日期永久缓存）
    # ============================================================

    def get_bars(  # type: ignore[no-untyped-def]
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start=None,
        end=None,
        limit: int | None = None,
    ) -> list[Bar]:
        """K 线缓存：按日期永久保留。

        - 数据库已有该 code 的部分日期 → 用缓存
        - 数据库没有 → 拉新并缓存
        """
        interval_str = interval.value
        adj_str = adjustment.value

        # 1. 尝试从缓存读所有日期
        cached_bars = self.store.get_bars(code, interval_str, adj_str)
        key = f"bar:{code}:{interval_str}:{adj_str}"

        if cached_bars is None or len(cached_bars) == 0:
            # 完全没缓存 → 必须拉新
            self._mark_fetched(key)
            self.stats_counters["fetches"] += 1
            try:
                fresh = self.inner.get_bars(code, interval=interval, adjustment=adjustment,
                                              start=start, end=end, limit=limit)
                self.stats_counters["fetch_ok"] += 1
            except Exception as e:
                self.stats_counters["fetch_fail"] += 1
                _log.warning("fetch bars(%s) failed: %s", code, e)
                return []

            # 写入缓存（每根 K 线一天一条记录）
            for bar in fresh:
                trade_date = bar.timestamp.strftime("%Y-%m-%d")
                from dataclasses import asdict
                bar_dict = asdict(bar)
                # 转换 datetime/Decimal/enum
                bar_dict["timestamp"] = bar.timestamp.isoformat()
                bar_dict["interval"] = interval_str
                bar_dict["adjustment"] = adj_str
                from decimal import Decimal
                for k, v in list(bar_dict.items()):
                    if isinstance(v, Decimal):
                        bar_dict[k] = str(v)
                try:
                    self.store.set_bar(code, interval_str, adj_str, trade_date, bar_dict)
                except Exception as e:
                    _log.error("cache set_bar failed: %s", e)
            return fresh

        # 有缓存 → 看是否需要尝试拉新（节流）
        if self._should_fetch(key, self.config.bar_fetch_interval_seconds):
            self._mark_fetched(key)
            self.stats_counters["fetches"] += 1
            try:
                fresh = self.inner.get_bars(code, interval=interval, adjustment=adjustment,
                                              start=start, end=end, limit=limit)
                self.stats_counters["fetch_ok"] += 1
                for bar in fresh:
                    trade_date = bar.timestamp.strftime("%Y-%m-%d")
                    from dataclasses import asdict
                    bar_dict = asdict(bar)
                    bar_dict["timestamp"] = bar.timestamp.isoformat()
                    bar_dict["interval"] = interval_str
                    bar_dict["adjustment"] = adj_str
                    from decimal import Decimal
                    for k, v in list(bar_dict.items()):
                        if isinstance(v, Decimal):
                            bar_dict[k] = str(v)
                    self.store.set_bar(code, interval_str, adj_str, trade_date, bar_dict)
            except Exception as e:
                _log.warning("refetch bars(%s) failed (using cache): %s", code, e)

        # 从缓存构造 Bar 列表
        self.stats_counters["hits"] += 1
        from mommy_chaogu.market_data.types import Bar, Money
        bars: list[Bar] = []
        for bar_dict in cached_bars:
            ts = bar_dict["timestamp"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            from decimal import Decimal
            bars.append(Bar(
                code=code,
                name=bar_dict.get("name", ""),
                interval=interval,
                adjustment=adjustment,
                timestamp=ts,
                open=Decimal(bar_dict["open"]),
                high=Decimal(bar_dict["high"]),
                low=Decimal(bar_dict["low"]),
                close=Decimal(bar_dict["close"]),
                volume=bar_dict["volume"],
                turnover=Money(Decimal(str(bar_dict["turnover"])), "CNY"),
                change_pct=Decimal(bar_dict["change_pct"]) if bar_dict.get("change_pct") else None,
                turnover_rate=Decimal(bar_dict["turnover_rate"]) if bar_dict.get("turnover_rate") else None,
                amplitude=Decimal(bar_dict["amplitude"]) if bar_dict.get("amplitude") else None,
            ))
        return bars

    # ============================================================
    # Tick / 成交明细（不缓存，实时性要求高）
    # ============================================================

    def get_ticks(self, code: str, limit: int | None = None) -> list[Any]:
        return self.inner.get_ticks(code, limit=limit)

    # ============================================================
    # 资金流
    # ============================================================

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:  # type: ignore[override]
        """当日资金流：节流缓存（默认 5 分钟）。"""
        cached = self.store.get_today_money_flow(code)
        key = f"today_flow:{code}"

        if not self._should_fetch(key, self.config.today_money_flow_fetch_interval_seconds):
            # 不到拉新间隔 → 直接用缓存
            if cached is not None:
                self.stats_counters["hits"] += 1
                return [_money_flow_from_dict(d) for d in cached]
            return []

        # 到拉新间隔 → 尝试拉新
        self._mark_fetched(key)
        self.stats_counters["fetches"] += 1
        try:
            fresh = self.inner.get_today_money_flow(code)
            self.stats_counters["fetch_ok"] += 1
        except Exception as e:
            self.stats_counters["fetch_fail"] += 1
            _log.warning("fetch today_money_flow(%s) failed: %s", code, e)
            fresh = None

        if fresh is not None:
            flow_dicts = [_money_flow_to_dict(f) for f in fresh]
            try:
                self.store.set_today_money_flow(code, flow_dicts)
            except Exception as e:
                _log.error("cache set_today_money_flow failed: %s", e)
            return fresh

        # 拉新失败 → fallback 到旧缓存
        if cached is not None:
            self.stats_counters["hits"] += 1
            _log.info("serving cached today_money_flow(%s) (fetch failed)", code)
            return [_money_flow_from_dict(d) for d in cached]
        return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        """历史资金流：按日期永久缓存。"""
        cached = self.store.get_money_flow_history(code)
        key = f"history_flow:{code}"

        if cached is None or len(cached) == 0:
            self._mark_fetched(key)
            self.stats_counters["fetches"] += 1
            try:
                fresh = self.inner.get_history_money_flow(code, days=days)
                self.stats_counters["fetch_ok"] += 1
            except Exception as e:
                self.stats_counters["fetch_fail"] += 1
                _log.warning("fetch history_money_flow(%s) failed: %s", code, e)
                return []

            # 按 trade_date 分组存
            from collections import defaultdict
            by_date: dict[str, list[MoneyFlow]] = defaultdict(list)
            for f in fresh:
                trade_date = f.timestamp.strftime("%Y-%m-%d")
                by_date[trade_date].append(f)
            for trade_date, flows in by_date.items():
                flow_dicts = [_money_flow_to_dict(f) for f in flows]
                self.store.set_money_flow_history(code, trade_date, flow_dicts)
            return fresh

        # 有缓存
        self.stats_counters["hits"] += 1
        out: list[MoneyFlow] = []
        for d in cached:
            flows = d.get("flows", [])
            out.extend(_money_flow_from_dict(f) for f in flows)
        return out

    # ============================================================
    # 板块（不缓存，每次直接拉新）
    # ============================================================

    def get_belonging_boards(self, code: str) -> list[Board]:
        return self.inner.get_belonging_boards(code)

    # ============================================================
    # 健康检查（直接走底层）
    # ============================================================

    def health_check(self) -> bool:
        """健康：缓存有数据 或 底层能拉新。"""
        cached_codes = self.store.get_all_quote_codes()
        if len(cached_codes) > 0:
            return True
        try:
            return self.inner.health_check()
        except Exception:
            return False

    # ============================================================
    # 工具
    # ============================================================

    def data_freshness_report(self) -> list[dict]:
        """返回 [{code, age_seconds, quote_ts, ...}, ...] 给妈妈看新鲜度。"""
        entries = self.store.get_all_quote_entries()
        now = _utcnow()
        out_list: list = []
        for e in entries:
            out_list.append({
                "code": e.code,
                "name": e.quote.name,
                "fetched_at": e.fetched_at,
                "quote_ts": e.quote_ts,
                "age_seconds": (now - e.fetched_at).total_seconds(),
            })
        out_list.sort(key=lambda x: x["age_seconds"])  # 最新的在前
        return out_list


# ---------- 内部：MoneyFlow 序列化（简化版） ----------

def _money_flow_to_dict(f: MoneyFlow) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """MoneyFlow → JSON-safe dict。

    Money 拆 {amount: str, currency}，Decimal → str，datetime → ISO str。
    """
    def _money(m: object) -> dict[str, str]:
        # 适配 Money dataclass 和 dict
        if hasattr(m, "amount") and not isinstance(m, dict):  # type: ignore[unreachable]
            return {"amount": str(m.amount), "currency": m.currency}  # type: ignore[attr-defined]
        if isinstance(m, dict):
            return {"amount": str(m["amount"]), "currency": m.get("currency", "CNY")}
        raise TypeError(f"Cannot serialize money: {m!r}")

    return {
        "code": f.code,
        "name": f.name,
        "timestamp": f.timestamp.isoformat(),
        "main_net": _money(f.main_net),
        "small_net": _money(f.small_net),
        "medium_net": _money(f.medium_net),
        "large_net": _money(f.large_net),
        "super_large_net": _money(f.super_large_net),
        "main_net_ratio": str(f.main_net_ratio) if f.main_net_ratio is not None else None,
    }


def _recursive_safe(obj: object) -> object:
    """递归把所有 Decimal/datetime 转 JSON-safe。"""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _recursive_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_recursive_safe(v) for v in obj]
    return obj


def _money_flow_from_dict(d: dict) -> MoneyFlow:
    from decimal import Decimal

    from mommy_chaogu.market_data.types import Money, MoneyFlow

    def _money(v: object) -> Money:
        if isinstance(v, dict):
            return Money(Decimal(str(v["amount"])), v.get("currency", "CNY"))
        return Money(Decimal(str(v)), "CNY")

    ts = d["timestamp"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return MoneyFlow(
        code=d["code"],
        name=d.get("name", ""),
        timestamp=ts,
        main_net=_money(d["main_net"]),
        small_net=_money(d["small_net"]),
        medium_net=_money(d["medium_net"]),
        large_net=_money(d["large_net"]),
        super_large_net=_money(d["super_large_net"]),
        main_net_ratio=Decimal(str(d["main_net_ratio"])) if d.get("main_net_ratio") else None,
    )
