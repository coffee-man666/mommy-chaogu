"""数据库布局迁移脚本：旧布局 → 新布局。

旧布局：
    data/watchlist.db → 所有表混在一起
    data/semicon.db → 半导体
    data/earnings_preview.db → 业绩前瞻
    data/earnings_actual.db → 业绩实际值
    data/semicon_backtest.db → 回测数据

新布局：
    data/market.db → 行情缓存 + 历史 K 线 + 资金流
    data/portfolio.db → 自选股 + 持仓
    data/agent.db → 记忆系统
    data/reference.db → 半导体 + 业绩

用法：
    uv run python scripts/migrate_db_layout.py           # 迁移
    uv run python scripts/migrate_db_layout.py --check    # 只检查不迁移
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from mommy_chaogu.db_paths import (
    AGENT_DB,
    LEGACY_BACKTEST_DB,
    LEGACY_EARNINGS_ACTUAL_DB,
    LEGACY_EARNINGS_PREVIEW_DB,
    LEGACY_SEMICON_DB,
    LEGACY_WATCHLIST_DB,
    MARKET_DB,
    PORTFOLIO_DB,
    REFERENCE_DB,
)

# 表 → 目标库的映射
CACHE_TABLES = [
    "quote_cache",
    "bar_cache",
    "money_flow_cache",
    "today_money_flow_cache",
    "market_snapshot_cache",
]

PORTFOLIO_TABLES = [
    "groups",
    "stock_entries",
    "positions",
    "position_adjustments",
    "custom_alerts",
]

AGENT_TABLES = [
    "agent_memory",
    "episodic_events",
    "predictions",
    "semantic_knowledge",
    "episodic_embeddings",
]

REFERENCE_TABLES_SEMICON = ["semicon_stocks"]
REFERENCE_TABLES_EARNINGS = [
    "earnings_preview",
    "earnings_actuals",
    "earnings_scores",
    "earnings_calendars",
]

BACKTEST_TABLES = ["klines", "flows", "stocks"]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    result = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return result is not None


def table_row_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def copy_table(src_conn: sqlite3.Connection, dst_db: Path, table: str) -> int:
    """把表从 src_conn 复制到 dst_db。返回行数。"""
    if not table_exists(src_conn, table):
        return 0

    rows = table_row_count(src_conn, table)
    if rows == 0:
        return 0

    # 用 ATTACH + INSERT 把数据搬过去
    dst_db.parent.mkdir(parents=True, exist_ok=True)

    # 先确保目标库有这个表（通过 ATTACH + CREATE TABLE ... AS SELECT）
    src_conn.execute(f"ATTACH DATABASE '{dst_db}' AS dst")

    # 检查目标是否已有数据
    try:
        dst_count = src_conn.execute(f"SELECT COUNT(*) FROM dst.{table}").fetchone()[0]
    except sqlite3.OperationalError:
        dst_count = -1  # 表不存在

    if dst_count > 0:
        print(f"  ⏭️  {table}: 目标已有 {dst_count} 行，跳过")
        src_conn.execute("DETACH DATABASE dst")
        return 0

    # 复制表结构和数据
    if dst_count == -1:
        # 表不存在，直接 CREATE TABLE AS SELECT
        src_conn.execute(f"CREATE TABLE dst.{table} AS SELECT * FROM main.{table}")
    else:
        # 表存在但为空，INSERT
        src_conn.execute(f"INSERT INTO dst.{table} SELECT * FROM main.{table}")

    src_conn.execute("DETACH DATABASE dst")
    return rows


def run(check_only: bool = False) -> None:
    print("=" * 60)
    print("  📦 数据库布局迁移")
    print("=" * 60)

    needs_migration = False

    # ---------- 1. watchlist.db → market.db + portfolio.db + agent.db ----------
    if LEGACY_WATCHLIST_DB.exists():
        print(f"\n📂 {LEGACY_WATCHLIST_DB}")

        conn = sqlite3.connect(str(LEGACY_WATCHLIST_DB))

        for table in CACHE_TABLES:
            n = table_row_count(conn, table)
            if n > 0:
                print(f"  📊 {table}: {n} 行 → {MARKET_DB.name}")
                needs_migration = True

        for table in PORTFOLIO_TABLES:
            n = table_row_count(conn, table)
            if n > 0:
                print(f"  📊 {table}: {n} 行 → {PORTFOLIO_DB.name}")
                needs_migration = True

        for table in AGENT_TABLES:
            n = table_row_count(conn, table)
            if n > 0:
                print(f"  📊 {table}: {n} 行 → {AGENT_DB.name}")
                needs_migration = True

        if not check_only:
            for table in CACHE_TABLES:
                copy_table(conn, MARKET_DB, table)
            for table in PORTFOLIO_TABLES:
                copy_table(conn, PORTFOLIO_DB, table)
            for table in AGENT_TABLES:
                copy_table(conn, AGENT_DB, table)

        conn.close()

        if not check_only:
            backup = LEGACY_WATCHLIST_DB.with_suffix(".db.bak")
            LEGACY_WATCHLIST_DB.rename(backup)
            print(f"  ✅ {LEGACY_WATCHLIST_DB.name} → {backup.name}")

    # ---------- 2. semicon.db → reference.db ----------
    if LEGACY_SEMICON_DB.exists() and LEGACY_SEMICON_DB.stat().st_size > 0:
        print(f"\n📂 {LEGACY_SEMICON_DB}")
        conn = sqlite3.connect(str(LEGACY_SEMICON_DB))
        for table in REFERENCE_TABLES_SEMICON:
            n = table_row_count(conn, table)
            if n > 0:
                print(f"  📊 {table}: {n} 行 → {REFERENCE_DB.name}")
                needs_migration = True
                if not check_only:
                    copy_table(conn, REFERENCE_DB, table)
        conn.close()
        if not check_only:
            backup = LEGACY_SEMICON_DB.with_suffix(".db.bak")
            LEGACY_SEMICON_DB.rename(backup)
            print(f"  ✅ {LEGACY_SEMICON_DB.name} → {backup.name}")

    # ---------- 3. earnings dbs → reference.db ----------
    for db_file in [LEGACY_EARNINGS_ACTUAL_DB, LEGACY_EARNINGS_PREVIEW_DB]:
        if db_file.exists() and db_file.stat().st_size > 0:
            print(f"\n📂 {db_file}")
            conn = sqlite3.connect(str(db_file))
            for table in REFERENCE_TABLES_EARNINGS:
                n = table_row_count(conn, table)
                if n > 0:
                    print(f"  📊 {table}: {n} 行 → {REFERENCE_DB.name}")
                    needs_migration = True
                    if not check_only:
                        copy_table(conn, REFERENCE_DB, table)
            conn.close()

    # ---------- 4. semicon_backtest.db → market.db ----------
    if LEGACY_BACKTEST_DB.exists() and LEGACY_BACKTEST_DB.stat().st_size > 0:
        print(f"\n📂 {LEGACY_BACKTEST_DB}")
        conn = sqlite3.connect(str(LEGACY_BACKTEST_DB))
        for table in BACKTEST_TABLES:
            n = table_row_count(conn, table)
            if n > 0:
                target = MARKET_DB if table in ("klines", "flows") else REFERENCE_DB
                print(f"  📊 {table}: {n} 行 → {target.name}")
                needs_migration = True
                if not check_only:
                    copy_table(conn, target, table)
        conn.close()

    # ---------- 总结 ----------
    if not needs_migration:
        print("\n✅ 无需迁移 — 没有发现需要迁移的数据")
    elif check_only:
        print("\n🔍 检查完成 — 以上表需要迁移（用 --check=false 执行迁移）")
    else:
        print("\n✅ 迁移完成")
        for _name, db in [
            ("market", MARKET_DB),
            ("portfolio", PORTFOLIO_DB),
            ("agent", AGENT_DB),
            ("reference", REFERENCE_DB),
        ]:
            if db.exists():
                print(f"  {db.name}: {db.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    check = "--check" in sys.argv
    run(check_only=check)
