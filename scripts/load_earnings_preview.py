#!/usr/bin/env -S uv run python
"""加载券商 H1 业绩前瞻数据到 SQLite 数据库。

数据来源：中信证券《电子行业 2026 年中报业绩前瞻》（2026-07-02）
存储位置：data/earnings_preview.db

数据模型：
- 每条记录 = 一家公司在一个报告期的一个增速预测
- sector / subsector 双层分类
- growth_low / growth_high 数值化区间（%）
- growth_text 保留原文 (e.g., "+188%~+217%")
- core_driver 业绩驱动逻辑（涨价 / AI / 自主可控 / 业绩弹性 / 出货 / ...）

用法：
    uv run python scripts/load_earnings_preview.py            # 全部加载
    uv run python scripts/load_earnings_preview.py --summary  # 加载 + 打印摘要
    uv run python scripts/load_earnings_preview.py --dry-run  # 只打印不写库
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path("data/earnings_preview.db").resolve()

REPORT_DATE = "2026-07-02"
REPORT_SOURCE = "中信证券"
REPORT_PERIOD = "H1 2026"

# 数据集：(code, name, sector, subsector, growth_low, growth_high, growth_text, core_driver, highlight)
# sector: 一级板块
# subsector: 二级细分
# core_driver: 业绩驱动逻辑关键词
# highlight: 业绩亮点（驱动因素）

DATA: list[tuple[str, str, str, str, float, float, str, str, str]] = [
    # ====== 半导体-存储 ======
    (
        "603986",
        "兆易创新",
        "半导体",
        "存储",
        1070.0,
        1370.0,
        "+1070%~+1370%",
        "AI/涨价",
        "业绩大增长动力强劲，AI 算力受益",
    ),
    (
        "300223",
        "北京君正",
        "半导体",
        "存储",
        440.0,
        520.0,
        "+440%~+520%",
        "AI/涨价",
        "业绩大增长动力强劲，AI 算力受益",
    ),
    # ====== 半导体-IC设计 ======
    ("603501", "韦尔股份", "半导体", "IC设计", 30.0, 40.0, "+30%~+40%", "AI", "受益高端 CIS 需求"),
    (
        "688052",
        "纳芯微",
        "半导体",
        "IC设计",
        50.0,
        60.0,
        "+50%~+60%",
        "自主可控",
        "持续受益汽车业务趋势",
    ),
    (
        "688213",
        "思特威",
        "半导体",
        "IC设计",
        20.0,
        25.0,
        "+20%~+25%",
        "AI/智能驾驶",
        "高端 CIS 国产替代",
    ),
    (
        "301536",
        "星宸科技",
        "半导体",
        "IC设计",
        336.0,
        627.0,
        "+336%~+627%",
        "AIoT",
        "端侧 AI 需求强劲",
    ),
    ("603893", "瑞芯微", "半导体", "IC设计", 20.0, 40.0, "+20%~+40%", "AIoT", "AIoT 景气度延续"),
    (
        "688403",
        "汇成股份",
        "半导体",
        "IC设计",
        10.0,
        15.0,
        "+10%~+15%",
        "自主可控",
        "DDIC 稳健增长，2.5D 封装储备",
    ),
    # ====== 半导体-设备 ======
    (
        "002371",
        "北方华创",
        "半导体",
        "设备",
        30.0,
        50.0,
        "+30%~+50%",
        "自主可控",
        "国产半导体设备平台龙头，存储/逻辑订单高速增长",
    ),
    (
        "688012",
        "中微公司",
        "半导体",
        "设备",
        28.0,
        40.0,
        "+28%~+40%",
        "自主可控",
        "半导体设备平台龙头，存储订单高速增长",
    ),
    (
        "688120",
        "华海清科",
        "半导体",
        "设备",
        20.0,
        40.0,
        "+20%~+40%",
        "自主可控",
        "国产替代，存储订单高速增长",
    ),
    (
        "688037",
        "芯源微",
        "半导体",
        "设备",
        20.0,
        40.0,
        "+20%~+40%",
        "自主可控",
        "受益存储/逻辑/先进封装",
    ),
    (
        "688383",
        "新益昌",
        "半导体",
        "LED设备",
        430.0,
        671.0,
        "+430%~+671%",
        "业绩弹性",
        "LED 行业景气平稳向上，高端设备加速迭代",
    ),
    # ====== 半导体-材料 ======
    (
        "688519",
        "南亚新材",
        "半导体",
        "CCL材料",
        354.0,
        505.0,
        "+354%~+505%",
        "涨价",
        "CCL 涨价传导落地，高稼动率",
    ),
    (
        "688072",
        "富创精密",
        "半导体",
        "零部件",
        188.0,
        217.0,
        "+188%~+217%",
        "自主可控",
        "半导体零部件国产替代",
    ),
    (
        "002617",
        "露笑科技",
        "半导体",
        "材料",
        336.0,
        627.0,
        "+336%~+627%",
        "涨价",
        "SiC 衬底业务弹性",
    ),
    (
        "603290",
        "斯达半导",
        "半导体",
        "功率",
        -51.0,
        -2.0,
        "-51%~-2%",
        "涨价/份额",
        "受 SiC 衬底价格上涨影响，行业市占率持续提升",
    ),
    # ====== 半导体-封测 ======
    (
        "002156",
        "通富微电",
        "半导体",
        "封测",
        15.0,
        20.0,
        "+15%~+20%",
        "AI",
        "先进封装国内领先，AMD/存储需求增长",
    ),
    (
        "600584",
        "长电科技",
        "半导体",
        "封测",
        10.0,
        15.0,
        "+10%~+15%",
        "AI/涨价",
        "先进封装国内龙头，电源管理/存储需求增长",
    ),
    # ====== AI 算力 ======
    ("688256", "寒武纪", "AI算力", "训练芯片", 126.0, 183.0, "+126%~+183%", "AI", "算力高增预期强"),
    ("688041", "海光信息", "AI算力", "DCU", 83.0, 96.0, "+83%~+96%", "AI", "算力高增预期强"),
    # ====== PCB/CCL ======
    (
        "002463",
        "沪电股份",
        "PCB",
        "AI服务器PCB",
        52.0,
        74.0,
        "+52%~+74%",
        "AI",
        "AI PCB 需求景气高，产能持续释放",
    ),
    (
        "300476",
        "胜宏科技",
        "PCB",
        "AI服务器PCB",
        15.0,
        23.0,
        "+15%~+23%",
        "AI",
        "AI PCB 需求景气高，产能持续释放",
    ),
    (
        "002916",
        "深南电路",
        "PCB",
        "AI服务器PCB",
        15.0,
        50.0,
        "+15%~+50%",
        "AI",
        "AI PCB 需求景气高，产能持续释放",
    ),
    (
        "001389",
        "广合科技",
        "PCB",
        "AI服务器PCB",
        99.0,
        119.0,
        "+99%~+119%",
        "AI",
        "加速向下游涨价传导成本，比利时新设备投入",
    ),
    (
        "603920",
        "世运电路",
        "PCB",
        "汽车PCB",
        -51.0,
        -2.0,
        "-51%~-2%",
        "涨价",
        "加速向下游涨价传导成本，比利时新设备投入",
    ),
    # ====== 面板/LED ======
    (
        "000100",
        "TCL科技",
        "面板",
        "LCD",
        61.0,
        84.0,
        "+61%~+84%",
        "涨价",
        "LCD 涨价趋势高位，整体业绩有望高增",
    ),
    (
        "000725",
        "京东方A",
        "面板",
        "LCD/OLED",
        -2.0,
        10.0,
        "-2%~+10%",
        "涨价",
        "LCD 涨价趋势高位，OLED 短期承压",
    ),
    (
        "002876",
        "三孚新科",
        "面板",
        "材料",
        261.0,
        502.0,
        "+261%~+502%",
        "涨价",
        "面板产业链景气度高",
    ),
    (
        "002745",
        "木林森",
        "LED",
        "封装",
        824.0,
        1286.0,
        "+824%~+1286%",
        "业绩弹性",
        "LED 行业景气平稳向上，业绩结构改善",
    ),
    (
        "300708",
        "聚灿光电",
        "LED",
        "芯片",
        -28.0,
        -8.0,
        "-28%~-8%",
        "业绩弹性",
        "LED 行业景气平稳向上，业绩结构改善",
    ),
    # ====== 传感器 ======
    (
        "603662",
        "柯力传感",
        "传感器",
        "六维力",
        188.0,
        217.0,
        "+188%~+217%",
        "机器人/工业",
        "持续受益于人形机器人/工业传感器需求",
    ),
    (
        "688007",
        "优利德",
        "传感器",
        "测试仪器",
        20.0,
        36.0,
        "+20%~+36%",
        "业绩弹性",
        "业务结构优化，业绩结构改善",
    ),
    # ====== 机器人 ======
    (
        "002472",
        "双环传动",
        "机器人",
        "丝杠/外骨骼",
        30.0,
        40.0,
        "+30%~+40%",
        "机器人/清洁能源",
        "北美客户多领域放量，丝杠/外骨骼协同放量",
    ),
    # ====== 消费电子 ======
    (
        "002600",
        "领益智造",
        "消费电子",
        "精密结构件",
        0.0,
        10.0,
        "+0%~+10%",
        "AI/客户放量",
        "北美大客户多领域放量，AI 服务器/折叠机/PC 起量",
    ),
    (
        "002241",
        "歌尔股份",
        "消费电子",
        "声学/光学",
        0.0,
        10.0,
        "0%~+10%",
        "AI",
        "北美 AI 眼镜业务起量，AR 新品",
    ),
    (
        "002273",
        "水晶光电",
        "消费电子",
        "光学",
        10.0,
        20.0,
        "+10%~+20%",
        "客户放量",
        "北美大客户终端放量",
    ),
    (
        "300433",
        "蓝思科技",
        "消费电子",
        "玻璃/金属",
        -30.0,
        -20.0,
        "-30%~-20%",
        "客户转型",
        "客户结构转型期，业绩承压",
    ),
    (
        "603296",
        "华勤技术",
        "消费电子",
        "ODM",
        20.0,
        30.0,
        "+20%~+30%",
        "AI/客户放量",
        "AI 服务器/折叠机/PC 多领域放量",
    ),
    (
        "300115",
        "协创数据",
        "消费电子",
        "存储模组",
        10.0,
        20.0,
        "+10%~+20%",
        "涨价",
        "存储涨价向下游传导",
    ),
    (
        "300613",
        "雷神科技",
        "消费电子",
        "电脑/外设",
        133.0,
        180.0,
        "+133%~+180%",
        "AI",
        "AI PC 换机周期",
    ),
]

SCHEMA_SQL = """
-- 主表：单只股票在一个报告期的一份业绩前瞻
CREATE TABLE IF NOT EXISTS earnings_preview (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    sector          TEXT    NOT NULL,
    subsector       TEXT,
    growth_low      REAL    NOT NULL,    -- 增速下限 (%)
    growth_high     REAL    NOT NULL,    -- 增速上限 (%)
    growth_mid      REAL    NOT NULL,    -- 中位数（自动算）
    growth_text     TEXT    NOT NULL,    -- 原文，如 "+188%~+217%"
    core_driver     TEXT,                -- 涨价 / AI / 自主可控 / 业绩弹性 / 机器人 / ...
    highlight       TEXT,                -- 业绩驱动描述
    report_period   TEXT    NOT NULL,    -- 报告期（如 "H1 2026"）
    report_source   TEXT    NOT NULL,    -- 来源券商
    report_date     TEXT    NOT NULL,    -- 报告日期
    watchlist_flag  INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code, report_period, report_source)
);

