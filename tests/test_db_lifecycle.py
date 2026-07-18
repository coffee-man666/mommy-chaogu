"""Database configuration and explicit resource ownership tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import text

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.memory import ConversationMemory
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.semantic_memory import SemanticMemory
from mommy_chaogu.agent.token_tracker import TokenTracker
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.earnings.store import EarningsStore
from mommy_chaogu.portfolio.store import PortfolioStore
from mommy_chaogu.semicon.store import SemiconStore
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.watchlist.store import WatchlistStore

ENGINE_OWNERS = (
    EpisodicMemory,
    ConversationMemory,
    PredictionTracker,
    SemanticMemory,
    TokenTracker,
    CacheStore,
    PortfolioStore,
    SemiconStore,
    CustomAlertStore,
    WatchlistStore,
)


@pytest.mark.parametrize("owner_type", ENGINE_OWNERS)
def test_engine_owner_close_is_idempotent(owner_type: type, tmp_path: Path) -> None:
    owner = owner_type(tmp_path / f"{owner_type.__name__}.db")
    owner.close()
    owner.close()


def test_engine_owner_supports_context_manager(tmp_path: Path) -> None:
    with WatchlistStore(tmp_path / "portfolio.db") as store:
        store.add_group("生命周期")
    store.close()


def test_sqlite_pragmas_are_applied_to_each_connection(tmp_path: Path) -> None:
    with (
        WatchlistStore(tmp_path / "portfolio.db") as store,
        store.engine.connect() as connection,
    ):
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"


def test_earnings_store_close_is_idempotent(tmp_path: Path) -> None:
    with EarningsStore(tmp_path / "earnings.db") as store:
        assert store.engine.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.engine.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    store.close()


def test_concurrent_store_writes_share_busy_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "portfolio.db"

    def add_group(index: int) -> None:
        with WatchlistStore(db_path) as store:
            store.add_group(f"group-{index}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(add_group, range(20)))

    with WatchlistStore(db_path) as store:
        assert len(store.list_groups()) == 20
