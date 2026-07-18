"""Shared SQLite engine configuration and lifecycle helpers.

Engine-owning stores inherit :class:`EngineOwner`.  The owner is responsible
for disposing the engine explicitly; the finalizer is a last-resort safeguard
for short-lived CLI and test instances.
"""

from __future__ import annotations

import sqlite3
import weakref
from pathlib import Path
from types import TracebackType
from typing import Self

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def create_sqlite_engine(db_path: Path) -> Engine:
    """Create a consistently configured SQLAlchemy SQLite engine."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 5.0},
        echo=False,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            if str(db_path) != ":memory:":
                try:
                    cursor.execute("PRAGMA journal_mode = WAL")
                except sqlite3.OperationalError as exc:
                    # Concurrent first connections can race while another
                    # process switches the persistent journal mode.
                    if "locked" not in str(exc).lower():
                        raise
        finally:
            cursor.close()

    return engine


class EngineOwner:
    """Idempotent lifecycle support for classes that own an ``engine``."""

    engine: Engine

    def _manage_engine(self) -> None:
        self._engine_finalizer = weakref.finalize(self, self.engine.dispose)

    def close(self) -> None:
        """Release pooled connections. Safe to call repeatedly."""
        finalizer = getattr(self, "_engine_finalizer", None)
        if finalizer is not None and finalizer.alive:
            finalizer()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
