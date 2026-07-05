#!/usr/bin/env python3
"""Rebuild earnings_preview.db and watchlist groups 4+ from CITIC H1 2026 report.

Usage:
    uv run python scripts/rebuild_earnings_preview.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EP_DB = PROJECT_ROOT / "data" / "earnings_preview.db"
WL_DB = PROJECT_ROOT / "data" / "watchlist.db"

REPORT_PERIOD = "H1 2026"
REPORT_SOURCE = "中信证券"
REPORT_DATE = "2026-07-02"

# ── Data: (code, name, sector, subsector, growth_low, growth_high, core_driver, highlight)
COMPANIES: list[tuple[str, str, str, str | None, float, float, str, str]] = [
    # 半导体-存储 (3)
    ("603986", "兆易创新", "半导体-存储", None, 1070, 1370, "AI/涨价", "存储价格涨势强劲"),
    ("300223", "北京君正", "半导体-存储", None, 440, 520, "AI/涨价", "车规存储涨价"),
    ("688110", "东芯股份", "半导体-存储", None, 30, 9999, "涨价", "利润逐步释放"),

    # 半导体-AI算力 (2)
    ("688256", "寒武纪", "半导体-AI算力", None, 126, 183, "AI", "算力需求扩张"),
    ("688041", "海光信息", "半导体-AI算力", None, 83, 96, "AI", "算力需求扩张"),

    # 半导体-IC设计 (11)
    ("301536", "星宸科技", "半导体-IC设计", None, 336, 627, "AIoT", "存储周期+AIoT"),
    ("300613", "富瀚微", "半导体-IC设计", None, 133, 180, "AI", "存储周期产品超预期"),
    ("603893", "瑞芯微", "半导体-IC设计", None, 20, 40, "AIoT", "AIoT景气延续"),
    ("688018", "乐鑫科技", "半导体-IC设计", None, 10, 20, "AIoT", "新品迭代放量"),
    ("688049", "炬芯科技", "半导体-IC设计", None, 17, 28, "AIoT", "多品类推进"),
    ("688332", "中科蓝讯", "半导体-IC设计", None, 0, 10, "AIoT", "白牌需求趋佳"),
    ("688252", "天德钰", "半导体-IC设计", None, -6, 7, "DDIC", "DDIC新品迭代"),
    ("688593", "新相徽", "半导体-IC设计", None, 18, 41, "OLED", "OLED+光通信+算力"),
    ("300672", "国科微", "半导体-IC设计", None, 0, 0, "合封存储", "合封存储利润弹性"),
    ("603501", "韦尔股份", "半导体-IC设计", None, -5, 1, "CIS", "手机承压汽车向好"),
    ("688213", "思特威", "半导体-IC设计", None, 20, 25, "CIS", "新机客户拓展"),

    # 半导体-模拟 (3)
    ("300661", "圣邦股份", "半导体-模拟", None, 30, 40, "模拟", "光模块+泛工业"),
    ("688536", "思瑞浦", "半导体-模拟", None, 50, 9999, "模拟", "光模块+泛工业"),
    ("688052", "纳芯微", "半导体-模拟", None, 50, 60, "模拟", "泛工业景气"),

    # 半导体-功率 (4)
    ("605111", "新洁能", "半导体-功率", None, 25, 35, "功率/涨价", "中低压涨价"),
    ("300373", "扬杰科技", "半导体-功率", None, 23, 28, "功率/涨价", "中低压涨价"),
    ("688396", "华润微", "半导体-功率", None, 15, 29, "功率/涨价", "二期涨价+顺价"),
    ("603290", "斯达半导", "半导体-功率", None, -51, -2, "功率/份额", "涨价预期"),

    # 半导体-设备 (12)
    ("002371", "北方华创", "半导体-设备", None, 30, 50, "自主可控", "设备龙头订单高增"),
    ("688012", "中微公司", "半导体-设备", None, 28, 40, "自主可控", "刻蚀龙头"),
    ("688072", "拓荆科技", "半导体-设备", None, 30, 60, "自主可控", "薄膜沉积国产龙头"),
    ("688120", "华海清科", "半导体-设备", None, 20, 40, "自主可控", "CMP+减薄"),
    ("688037", "芯源微", "半导体-设备", None, 26, 40, "自主可控", "涂胶显影"),
    ("688082", "盛美上海", "半导体-设备", None, 20, 30, "自主可控", "湿法设备升级"),
    ("688200", "华峰测控", "半导体-设备", None, 30, 60, "自主可控", "ATE测试龙头"),
    ("688372", "伟测科技", "半导体-设备", None, 40, 50, "自主可控", "第三方测试"),
    ("688652", "京仪装备", "半导体-设备", None, 25, 40, "自主可控", "温控设备"),
    ("688409", "富创精密", "半导体-设备", None, 25, 40, "自主可控", "零部件龙头"),
    ("301611", "珂玛科技", "半导体-设备", None, 10, 30, "自主可控", "陶瓷件需求"),
    ("688469", "芯联集成", "半导体-设备", None, 14, 25, "制造", "低压涨价+硅光"),

    # 半导体-封测 (5)
    ("600584", "长电科技", "半导体-封测", None, 10, 15, "AI/涨价", "先进封装龙头"),
    ("002156", "通富微电", "半导体-封测", None, 15, 20, "AI", "AMD+存储需求"),
    ("688362", "甬矽电子", "半导体-封测", None, 18, 33, "AI", "2.5D封装"),
    ("688403", "汇成股份", "半导体-封测", None, 10, 15, "自主可控", "封测增长"),
    ("002617", "露笑科技", "半导体-封测", None, 336, 627, "涨价", "功率涨价"),

    # 半导体-射频 (1)
    ("688807", "优讯股份", "半导体-射频", None, 20, 36, "射频", "高速产品导入"),

    # PCB (7)
    ("002463", "沪电股份", "PCB", None, 52, 74, "AI", "AI PCB高景气"),
    ("300476", "胜宏科技", "PCB", None, 15, 23, "AI", "AI PCB"),
    ("002916", "深南电路", "PCB", None, 15, 50, "AI", "AI PCB+载板"),
    ("001389", "广合科技", "PCB", None, 99, 119, "AI", "CPU/AI PCB"),
    ("603920", "世运电路", "PCB", None, -51, -2, "AI", "向高价值领域布局"),
    ("002913", "奥士康", "PCB", None, -64, 161, "AI", "AI及汽车服务器"),
    ("301200", "大族数控", "PCB", None, 139, 173, "AI", "PCB扩产景气"),

    # CCL (3)
    ("600183", "生益科技", "CCL", None, 62, 85, "涨价", "CCL涨价落地"),
    ("688519", "南亚新材", "CCL", None, 354, 505, "涨价", "CCL涨价"),
    ("002436", "兴森科技", "CCL", None, 157, 671, "涨价", "载板订单"),

    # 面板 (3)
    ("000100", "TCL科技", "面板", None, 61, 84, "涨价", "LCD量价齐升"),
    ("000725", "京东方A", "面板", None, -2, 10, "涨价", "LCD+OLED"),
    ("002876", "三利谱", "面板", None, 261, 502, "涨价", "面板景气"),

    # LED (3)
    ("002745", "木林森", "LED", None, 824, 1286, "业绩弹性", "LED景气"),
    ("300708", "聚灿光电", "LED", None, -25, -8, "业绩弹性", "LED整体向好"),
    ("688383", "新益昌", "LED", None, 430, 671, "业绩弹性", "LED设备加速"),

    # 被动元件 (4)
    ("300408", "三环集团", "被动元件", None, 28, 42, "涨价", "MLCC+SOFC"),
    ("000636", "风华高科", "被动元件", None, 10, 20, "涨价", "被动龙头"),
    ("002138", "顺络电子", "被动元件", None, 15, 20, "涨价", "MLCC加速"),
    ("600563", "法拉电子", "被动元件", None, 8, 16, "涨价", "新能源+数据中心"),

    # 消费电子 (12) — note: spec says 12 but data has 10
    ("601231", "环旭电子", "消费电子", None, 30, 40, "客户放量", "眼镜业务"),
    ("002241", "歌尔股份", "消费电子", None, 0, 10, "AI", "眼镜+AR"),
    ("300433", "蓝思科技", "消费电子", None, -30, -20, "客户转型", "玻璃份额+TGV"),
    ("002273", "水晶光电", "消费电子", None, 10, 20, "客户放量", "终端新品"),
    ("002600", "领益智造", "消费电子", None, 0, 10, "客户放量", "AI/客户"),
    ("300115", "长盈精密", "消费电子", None, 10, 20, "客户放量", "Mac新机"),
    ("603296", "华勤技术", "消费电子", None, 80, 100, "AI", "数据中心"),
    ("001314", "亿道信息", "消费电子", None, 34, 54, "AI", "端侧AI"),
    ("688608", "恒玄科技", "消费电子", None, 30, 51, "AI", "蓝牙+云台相机"),
    ("688088", "虹软科技", "消费电子", None, -25, -15, "AI", "BES6000进度"),

    # 传感器 (2)
    ("603662", "柯力传感", "传感器", None, 188, 217, "机器人", "六维力传感器"),
    ("688007", "光峰科技", "传感器", None, 20, 36, "业绩弹性", "ALPD激光显示"),

    # 机器人 (1)
    ("002472", "双环传动", "机器人", None, 30, 40, "机器人", "RV减速器"),
]

# ── Watchlist group definitions: (sector_name, [codes in that sector])
WATCHLIST_GROUPS: list[tuple[str, list[str]]] = [
    ("半导体-存储", ["603986", "300223", "688110"]),
    ("半导体-AI算力", ["688256", "688041"]),
    ("半导体-IC设计", [
        "301536", "300613", "603893", "688018", "688049",
        "688332", "688252", "688593", "300672", "603501", "688213",
    ]),
    ("半导体-模拟功率", [
        "300661", "688536", "688052",
        "605111", "300373", "688396", "603290",
    ]),
    ("半导体-设备", [
        "002371", "688012", "688072", "688120", "688037",
        "688082", "688200", "688372", "688652", "688409",
        "301611", "688469",
    ]),
    ("半导体-封测", ["600584", "002156", "688362", "688403", "002617"]),
    ("半导体-射频", ["688807"]),
    ("PCB", ["002463", "300476", "002916", "001389", "603920", "002913", "301200"]),
    ("CCL", ["600183", "688519", "002436"]),
    ("面板", ["000100", "000725", "002876"]),
    ("LED", ["002745", "300708", "688383"]),
    ("被动元件", ["300408", "000636", "002138", "600563"]),
    ("消费电子", [
        "601231", "002241", "300433", "002273", "002600",
        "300115", "603296", "001314", "688608", "688088",
    ]),
    ("传感器", ["603662", "688007"]),
    ("机器人", ["002472"]),
]


def fmt_growth_text(low: float, high: float) -> str:
    """Format growth range as text."""
    if high == 9999:
        return f"+{low:.0f}%以上"
    return f"+{low:.0f}%~+{high:.0f}%"


def resolve_high(low: float, high: float) -> float:
    """Resolve sentinel 9999 for 'X%以上' to low * 1.5 as a conservative mid."""
    if high == 9999:
        return round(low * 1.5, 1)
    return high


def rebuild_earnings_preview() -> int:
    """Delete and repopulate earnings_preview table. Return row count."""
    conn = sqlite3.connect(EP_DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM earnings_preview")

    n = 0
    for code, name, sector, subsector, g_low, g_high, driver, highlight in COMPANIES:
        real_high = resolve_high(g_low, g_high)
        g_mid = round((g_low + real_high) / 2, 1)
        g_text = fmt_growth_text(g_low, g_high)
        cur.execute(
            """INSERT INTO earnings_preview
               (code, name, sector, subsector, growth_low, growth_high,
                growth_mid, growth_text, core_driver, highlight,
                report_period, report_source, report_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, name, sector, subsector, g_low, real_high,
             g_mid, g_text, driver, highlight,
             REPORT_PERIOD, REPORT_SOURCE, REPORT_DATE),
        )
        n += 1

    conn.commit()
    conn.close()
    return n


