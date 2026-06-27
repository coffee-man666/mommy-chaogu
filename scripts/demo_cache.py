#!/usr/bin/env -S uv run python
"""演示缓存效果：用 Mock adapter 模拟东财接口。

展示：
- 第一次拉新（miss）
- 间隔内命中缓存（hit，不调底层）
- 跨间隔拉新（fetch）
- 拉新失败 → fallback 旧缓存
- 数据新鲜度报告
"""
from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.cache import CacheConfig, CacheManager, CacheStore
from mommy_chaogu.market_data import Quote
from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    QuoteType,
)


def mk_quote(code: str, price: str = "100") -> Quote:
    return Quote(
        code=code, name=f"名称{code}",
        market=MarketType.SH, quote_type=QuoteType.STOCK,
        price=Decimal(price), open=Decimal(price), high=Decimal(price),
        low=Decimal(price), prev_close=Decimal(price),
        change=Decimal("0"), change_pct=Decimal("1.5"),
        volume=100000, turnover=Money.from_yuan(100000000),
        turnover_rate=None, volume_ratio=None,
        pe_dynamic=None, total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime.now(UTC),
    )


class MockAdapter:
    """可预设 fetch 行为。"""
    def __init__(self, quote: Quote, fail_next_n: int = 0) -> None:
        self.name = "mock"
        self.quote = quote
        self.fail_next_n = fail_next_n
        self.fetch_count = 0

    def get_quote(self, code: str) -> Quote | None:
        self.fetch_count += 1
        if self.fetch_count <= self.fail_next_n:
            raise ConnectionError(f"simulated fail #{self.fetch_count}")
        return self.quote

    def get_quotes(self, codes): return []
    def list_market_quotes(self): return []
    def get_order_book(self, code): return None
    def get_bars(self, code, **kw): return []
    def get_ticks(self, code, limit=None): return []
    def get_today_money_flow(self, code): return []
    def get_history_money_flow(self, code, days=30): return []
    def get_belonging_boards(self, code): return []
    def health_check(self): return True


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "demo.db"
        store = CacheStore(db_path)

        # 短间隔：2 秒
        cfg = CacheConfig(quote_fetch_interval_seconds=2)
        mock = MockAdapter(mk_quote("600519", "1184.98"))
        from mommy_chaogu.cache import CachedMarketDataAdapter
        adapter = CachedMarketDataAdapter(mock, store, config=cfg)
        mgr = CacheManager(store=store, adapter=adapter)

        print("📊 缓存效果演示")
        print("=" * 70)
        print(f"拉新间隔: {cfg.quote_fetch_interval_seconds} 秒")
        print()

        # 第 1 次：miss → fetch
        print("【第 1 次】首次查询（应该 miss → 拉新）")
        q = adapter.get_quote("600519")
        print(f"  价: {q.price if q else None}, 底层 fetch: {mock.fetch_count}")
        print(f"  stats: {adapter.stats_counters}")
        print()

        # 第 2 次：cache hit
        print("【第 2 次】间隔内查询（应该命中缓存，不调底层）")
        q = adapter.get_quote("600519")
        print(f"  价: {q.price if q else None}, 底层 fetch: {mock.fetch_count}")
        print(f"  stats: {adapter.stats_counters}")
        print()

        # 等过期
        print("【第 3 次】等待 3 秒（超过拉新间隔）")
        import time
        time.sleep(3)
        q = adapter.get_quote("600519")
        print(f"  价: {q.price if q else None}, 底层 fetch: {mock.fetch_count}")
        print(f"  stats: {adapter.stats_counters}")
        print()

        # 模拟东财接口挂
        print("【第 4 次】东财接口抽风（连续失败 2 次）")
        mock.fail_next_n = 99  # 之后都失败
        # 重置拉新节流
        adapter._last_fetch_attempt["quote:600519"] = datetime.min.replace(tzinfo=UTC)
        q = adapter.get_quote("600519")
        print(f"  价: {q.price if q else None} (旧缓存), 底层 fetch: {mock.fetch_count}")
        print(f"  stats: {adapter.stats_counters}")
        print()

        print("=" * 70)
        print(mgr.format_freshness())

    return 0


if __name__ == "__main__":
    sys.exit(main())
