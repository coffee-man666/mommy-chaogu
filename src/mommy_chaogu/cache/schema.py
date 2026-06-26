"""缓存表 schema。

所有表都带 fetched_at 时间戳，标明"我们什么时候抓的"。
quote_cache 还带 quote_ts，记录"数据自身的时间"（行情接口给的时间戳）。
"""
from __future__ import annotations

SCHEMA_SQL = """
-- 自选股实时报价（每个 code 一份最新，可覆盖）
CREATE TABLE IF NOT EXISTS quote_cache (
    code TEXT PRIMARY KEY,
    quote_json TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    quote_ts TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_quote_cache_fetched_at
    ON quote_cache(fetched_at);

-- K 线（每天一条，永久保留）
CREATE TABLE IF NOT EXISTS bar_cache (
    code TEXT NOT NULL,
    interval TEXT NOT NULL,
    adj_type TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    bar_json TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (code, interval, adj_type, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_bar_cache_code
    ON bar_cache(code, interval, adj_type);

-- 历史资金流（每天一条，永久保留）
CREATE TABLE IF NOT EXISTS money_flow_cache (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    flow_json TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (code, trade_date)
);

-- 当日资金流最新（每个 code 一份）
CREATE TABLE IF NOT EXISTS today_money_flow_cache (
    code TEXT PRIMARY KEY,
    flows_json TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL
);

-- 全市场快照（保留多份历史，便于看历史涨跌榜变化）
CREATE TABLE IF NOT EXISTS market_snapshot_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TIMESTAMP NOT NULL,
    quote_ts TIMESTAMP,
    quotes_json TEXT NOT NULL,
    n_codes INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_market_snapshot_fetched_at
    ON market_snapshot_cache(fetched_at DESC);
"""