def rebuild_watchlist() -> tuple[int, int]:
    """Delete groups 4+ and rebuild from WATCHLIST_GROUPS. Return (n_groups, n_entries)."""
    conn = sqlite3.connect(WL_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # Clean old groups 4+
    cur.execute("DELETE FROM stock_entries WHERE group_id >= 4")
    cur.execute("DELETE FROM groups WHERE id >= 4")

    # Reset autoincrement sequence so new groups start at 4
    cur.execute("DELETE FROM sqlite_sequence WHERE name = 'groups'")
    cur.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('groups', 3)")
    cur.execute("DELETE FROM sqlite_sequence WHERE name = 'stock_entries'")
    cur.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('stock_entries', 0)")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    group_desc = f"H1 2026 业绩前瞻（来源: {REPORT_SOURCE} {REPORT_DATE}）"

    # Build code → name map from COMPANIES
    code2name = {c[0]: c[1] for c in COMPANIES}

    n_groups = 0
    n_entries = 0
    next_group_id = 4

    for sector_name, codes in WATCHLIST_GROUPS:
        gid = next_group_id
        next_group_id += 1
        cur.execute(
            "INSERT INTO groups (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (gid, sector_name, group_desc, now),
        )
        n_groups += 1

        for code in codes:
            name = code2name.get(code, "")
            cur.execute(
                """INSERT INTO stock_entries (code, name, group_id, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (code, name, gid, None, now),
            )
            n_entries += 1

    conn.commit()
    conn.close()
    return n_groups, n_entries


def main() -> None:
    print("═" * 60)
    print("Rebuild earnings_preview.db + watchlist groups 4+")
    print(f"Source: {REPORT_SOURCE} {REPORT_PERIOD} ({REPORT_DATE})")
    print("═" * 60)

    n_ep = rebuild_earnings_preview()
    print(f"✅ earnings_preview: {n_ep} rows inserted")

    n_grp, n_ent = rebuild_watchlist()
    print(f"✅ watchlist: {n_grp} groups, {n_ent} entries (groups 4+)")

    # Verification
    print("\n── Verification ──")
    conn = sqlite3.connect(EP_DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM earnings_preview")
    print(f"earnings_preview count: {cur.fetchone()[0]}")

    # Check known corrections
    for code, expected in [("688072", "拓荆科技"), ("300613", "富瀚微"), ("688007", "光峰科技")]:
        cur.execute("SELECT name FROM earnings_preview WHERE code = ?", (code,))
        row = cur.fetchone()
        actual = row[0] if row else "NOT FOUND"
        status = "✅" if actual == expected else "❌"
        print(f"  {status} {code} → {actual} (expected {expected})")

    cur.execute("SELECT sector, COUNT(*) FROM earnings_preview GROUP BY sector ORDER BY sector")
    for sector, cnt in cur.fetchall():
        print(f"  {sector}: {cnt}")
    conn.close()

    conn = sqlite3.connect(WL_DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM groups WHERE id >= 4")
    print(f"\nwatchlist groups (4+): {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM stock_entries WHERE group_id >= 4")
    print(f"watchlist entries (4+): {cur.fetchone()[0]}")
    conn.close()

    print("\n🎉 Done!")


if __name__ == "__main__":
    main()
