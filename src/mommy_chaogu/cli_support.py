"""Shared imports and paths for CLI command-family modules."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB
from mommy_chaogu.market_data import EfinanceAdapter
from mommy_chaogu.monitor import Monitor
from mommy_chaogu.semicon.store import Board, ChainPosition, Subcategory
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.watchlist.store import (
    GroupAlreadyExistsError,
    GroupNotFoundError,
    StockEntryNotFoundError,
)

DEFAULT_DB_PATH = PORTFOLIO_DB
DEFAULT_LOG_PATH = Path("data/monitor.log")
DEFAULT_SIGNALS_LOG_PATH = Path("data/signals.log")
DEFAULT_CACHE_DB_PATH = MARKET_DB
DEFAULT_SEMICON_DB_PATH = REFERENCE_DB
DEFAULT_FLOWS_SEMICON_DB_PATH = REFERENCE_DB
DEFAULT_FLOWS_DB_PATH = MARKET_DB
DEFAULT_FLOWS_MONITOR_LOG_PATH = Path("data/flows_monitor.log")
DEFAULT_FLOWS_REPORT_DIR = Path("reports/")


def _store(args: argparse.Namespace) -> WatchlistStore:
    return WatchlistStore(Path(args.db))


__all__ = [
    "AGENT_DB",
    "DEFAULT_CACHE_DB_PATH",
    "DEFAULT_DB_PATH",
    "DEFAULT_FLOWS_DB_PATH",
    "DEFAULT_FLOWS_MONITOR_LOG_PATH",
    "DEFAULT_FLOWS_REPORT_DIR",
    "DEFAULT_FLOWS_SEMICON_DB_PATH",
    "DEFAULT_LOG_PATH",
    "DEFAULT_SEMICON_DB_PATH",
    "DEFAULT_SIGNALS_LOG_PATH",
    "Alerter",
    "Board",
    "ChainPosition",
    "EfinanceAdapter",
    "GroupAlreadyExistsError",
    "GroupNotFoundError",
    "Monitor",
    "NoReturn",
    "Path",
    "StockEntryNotFoundError",
    "Subcategory",
    "WatchlistStore",
    "_store",
    "argparse",
    "os",
    "sys",
]
