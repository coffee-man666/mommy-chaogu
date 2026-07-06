#!/usr/bin/env python3
"""Rebuild earnings_preview.db + watchlist groups 4+ from earnings_preview.json.

JSON 是唯一数据源，本脚本把 JSON 同步到 SQLite + watchlist。

Usage:
    uv run python scripts/rebuild_earnings_preview.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = PROJECT_ROOT / "data" / "earnings_preview.json"
EP_DB = PROJECT_ROOT / "data" / "earnings_preview.db"
WL_DB = PROJECT_ROOT / "data" / "watchlist.db"


def load_json() -> list[dict]:
    """加载 JSON 种子文件。"""
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    return data.get("stocks", [])


def rebuild_earnings_preview(stocks: list[dict]) -> int:
    """清空 + 重建 earnings_preview 表。"""
    conn = sqlite3.connect(EP_DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM earnings_preview")

    n = 0
    for s in stocks:
        growth_mid = (s["growth_low"] + s["growth_high"]) / 2
        cur.execute(
            """INSERT INTO earnings_preview
               (code, name, sector, subsector, growth_low, growth_high,
                growth_mid, growth_text, core_driver, highlight,
                report_period, report_source, report_date, watchlist_flag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        n += 1

    conn.commit()
    conn.close()
    return n


def rebuild_watchlist(stocks: list[dict]) -> tuple[int, int]:
    """清空 groups 4+ 并从 stocks 的 sector 分组重建。"""
    # 按 sector 分组
    groups: dict[str, list[dict]] = {}
    for s in stocks:
        groups.setdefault(s["sector"], []).append(s)

    conn = sqlite3.connect(WL_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.execute("DELETE FROM stock_entries WHERE group_id >= 4")
    cur.execute("DELETE FROM groups WHERE id >= 4")
    cur.execute("DELETE FROM sqlite_sequence WHERE name = 'groups'")
    cur.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('groups', 3)")
    cur.execute("DELETE FROM sqlite_sequence WHERE name = 'stock_entries'")
    cur.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('stock_entries', 0)")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = json.loads(JSON_PATH.read_text(encoding="utf-8")).get("meta", {})
    source = meta.get("source", "中信证券")
    report_date = meta.get("report_date", "2026-07-02")
    group_desc = f"H1 2026 业绩前瞻（来源: {source} {report_date}）"

    n_groups = 0
    n_entries = 0
    next_id = 4

    for sector, sector_stocks in sorted(groups.items()):
        gid = next_id
        next_id += 1
        cur.execute(
            "INSERT INTO groups (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (gid, sector, group_desc, now),
        )
        n_groups += 1
        for s in sector_stocks:
            cur.execute(
                """INSERT INTO stock_entries (code, name, group_id, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (s["code"], s["name"], gid, None, now),
            )
            n_entries += 1

    conn.commit()
    conn.close()
    return n_groups, n_entries


def main() -> None:
    print("═" * 60)
    print("Rebuild from earnings_preview.json")
    print(f"Source: {JSON_PATH.name}")
    print("═" * 60)

    stocks = load_json()
    print(f"📦 JSON: {len(stocks)} stocks")

    n_ep = rebuild_earnings_preview(stocks)
    print(f"✅ earnings_preview.db: {n_ep} rows")

    n_grp, n_ent = rebuild_watchlist(stocks)
    print(f"✅ watchlist: {n_grp} groups, {n_ent} entries")

    # 验证
    conn = sqlite3.connect(EP_DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM earnings_preview")
    print(f"\n验证: earnings_preview count = {cur.fetchone()[0]}")
    cur.execute(
        "SELECT sector, COUNT(*) FROM earnings_preview GROUP BY sector ORDER BY COUNT(*) DESC"
    )
    for sector, cnt in cur.fetchall():
        print(f"  {sector}: {cnt}")
    conn.close()


if __name__ == "__main__":
    main()
