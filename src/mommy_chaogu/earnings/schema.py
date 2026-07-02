"""earnings 模块 — SQL Schema。

3 张表：
- earnings_actual：实际披露的业绩
- earnings_score：actual vs predicted 比对结果（由 Service 计算）
- earnings_calendar：披露日历

设计原则：
- Decimal 字段用 TEXT 存储（避免 SQLite 浮点精度问题）
- 所有时间戳用 ISO-8601 字符串
- UNIQUE 约束支持 upsert
- 索引覆盖常见查询路径
"""
from __future__ import annotations

SCHEMA_SQL = """
-- 实际披露业绩
CREATE TABLE IF NOT EXISTS earnings_actual (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    period          TEXT    NOT NULL,                  -- "H1 2026" / "Q3 2026" / "FY 2026"
    actual_value    TEXT    NOT NULL,                  -- 净利润（元，Decimal 字符串）
    growth_pct      TEXT,                              -- 同比增速 %（Decimal 字符串）
    disclosure_date TEXT    NOT NULL,                  -- ISO 日期
    source          TEXT    NOT NULL,                  -- forecast/express/report/guidance
    note            TEXT,
    fetched_at      TEXT,                              -- ISO datetime
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, period, source)
);

CREATE INDEX IF NOT EXISTS idx_ea_code         ON earnings_actual (code);
CREATE INDEX IF NOT EXISTS idx_ea_period       ON earnings_actual (period);
CREATE INDEX IF NOT EXISTS idx_ea_disclosure   ON earnings_actual (disclosure_date);
CREATE INDEX IF NOT EXISTS idx_ea_source       ON earnings_actual (source);

-- 比对结果（actual vs predicted）
CREATE TABLE IF NOT EXISTS earnings_score (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    period          TEXT    NOT NULL,
    predicted_low   TEXT    NOT NULL,
    predicted_high  TEXT    NOT NULL,
    predicted_mid   TEXT    NOT NULL,
    actual_value    TEXT    NOT NULL,
    actual_growth   TEXT,
    gap_to_mid      TEXT,
    gap_to_high     TEXT,
    verdict         TEXT    NOT NULL,                  -- SUPER_BEAT/BEAT/MEET/MISS/DEEP_MISS/UNKNOWN
    confidence      TEXT    NOT NULL,                  -- 0~1 (Decimal)
    scored_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, period)
);

CREATE INDEX IF NOT EXISTS idx_es_code         ON earnings_score (code);
CREATE INDEX IF NOT EXISTS idx_es_period       ON earnings_score (period);
CREATE INDEX IF NOT EXISTS idx_es_verdict      ON earnings_score (verdict);

-- 披露日历
CREATE TABLE IF NOT EXISTS earnings_calendar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    period          TEXT    NOT NULL,
    disclosure_date TEXT    NOT NULL,
    is_estimated    INTEGER NOT NULL DEFAULT 0,
    source          TEXT    NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, period)
);

CREATE INDEX IF NOT EXISTS idx_ec_code         ON earnings_calendar (code);
CREATE INDEX IF NOT EXISTS idx_ec_date         ON earnings_calendar (disclosure_date);
CREATE INDEX IF NOT EXISTS idx_ec_period       ON earnings_calendar (period);
CREATE INDEX IF NOT EXISTS idx_ec_estimated    ON earnings_calendar (is_estimated);

-- 视图：最近 7 天披露 + 比对结果
CREATE VIEW IF NOT EXISTS v_recent_disclosures AS
SELECT
    s.code,
    s.name,
    s.period,
    a.disclosure_date,
    s.predicted_low,
    s.predicted_high,
    s.actual_growth,
    s.verdict,
    s.confidence
FROM earnings_score s
LEFT JOIN earnings_actual a
    ON a.code = s.code AND a.period = s.period
WHERE a.disclosure_date >= date('now', '-7 days')
ORDER BY a.disclosure_date DESC;
"""
