"""自选股 pool 必须读 portfolio.db，不能读资金流缓存 market.db。

`db_paths.py` 的职责划分写得很清楚：

    market.db   — 行情数据（缓存 + 历史 K 线 + 资金流）
    portfolio.db — 用户数据（自选股 + 持仓 + 自定义告警）

但 `mommy-flows` 的 `_flows_resolve_pool` 以前把**资金流缓存 db**（`--db`，
默认 market.db）当成自选股 db 传进 `build_pool`。`semicon` 有独立的
`--semicon-db` 所以幸免，`watchlist` 没有对应的参数，于是
`mommy-flows --pool watchlist pull` 永远打印「0 只自选股」——
**静默空池，不报错、不警告**。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mommy_chaogu.cli_commands.flows import _flows_resolve_pool
from mommy_chaogu.cli_support import (
    DEFAULT_FLOWS_DB_PATH,
    DEFAULT_FLOWS_SEMICON_DB_PATH,
    DEFAULT_FLOWS_WATCHLIST_DB_PATH,
)
from mommy_chaogu.db_paths import MARKET_DB, PORTFOLIO_DB, REFERENCE_DB


def _args(pool: str) -> argparse.Namespace:
    return argparse.Namespace(
        pool=pool,
        db=str(DEFAULT_FLOWS_DB_PATH),
        semicon_db=str(DEFAULT_FLOWS_SEMICON_DB_PATH),
        watchlist_db=str(DEFAULT_FLOWS_WATCHLIST_DB_PATH),
        codes=None,
    )


def test_each_pool_uses_its_own_db() -> None:
    """三个 pool 三个 db，互不串用。"""
    assert _flows_resolve_pool(_args("watchlist"))._db_path == Path(PORTFOLIO_DB)
    assert _flows_resolve_pool(_args("semicon"))._db_path == Path(REFERENCE_DB)


def test_watchlist_db_default_is_not_the_flows_cache_db() -> None:
    """回归：以前 watchlist pool 拿到的是 market.db，永远读不到自选股。"""
    assert Path(DEFAULT_FLOWS_WATCHLIST_DB_PATH) == Path(PORTFOLIO_DB)
    assert Path(DEFAULT_FLOWS_WATCHLIST_DB_PATH) != Path(DEFAULT_FLOWS_DB_PATH)
    assert Path(DEFAULT_FLOWS_DB_PATH) == Path(MARKET_DB)


def test_custom_pool_needs_codes() -> None:
    from mommy_chaogu.flows.pool import build_pool

    try:
        build_pool("custom", Path(DEFAULT_FLOWS_DB_PATH), None)
    except ValueError as exc:
        assert "--codes" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("custom pool 不带 codes 应当报错")


def test_watchlist_pool_reads_portfolio_db(tmp_path: Path) -> None:
    """端到端：写进 portfolio.db 的自选股，pool 必须能读出来。"""
    from mommy_chaogu.watchlist import WatchlistStore

    db = tmp_path / "portfolio.db"
    store = WatchlistStore(db)
    store.add_group("T")
    store.add_entry("600519", "T")

    pool = _flows_resolve_pool(
        argparse.Namespace(
            pool="watchlist",
            db=str(tmp_path / "market.db"),
            semicon_db=str(tmp_path / "reference.db"),
            watchlist_db=str(db),
            codes=None,
        )
    )
    assert pool.codes() == ["600519"]
