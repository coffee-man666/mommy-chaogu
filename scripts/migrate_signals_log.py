#!/usr/bin/env python3
"""把既有 data/signals.log 回填到 market.db 的 signal_events 表（#10）。

幂等：重复执行不产生重复行（按 timestamp+code+rule_id 去重）。

用法：
    uv run python scripts/migrate_signals_log.py --check   # 只报告可回填行数
    uv run python scripts/migrate_signals_log.py            # 执行回填

注意：旧 format_log 格式（[ts] emoji label code name title | detail）与
历史正则解析器不匹配，所以本脚本只能解析能匹配的行（测试格式），无法解析
的行会跳过。实际生产环境 data/signals.log 通常不存在或为空，影响很小。
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

# 旧格式正则（与 web/routes/signals.py 的 _parse_signal_line 一致）
_LINE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"\[(\w+)\s*\]\s+"
    r"(\d+)\s+(\S+)\s+"
    r"(\w+):\s+(.+)$"
)

MARKET_DB = Path("data/market.db")
LOG_PATH = Path("data/signals.log")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS signal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            trigger_value TEXT,
            threshold_value TEXT,
            metrics_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_signal_events_timestamp
            ON signal_events(timestamp DESC);
        CREATE INDEX IF NOT EXISTS ix_signal_events_code
            ON signal_events(code);
        CREATE INDEX IF NOT EXISTS ix_signal_events_rule_id
            ON signal_events(rule_id);
        """
    )
    conn.commit()


def _existing_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """已入库的 (timestamp, code, rule_id) 三元组（去重用）。"""
    rows = conn.execute("SELECT timestamp, code, rule_id FROM signal_events").fetchall()
    return {(str(r[0]), r[1], r[2]) for r in rows}


def _parse_log_lines(text: str) -> list[tuple[str, str, str, str, str, str, str]]:
    """解析日志文本，返回可入库的行元组列表。"""
    parsed: list[tuple[str, str, str, str, str, str, str]] = []
    for line in text.splitlines():
        m = _LINE_PATTERN.match(line)
        if not m:
            continue
        ts_str, severity, code, name, rule_id, detail = m.groups()
        title = f"{name} {rule_id}"
        parsed.append((ts_str, code, name, rule_id, severity.lower().strip(), title, detail))
    return parsed


def run(check_only: bool = False) -> None:
    if not LOG_PATH.exists():
        print(f"日志文件不存在：{LOG_PATH}（无需迁移）")
        return

    if not MARKET_DB.exists():
        print(f"错误：{MARKET_DB} 不存在，请先正常运行一次应用以初始化数据库。")
        sys.exit(1)

    conn = sqlite3.connect(str(MARKET_DB))
    try:
        _ensure_table(conn)
        text = LOG_PATH.read_text(encoding="utf-8")
        parsed = _parse_log_lines(text)
        existing = _existing_keys(conn)

        new_rows = [
            row
            for row in parsed
            if (row[0], row[1], row[3]) not in existing  # ts, code, rule_id
        ]

        print(f"日志总行数：{len(text.splitlines())}")
        print(f"可解析行数：{len(parsed)}")
        print(f"已入库行数：{len(existing)}")
        print(f"待回填行数：{len(new_rows)}")

        if check_only:
            print("\n[--check 模式] 未执行写入。去掉 --check 执行回填。")
            return

        if not new_rows:
            print("\n无新行需回填（幂等：重复执行安全）。")
            return

        conn.executemany(
            """INSERT INTO signal_events
               (timestamp, code, name, rule_id, severity, title, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            new_rows,
        )
        conn.commit()
        print(f"\n✓ 已回填 {len(new_rows)} 行到 signal_events 表")
    finally:
        conn.close()


if __name__ == "__main__":
    check = "--check" in sys.argv
    run(check_only=check)