CREATE INDEX IF NOT EXISTS idx_ep_code      ON earnings_preview (code);
CREATE INDEX IF NOT EXISTS idx_ep_sector    ON earnings_preview (sector);
CREATE INDEX IF NOT EXISTS idx_ep_growth    ON earnings_preview (growth_high DESC);
CREATE INDEX IF NOT EXISTS idx_ep_period    ON earnings_preview (report_period);
CREATE INDEX IF NOT EXISTS idx_ep_watchlist ON earnings_preview (watchlist_flag) WHERE watchlist_flag = 1;

-- 板块汇总视图（每次查询重算，无需持久化）
CREATE VIEW IF NOT EXISTS v_sector_summary AS
SELECT
    sector,
    COUNT(*)                                                       AS n,
    ROUND(AVG(growth_mid), 1)                                      AS avg_growth,
    MAX(growth_high)                                               AS max_growth,
    MIN(growth_low)                                                AS min_growth,
    SUM(CASE WHEN growth_high >= 200 THEN 1 ELSE 0 END)            AS n_explosive,  -- +200% 以上
    SUM(CASE WHEN growth_high >= 50 AND growth_high < 200 THEN 1 ELSE 0 END) AS n_high,  -- +50%~+200%
    SUM(CASE WHEN growth_high < 0 THEN 1 ELSE 0 END)               AS n_decline
