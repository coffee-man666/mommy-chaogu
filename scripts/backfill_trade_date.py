#!/usr/bin/env python
"""backfill_trade_date.py — 回填 episodic_events 存量 NULL 的 trade_date。

历史 bug（见 docs/archive/EVALUATION-2026-07-18-backend.md P5）：
``store_extraction`` 调 ``EpisodicMemory.write()`` 不传 ``trade_date``，
导致按日期范围查询（``query(start_date, end_date)``）静默漏掉这些事件。
``write()`` 现已兜底为本地日期，本脚本负责回填存量 NULL 行。

回填口径：``timestamp``（UTC ISO8601）转换到本地时区后的日期，
与 ``write()`` 的兜底口径（``datetime.now().strftime("%Y-%m-%d")``）一致。

用法::

    uv run python scripts/backfill_trade_date.py              # 默认 db_paths.AGENT_DB
    uv run python scripts/backfill_trade_date.py --db data/agent.db
    uv run python scripts/backfill_trade_date.py --dry-run    # 只统计，不写入
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


def backfill(db_path: Path, *, dry_run: bool = False) -> int:
    """回填 trade_date 为 NULL 的行，返回受影响行数。"""
    from sqlalchemy import text

    from mommy_chaogu.db import create_sqlite_engine

    engine = create_sqlite_engine(db_path)
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, timestamp FROM episodic_events WHERE trade_date IS NULL")
        ).all()

        if dry_run:
            print(f"[dry-run] {len(rows)} 行 trade_date 为 NULL")
            return len(rows)

        updated = 0
        for row_id, ts in rows:
            try:
                local_date = datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                # timestamp 无法解析时退化为本地当前日期，保证不再留 NULL
                local_date = datetime.now().strftime("%Y-%m-%d")
            conn.execute(
                text("UPDATE episodic_events SET trade_date = :d WHERE id = :id"),
                {"d": local_date, "id": row_id},
            )
            updated += 1

    print(f"已回填 {updated} 行 trade_date（{db_path}）")
    return updated


def main() -> int:
    from mommy_chaogu.db_paths import AGENT_DB

    parser = argparse.ArgumentParser(description="回填 episodic_events 的 NULL trade_date")
    parser.add_argument("--db", default=None, help=f"数据库路径 (默认 {AGENT_DB})")
    parser.add_argument("--dry-run", action="store_true", help="只统计 NULL 行数，不写入")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else AGENT_DB
    if not db_path.exists():
        print(f"数据库不存在: {db_path}", file=sys.stderr)
        return 1

    backfill(db_path, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
