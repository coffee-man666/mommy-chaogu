#!/usr/bin/env -S uv run python
"""从 earnings_preview.json 构建 earnings_preview.db。

JSON 是唯一数据源（single source of truth），本脚本负责把 JSON 种子同步到 SQLite。

用法：
    uv run python scripts/load_earnings_preview.py            # 构建 DB
    uv run python scripts/load_earnings_preview.py --summary  # 构建 + 打印摘要
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = PROJECT_ROOT / "data" / "earnings_preview.json"
DB_PATH = PROJECT_ROOT / "data" / "earnings_preview.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS earnings_preview (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    sector          TEXT    NOT NULL,
    subsector       TEXT,
    growth_low      REAL    NOT NULL,
    growth_high     REAL    NOT NULL,
    growth_mid      REAL    NOT NULL,
    growth_text     TEXT    NOT NULL,
    core_driver     TEXT,
    highlight       TEXT,
    report_period   TEXT    NOT NULL,
    report_source   TEXT    NOT NULL,
    report_date     TEXT    NOT NULL,
    watchlist_flag  INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, report_period, report_source)
);

CREATE INDEX IF NOT EXISTS idx_ep_code      ON earnings_preview (code);
CREATE INDEX IF NOT EXISTS idx_ep_sector    ON earnings_preview (sector);
CREATE INDEX IF NOT EXISTS idx_ep_growth    ON earnings_preview (growth_high DESC);
CREATE INDEX IF NOT EXISTS idx_ep_period    ON earnings_preview (report_period);
CREATE INDEX IF NOT EXISTS idx_ep_watchlist ON earnings_preview (watchlist_flag) WHERE watchlist_flag = 1;

CREATE VIEW IF NOT EXISTS v_sector_summary AS
SELECT
    sector,
    COUNT(*)                                                       AS n,
    ROUND(AVG(growth_mid), 1)                                      AS avg_growth,
    MAX(growth_high)                                               AS max_growth,
    MIN(growth_low)                                                AS min_growth,
    SUM(CASE WHEN growth_high >= 200 THEN 1 ELSE 0 END)            AS n_explosive,
    SUM(CASE WHEN growth_high >= 50 AND growth_high < 200 THEN 1 ELSE 0 END) AS n_high,
    SUM(CASE WHEN growth_high < 0 THEN 1 ELSE 0 END)               AS n_decline
FROM earnings_preview
GROUP BY sector
ORDER BY avg_growth DESC;
"""


def load_json() -> list[dict]:
    """加载 JSON 种子文件。"""
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    stocks = data.get("stocks", [])
    print(f"📂 JSON: {JSON_PATH.name}")
    print(
        f"📋 来源: {meta.get('source', '?')} {meta.get('report_date', '?')} ({meta.get('report_period', '?')})"
    )
    print(f"📦 数据量: {len(stocks)} 家公司\n")
    return stocks


def build_db(stocks: list[dict], db_path: Path) -> int:
    """从 stocks 列表构建 SQLite DB（先清空再写入）。返回插入条数。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.execute("DELETE FROM earnings_preview")

    inserted = 0
    for s in stocks:
        growth_mid = (s["growth_low"] + s["growth_high"]) / 2
        conn.execute(
            """
            INSERT INTO earnings_preview (
                code, name, sector, subsector,
                growth_low, growth_high, growth_mid, growth_text,
                core_driver, highlight,
                report_period, report_source, report_date,
                watchlist_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s["code"],
                s["name"],
                s["sector"],
                s.get("subsector", ""),
                s["growth_low"],
                s["growth_high"],
                growth_mid,
                s["growth_text"],
                s.get("core_driver", ""),
                s.get("highlight", ""),
                s.get("report_period", "H1 2026"),
                s.get("report_source", "中信证券"),
                s.get("report_date", "2026-07-02"),
                s.get("watchlist_flag", 0),
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def print_summary(db_path: Path) -> None:
    """打印 DB 摘要。"""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    print("=" * 70)
    print("📊 earnings_preview.db 摘要")
    print("=" * 70)

    cur.execute("SELECT COUNT(*) FROM earnings_preview")
    print(f"\n总计: {cur.fetchone()[0]} 家公司")

    print("\n板块汇总:")
    cur.execute("SELECT * FROM v_sector_summary")
    print(
        f"{'板块':<14} {'家数':>4} {'平均增速':>10} {'最高':>10} {'最低':>10} {'+200%':>5} {'+50~200':>8} {'下滑':>4}"
    )
    print("-" * 70)
    for row in cur.fetchall():
        sector, n, avg, mx, mn, exp, high, dec = row
        print(
            f"{sector:<14} {n:>4} {avg:>+9.1f}% {mx:>+9.1f}% {mn:>+9.1f}% {exp:>5} {high:>8} {dec:>4}"
        )

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="从 JSON 构建 earnings_preview.db")
    parser.add_argument("--summary", action="store_true", help="构建后打印摘要")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="数据库路径")
    args = parser.parse_args()

    stocks = load_json()
    n = build_db(stocks, args.db)
    print(f"✅ 插入 {n} 条 → {args.db}")

    if args.summary:
        print_summary(args.db)


if __name__ == "__main__":
    main()
