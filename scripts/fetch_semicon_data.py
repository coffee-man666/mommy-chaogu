"""批量抓取半导体链 106 只股票的历史量价 + 资金流数据，存入 SQLite。

用法：
    uv run python scripts/fetch_semicon_data.py
    uv run python scripts/fetch_semicon_data.py --output data/semicon_backtest.db

数据源：
- 腾讯日 K 线：web.ifzq.gtimg.cn（量价 OHLCV）
- 东财资金流：efinance adapter（主力净流入 + ratio）

存储路径：data/semicon_backtest.db（默认）
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests


def load_semicon_stocks() -> list[dict[str, str]]:
    """从 semiconductor.json 加载股票池。"""
    data = json.loads(Path("data/supply_chains/semiconductor.json").read_text())
    return [
        {"code": s["code"], "name": s.get("name", ""), "subcategory": s.get("subcategory", "")}
        for s in data["stocks"]
    ]


def get_market_prefix(code: str) -> str:
    """代码 → 沪/深市场前缀。"""
    if code.startswith("6"):
        return "sh"
    if code.startswith("0") or code.startswith("3"):
        return "sz"
    if code.startswith("8") or code.startswith("4"):
        return "bj"
    return "sh"


def fetch_tencent_daily(code: str, market: str) -> list[dict[str, Any]]:
    """腾讯日 K 线。"""
    tcode = f"{market}{code}"
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{tcode},day,2026-05-01,2026-07-10,80,qfq"}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        stock_data = data.get("data", {}).get(tcode, {})
        rows = stock_data.get("day", stock_data.get("qfqday", []))
        result = []
        for row in rows:
            result.append(
                {
                    "code": code,
                    "date": row[0],
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]) if len(row) > 5 else 0,
                }
            )
        return result
    except Exception:
        return []


def fetch_efinance_flow(code: str) -> list[dict[str, Any]]:
    """东财历史资金流。"""
    try:
        from mommy_chaogu.market_data.efinance_adapter import EfinanceAdapter

        adapter = EfinanceAdapter()
        flows = adapter.get_history_money_flow(code)
        if not flows:
            return []
        result = []
        for f in flows:
            result.append(
                {
                    "code": code,
                    "date": f.timestamp.strftime("%Y-%m-%d") if f.timestamp else "",
                    "main_net": float(f.main_net.amount) if f.main_net else 0.0,
                    "super_large_net": float(f.super_large_net.amount)
                    if f.super_large_net
                    else 0.0,
                    "large_net": float(f.large_net.amount) if f.large_net else 0.0,
                    "medium_net": float(f.medium_net.amount) if f.medium_net else 0.0,
                    "small_net": float(f.small_net.amount) if f.small_net else 0.0,
                    "ratio": float(f.main_net_ratio) if f.main_net_ratio else 0.0,
                }
            )
        return result
    except Exception:
        return []


def init_db(db_path: Path) -> sqlite3.Connection:
    """建表。"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (
            code TEXT PRIMARY KEY,
            name TEXT,
            subcategory TEXT
        );

        CREATE TABLE IF NOT EXISTS klines (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, close REAL, high REAL, low REAL, volume REAL,
            PRIMARY KEY (code, date)
        );

        CREATE TABLE IF NOT EXISTS flows (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            main_net REAL, super_large_net REAL, large_net REAL,
            medium_net REAL, small_net REAL, ratio REAL,
            PRIMARY KEY (code, date)
        );

        CREATE INDEX IF NOT EXISTS ix_klines_date ON klines(date);
        CREATE INDEX IF NOT EXISTS ix_flows_date ON flows(date);
    """)
    return conn


def run(output: str = "data/semicon_backtest.db") -> None:
    db_path = Path(output)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    stocks = load_semicon_stocks()
    print(f"半导体链: {len(stocks)} 只股票")
    print(f"存储: {db_path}")
    print()

    conn = init_db(db_path)

    # 写股票列表
    for s in stocks:
        conn.execute(
            "INSERT OR REPLACE INTO stocks (code, name, subcategory) VALUES (?, ?, ?)",
            (s["code"], s["name"], s["subcategory"]),
        )
    conn.commit()

    ok_k = 0
    ok_f = 0
    fail_k = 0
    fail_f = 0

    for i, s in enumerate(stocks):
        code = s["code"]
        name = s["name"]
        market = get_market_prefix(code)

        # K 线
        klines = fetch_tencent_daily(code, market)
        if klines:
            for k in klines:
                conn.execute(
                    "INSERT OR REPLACE INTO klines (code, date, open, close, high, low, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (k["code"], k["date"], k["open"], k["close"], k["high"], k["low"], k["volume"]),
                )
            ok_k += 1
        else:
            fail_k += 1

        time.sleep(0.15)

        # 资金流
        flows = fetch_efinance_flow(code)
        if flows:
            for f in flows:
                conn.execute(
                    "INSERT OR REPLACE INTO flows "
                    "(code, date, main_net, super_large_net, large_net, medium_net, small_net, ratio) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f["code"],
                        f["date"],
                        f["main_net"],
                        f["super_large_net"],
                        f["large_net"],
                        f["medium_net"],
                        f["small_net"],
                        f["ratio"],
                    ),
                )
            ok_f += 1
        else:
            fail_f += 1

        conn.commit()

        status_k = "✅" if klines else "❌"
        status_f = "✅" if flows else "❌"
        print(
            f"  [{i + 1:3d}/{len(stocks)}] {code} {name:8s}  "
            f"K线{status_k}{len(klines):2d}  资金流{status_f}{len(flows):2d}",
            end="\r",
        )
        time.sleep(0.2)

    print()
    print(f"\n{'=' * 50}")
    print(f"  K 线: {ok_k}/{len(stocks)} 成功, {fail_k} 失败")
    print(f"  资金流: {ok_f}/{len(stocks)} 成功, {fail_f} 失败")

    # 统计
    total_k = conn.execute("SELECT COUNT(*) FROM klines").fetchone()[0]
    total_f = conn.execute("SELECT COUNT(*) FROM flows").fetchone()[0]
    date_range_k = conn.execute("SELECT MIN(date), MAX(date) FROM klines").fetchone()
    date_range_f = conn.execute("SELECT MIN(date), MAX(date) FROM flows").fetchone()

    print(f"  K 线总行数: {total_k}  ({date_range_k[0]} → {date_range_k[1]})")
    print(f"  资金流总行数: {total_f}  ({date_range_f[0]} → {date_range_f[1]})")
    print(f"  存储: {db_path} ({db_path.stat().st_size / 1024:.0f} KB)")

    conn.close()


if __name__ == "__main__":
    out = "data/market.db"
    if len(sys.argv) > 2 and sys.argv[1] == "--output":
        out = sys.argv[2]
    run(out)
