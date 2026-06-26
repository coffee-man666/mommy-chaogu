"""CacheManager：高层操作（warmup / refresh / stats）。"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mommy_chaogu.cache.adapter import CachedMarketDataAdapter
from mommy_chaogu.cache.config import CacheConfig
from mommy_chaogu.cache.store import CacheStore


class CacheManager:
    """缓存管理器（高级 API）。"""

    def __init__(self, store: CacheStore, adapter: CachedMarketDataAdapter) -> None:
        self.store = store
        self.adapter = adapter

    @classmethod
    def default(cls, db_path: Path, config: CacheConfig | None = None) -> CacheManager:
        """默认构造：EfinanceAdapter + CacheStore + CachedMarketDataAdapter。"""
        from mommy_chaogu.cache.adapter import CachedMarketDataAdapter
        from mommy_chaogu.market_data import EfinanceAdapter
        store = CacheStore(db_path)
        adapter = CachedMarketDataAdapter(EfinanceAdapter(), store, config=config)
        return cls(store, adapter)

    # ---------- warmup ----------

    def warmup_market(self) -> dict[str, Any]:
        """盘前预热：拉一次全市场。"""
        from mommy_chaogu.cache.adapter import CachedMarketDataAdapter  # noqa: F401
        # 强制重置拉新节流，让全市场先拉一次
        self.adapter._last_fetch_attempt["market_snapshot:all"] = datetime.min.replace(tzinfo=UTC)
        quotes = self.adapter.list_market_quotes()
        return {
            "ok": True,
            "n_quotes": len(quotes),
        }

    def warmup_codes(self, codes: list[str]) -> dict[str, Any]:
        """预热指定股票代码（拉一次报价 + 当日资金流）。"""
        n_ok = 0
        n_fail = 0
        # 重置节流
        for code in codes:
            self.adapter._last_fetch_attempt[f"quote:{code}"] = datetime.min.replace(tzinfo=UTC)
            self.adapter._last_fetch_attempt[f"today_flow:{code}"] = datetime.min.replace(tzinfo=UTC)
        for code in codes:
            q = self.adapter.get_quote(code)
            if q is not None:
                n_ok += 1
            else:
                n_fail += 1
            flows = self.adapter.get_today_money_flow(code)
            if flows:
                pass
        return {
            "ok": True,
            "codes": len(codes),
            "quotes_fetched": n_ok,
            "quotes_failed": n_fail,
        }

    # ---------- refresh（强制拉新） ----------

    def refresh_quote(self, code: str) -> bool:
        """强制刷新单股报价。"""
        self.adapter._last_fetch_attempt[f"quote:{code}"] = datetime.min.replace(tzinfo=UTC)
        return self.adapter.get_quote(code) is not None

    def refresh_market(self) -> int:
        """强制刷新全市场。返回成功获取的 quote 数。"""
        self.adapter._last_fetch_attempt["market_snapshot:all"] = datetime.min.replace(tzinfo=UTC)
        quotes = self.adapter.list_market_quotes()
        return len(quotes)

    # ---------- stats ----------

    def stats(self) -> dict[str, Any]:
        """完整统计：缓存条目 + 命中率 + 数据新鲜度。"""
        cache_stats = self.store.stats()
        cache_stats.update(self.adapter.stats_counters)
        cache_stats["freshness"] = self.adapter.data_freshness_report()
        return cache_stats

    def format_freshness(self) -> str:
        """人类可读的新鲜度报告。"""
        entries = self.adapter.data_freshness_report()
        if not entries:
            return "（缓存为空，先 mommy-cache warmup）"

        lines: list[str] = []
        lines.append(f"📊 数据新鲜度（{len(entries)} 条）")
        lines.append("─" * 60)
        lines.append(f"{'代码':<8} {'名称':<10} {'拉取时间':<20} {'数据时间':<20} {'状态'}")
        lines.append("─" * 60)
        for e in entries:
            age = e["age_seconds"]
            if age < 60:
                emoji = "🟢"
            elif age < 600:
                emoji = "🟡"
            elif age < 3600:
                emoji = "🟠"
            else:
                emoji = "🔴"
            fetched = e["fetched_at"].strftime("%m-%d %H:%M:%S") if e["fetched_at"] else "—"
            quote_ts = e["quote_ts"].strftime("%m-%d %H:%M:%S") if e["quote_ts"] else "—"
            lines.append(f"{e['code']:<8} {(e['name'] or '—')[:10]:<10} "
                         f"{fetched:<20} {quote_ts:<20} {emoji} {age:.0f}s 前")
        return "\n".join(lines)