FROM earnings_preview
GROUP BY sector
ORDER BY avg_growth DESC;
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """建库 + 建表 + 建索引 + 建视图。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def load_data(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """加载数据。返回成功条数。"""
    cursor = conn.cursor()
    inserted = 0
    skipped = 0
    updated = 0

    for code, name, sector, subsector, low, high, text, driver, highlight in DATA:
        growth_mid = (low + high) / 2

        # 自选股 flag：检查是否在 watchlist
        # 这里简化：柯力 603662 是团长 7/2 实战关注的，加 flag
        watchlist_flag = 1 if code == "603662" else 0

        try:
            if dry_run:
                print(f"  [DRY] {code} {name:　<6} {sector}/{subsector}  {text}  driver={driver}")
                inserted += 1
                continue

            cursor.execute(
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
                    code,
                    name,
                    sector,
                    subsector,
                    low,
                    high,
                    growth_mid,
                    text,
                    driver,
                    highlight,
                    REPORT_PERIOD,
                    REPORT_SOURCE,
                    REPORT_DATE,
                    watchlist_flag,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # 已存在：更新 highlight / driver / sector（最新数据覆盖）
            cursor.execute(
                """
                UPDATE earnings_preview SET
                    sector = ?, subsector = ?,
                    growth_low = ?, growth_high = ?, growth_mid = ?, growth_text = ?,
                    core_driver = ?, highlight = ?,
                    report_date = ?,
                    watchlist_flag = MAX(watchlist_flag, ?)
                WHERE code = ? AND report_period = ? AND report_source = ?
                """,
                (
                    sector,
                    subsector,
                    low,
                    high,
                    growth_mid,
                    text,
                    driver,
                    highlight,
                    REPORT_DATE,
                    watchlist_flag,
                    code,
                    REPORT_PERIOD,
                    REPORT_SOURCE,
                ),
            )
            updated += 1

    if not dry_run:
        conn.commit()

    print(
        f"\n{'[DRY-RUN] ' if dry_run else ''}已插入: {inserted}, 更新: {updated}, 跳过: {skipped}"
    )
    return inserted


def print_summary(conn: sqlite3.Connection) -> None:
    """打印摘要。"""
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print(f"📊 H1 2026 业绩前瞻数据摘要（来源: {REPORT_SOURCE}, 报告日: {REPORT_DATE}）")
    print("=" * 70)

    # 总数
    cursor.execute(
        "SELECT COUNT(*) FROM earnings_preview WHERE report_period = ?", (REPORT_PERIOD,)
    )
    total = cursor.fetchone()[0]
    print(f"\n总计: {total} 家公司")

    # 板块汇总
    print("\n板块汇总（按平均增速排序）:")
    print(
        f"{'板块':　<12} {'家数':>4} {'平均增速':>10} {'最高':>10} {'最低':>10} {'+200%':>5} {'+50~+200':>8} {'下滑':>4}"
    )
    print("-" * 70)
    cursor.execute("SELECT * FROM v_sector_summary")
    for row in cursor.fetchall():
        sector, n, avg, mx, mn, exp, high, dec = row
        print(
            f"{sector:　<12} {n:>4} {avg:>+9.1f}% {mx:>+9.1f}% {mn:>+9.1f}% {exp:>5} {high:>8} {dec:>4}"
        )

    # TOP 10 业绩弹性
    print("\n💥 TOP 10 业绩弹性（按增速上限排序）:")
    cursor.execute(
        """
        SELECT code, name, sector, subsector, growth_text, core_driver, highlight
        FROM earnings_preview
        WHERE report_period = ? AND growth_high >= 100
        ORDER BY growth_high DESC
        LIMIT 10
        """,
        (REPORT_PERIOD,),
    )
    for row in cursor.fetchall():
        code, name, sector, sub, gt, drv, _hl = row
        watch = " ⭐" if code == "603662" else ""
        print(f"  {gt:>14}  {code} {name:　<6} {sector}/{sub} | {drv}{watch}")

    # 下滑公司
    print("\n🔻 业绩下滑 / 承压:")
    cursor.execute(
        """
        SELECT code, name, sector, growth_text, core_driver
        FROM earnings_preview
        WHERE report_period = ? AND growth_high < 0
        ORDER BY growth_low ASC
        """,
        (REPORT_PERIOD,),
    )
    for row in cursor.fetchall():
        code, name, sector, gt, drv = row
        print(f"  {gt:>14}  {code} {name:　<6} {sector} | {drv}")


def main() -> None:
    parser = argparse.ArgumentParser(description="加载券商业绩前瞻到 SQLite")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    parser.add_argument("--summary", action="store_true", help="加载后打印摘要")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="数据库路径")
    args = parser.parse_args()

    print(f"📂 数据库: {args.db}")
    print(f"📋 数据源: {REPORT_SOURCE} {REPORT_DATE} ({REPORT_PERIOD})")
    print(f"📦 数据量: {len(DATA)} 家公司\n")

    if not args.dry_run:
        conn = init_db(args.db)
        load_data(conn)
        if args.summary:
            print_summary(conn)
        conn.close()
    else:
        print("[DRY-RUN 模式] 不写库，仅预览：\n")
        # 直接打印 DATA，不走 DB
        from collections import defaultdict

        agg: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for row in DATA:
            agg[row[2]].append((row[4], row[5]))  # (low, high)

        print(
            f"{'板块':　<14} {'家数':>4} {'平均增速':>10} {'最高':>10} {'+200%':>5} {'+50~+200':>8} {'下滑':>4}"
        )
        print("-" * 70)
        for sector, vals in sorted(
            agg.items(),
            key=lambda x: -sum((a + b) / 2 for a, b in x[1]) / len(x[1]),
        ):
            n = len(vals)
            avg = sum((a + b) / 2 for a, b in vals) / n
            mx = max(b for _, b in vals)
            explosive = sum(1 for a, b in vals if b >= 200)
            high = sum(1 for a, b in vals if 50 <= b < 200)
            decline = sum(1 for a, b in vals if b < 0)
            print(
                f"{sector:　<14} {n:>4} {avg:>+9.1f}% {mx:>+9.1f}% {explosive:>5} {high:>8} {decline:>4}"
            )

        print()
        print("=== 全部记录预览 ===")
        for row in DATA:
            code, name, sector, sub, _low, _high, text, drv, _hl = row
            watch = " ⭐" if code == "603662" else ""
            print(f"  [{text:>14}] {code} {name:　<6} {sector}/{sub} | {drv}{watch}")
        print(f"\n总计: {len(DATA)} 家公司")


if __name__ == "__main__":
    main()
