#!/usr/bin/env python3
"""Run the legacy database migration against a disposable fixture."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import migrate_db_layout as migration


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mommy-migration-") as directory:
        root = Path(directory)
        data = root / "data"
        data.mkdir()

        paths = {
            "LEGACY_WATCHLIST_DB": data / "watchlist.db",
            "LEGACY_SEMICON_DB": data / "semicon.db",
            "LEGACY_EARNINGS_PREVIEW_DB": data / "earnings_preview.db",
            "LEGACY_EARNINGS_ACTUAL_DB": data / "earnings_actual.db",
            "LEGACY_BACKTEST_DB": data / "semicon_backtest.db",
            "MARKET_DB": data / "market.db",
            "PORTFOLIO_DB": data / "portfolio.db",
            "AGENT_DB": data / "agent.db",
            "REFERENCE_DB": data / "reference.db",
        }
        for name, value in paths.items():
            setattr(migration, name, value)

        legacy = paths["LEGACY_WATCHLIST_DB"]
        with sqlite3.connect(legacy) as connection:
            connection.execute("CREATE TABLE groups (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO groups VALUES (1, 'fixture')")
            connection.execute("CREATE TABLE quote_cache (code TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO quote_cache VALUES ('600519')")
            connection.execute(
                "CREATE TABLE agent_memory "
                "(id INTEGER PRIMARY KEY, role TEXT, content TEXT, timestamp TEXT)"
            )
            connection.execute(
                "INSERT INTO agent_memory VALUES (1, 'user', 'fixture', '2026-01-01')"
            )

        migration.run()
        assert legacy.with_suffix(".db.bak").exists()
        for db_name, table in (
            ("PORTFOLIO_DB", "groups"),
            ("MARKET_DB", "quote_cache"),
            ("AGENT_DB", "agent_memory"),
        ):
            with sqlite3.connect(paths[db_name]) as connection:
                count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count == 1, (db_name, table, count)

        migration.run()

    print("Migration smoke test passed")


if __name__ == "__main__":
    main()
