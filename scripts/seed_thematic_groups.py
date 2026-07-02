#!/usr/bin/env -S uv run python
"""按主题建立自选股分组（H1 2026 业绩前瞻）。

设计：
- 13 个主题 group，覆盖中信证券 7/2 报告的 41 家公司
- Group.description 标注数据来源 + 报告期，方便后续追溯
- StockEntry.note 存业绩弹性 + 核心驱动，扫码时一眼看出
- 同一只股票可属于多个主题（通过插入多条 StockEntry）
- 现有 3 个持仓 group（白酒/银行/新能源）不动

主题分类：
    半导体（6 子类）+ AI算力 + PCB + 面板 + LED + 传感器 + 机器人 + 消费电子

用法：
    uv run python scripts/seed_thematic_groups.py            # 全部建组 + 入股
    uv run python scripts/seed_thematic_groups.py --dry-run  # 只打印不写库
    uv run python scripts/seed_thematic_groups.py --show     # 写完后展示分组
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path("data/watchlist.db").resolve()

# 数据来源
REPORT_SOURCE = "中信证券"
REPORT_DATE = "2026-07-02"
REPORT_PERIOD = "H1 2026"
DESCRIPTION = f"{REPORT_PERIOD} 业绩前瞻（来源: {REPORT_SOURCE} {REPORT_DATE}）"

# 主题分组设计
# 格式: { group_name: [(code, name, note), ...] }
# note 格式: "+188%~+217% | driver=机器人/工业" 或 "-51%~-2% | driver=涨价/份额"
THEMATIC_GROUPS: dict[str, list[tuple[str, str, str]]] = {
    # ====== 半导体（6 子类） ======
    "半导体-存储": [
        ("603986", "兆易创新", "+1070%~+1370% | driver=AI/涨价 | 业绩大增长动力强劲"),
        ("300223", "北京君正", "+440%~+520% | driver=AI/涨价 | 业绩大增长动力强劲"),
    ],
    "半导体-IC设计": [
        ("603501", "韦尔股份", "+30%~+40% | driver=AI | 高端 CIS 需求"),
        ("688052", "纳芯微", "+50%~+60% | driver=自主可控 | 汽车业务趋势"),
        ("688213", "思特威", "+20%~+25% | driver=AI/智能驾驶 | 高端 CIS"),
        ("301536", "星宸科技", "+336%~+627% | driver=AIoT | 端侧 AI"),
        ("603893", "瑞芯微", "+20%~+40% | driver=AIoT | 景气延续"),
        ("688403", "汇成股份", "+10%~+15% | driver=自主可控 | DDIC 稳健"),
    ],
    "半导体-设备": [
        ("002371", "北方华创", "+30%~+50% | driver=自主可控 | 国产设备平台龙头"),
        ("688012", "中微公司", "+28%~+40% | driver=自主可控 | 设备平台龙头"),
        ("688120", "华海清科", "+20%~+40% | driver=自主可控 | 国产替代"),
        ("688037", "芯源微", "+20%~+40% | driver=自主可控 | 存储/逻辑/封测"),
    ],
    "半导体-材料": [
        ("688519", "南亚新材", "+354%~+505% | driver=涨价 | CCL 涨价传导"),
        ("688072", "富创精密", "+188%~+217% | driver=自主可控 | 半导体零部件"),
        ("002617", "露笑科技", "+336%~+627% | driver=涨价 | SiC 衬底"),
        ("603290", "斯达半导", "-51%~-2% | driver=涨价/份额 | ⚠️ 受 SiC 涨价影响"),
    ],
    "半导体-封测": [
        ("002156", "通富微电", "+15%~+20% | driver=AI | AMD/存储需求"),
        ("600584", "长电科技", "+10%~+15% | driver=AI/涨价 | 电源管理/存储"),
    ],
    "半导体-LED设备": [
        ("688383", "新益昌", "+430%~+671% | driver=业绩弹性 | LED 高端设备"),
    ],
    # ====== AI 算力 ======
    "AI算力": [
        ("688256", "寒武纪", "+126%~+183% | driver=AI | 算力高增"),
        ("688041", "海光信息", "+83%~+96% | driver=AI | 算力高增"),
    ],
    # ====== PCB ======
    "PCB": [
        ("002463", "沪电股份", "+52%~+74% | driver=AI | AI 服务器 PCB"),
        ("300476", "胜宏科技", "+15%~+23% | driver=AI | AI 服务器 PCB"),
        ("002916", "深南电路", "+15%~+50% | driver=AI | AI 服务器 PCB"),
        ("001389", "广合科技", "+99%~+119% | driver=AI | 涨价传导"),
        ("603920", "世运电路", "-51%~-2% | driver=涨价 | ⚠️ 汽车 PCB 承压"),
    ],
    # ====== 面板 ======
    "面板": [
        ("000100", "TCL科技", "+61%~+84% | driver=涨价 | LCD 高位"),
        ("000725", "京东方A", "-2%~+10% | driver=涨价 | LCD/OLED"),
        ("002876", "三孚新科", "+261%~+502% | driver=涨价 | 面板材料"),
    ],
    # ====== LED ======
    "LED": [
        ("002745", "木林森", "+824%~+1286% | driver=业绩弹性 | LED 景气"),
        ("300708", "聚灿光电", "-28%~-8% | driver=业绩弹性 | ⚠️ LED 芯片"),
    ],
    # ====== 传感器 ======
    "传感器": [
        ("603662", "柯力传感", "+188%~+217% | driver=机器人/工业 | ⭐ 人形机器人"),
        ("688007", "优利德", "+20%~+36% | driver=业绩弹性 | 测试仪器"),
    ],
    # ====== 机器人（柯力跨主题）======
    "机器人": [
        ("603662", "柯力传感", "+188%~+217% | driver=机器人/工业 | ⭐ 六维力"),
        ("002472", "双环传动", "+30%~+40% | driver=机器人/清洁能源 | 丝杠外骨骼"),
    ],
    # ====== 消费电子 ======
    "消费电子": [
        ("002600", "领益智造", "+0%~+10% | driver=AI/客户放量 | 多领域放量"),
        ("002241", "歌尔股份", "0%~+10% | driver=AI | AI 眼镜"),
        ("002273", "水晶光电", "+10%~+20% | driver=客户放量 | 北美大客户"),
        ("300433", "蓝思科技", "-30%~-20% | driver=客户转型 | ⚠️ 客户结构转型"),
        ("603296", "华勤技术", "+20%~+30% | driver=AI/客户放量 | AI 服务器/PC"),
        ("300115", "协创数据", "+10%~+20% | driver=涨价 | 存储模组"),
        ("300613", "雷神科技", "+133%~+180% | driver=AI | AI PC 换机"),
    ],
}


def show_existing_groups(conn: sqlite3.Connection) -> None:
    """展示现有 group 概览。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT g.id, g.name,
               (SELECT COUNT(*) FROM stock_entries WHERE group_id = g.id) AS n
        FROM groups g
        ORDER BY g.id
        """
    )
    print("=== 现有分组 ===")
    for gid, name, n in cursor.fetchall():
        marker = " 持仓" if name in ("白酒", "银行", "新能源") else " 主题"
        print(f"  [{gid:>2}] {name:<20} ({n} 只)  {marker}")


def seed_groups(dry_run: bool = False) -> tuple[int, int, int]:
    """建组 + 入股。返回 (group_added, entry_added, entry_skipped)。"""

    from mommy_chaogu.watchlist.store import (
        GroupAlreadyExistsError,
        WatchlistStore,
    )

    if dry_run:
        print("[DRY-RUN 模式]\n")
        for g_name, entries in THEMATIC_GROUPS.items():
            print(f"  📁 {g_name} ({len(entries)} 只)")
            for code, _name, note in entries:
                print(f"     - {code} {_name}  | {note}")
        n_groups = len(THEMATIC_GROUPS)
        n_entries = sum(len(v) for v in THEMATIC_GROUPS.values())
        return n_groups, n_entries, 0

    store = WatchlistStore(DB_PATH)
    g_added = 0
    e_added = 0
    e_skipped = 0

    for g_name, entries in THEMATIC_GROUPS.items():
        # 幂等建组
        try:
            store.add_group(name=g_name, description=DESCRIPTION)
            g_added += 1
            print(f"  ✅ 新建分组: {g_name}")
        except GroupAlreadyExistsError:
            print(f"  ⏭  分组已存在: {g_name}")

        # 入股
        for code, _name, note in entries:
            try:
                entry = store.add_entry(code=code, group_name=g_name, note=note)
                if entry.name is None:
                    # 名称缺失（首次入），不影响
                    pass
                e_added += 1
            except Exception as exc:
                e_skipped += 1
                print(f"     ⚠️ {code} 入 {g_name} 失败: {exc}")

    return g_added, e_added, e_skipped


def show_result(conn: sqlite3.Connection) -> None:
    """展示结果（按主题分组）。"""
    cursor = conn.cursor()
    print()
    print("=" * 70)
    print("📋 入库结果（按主题分组）")
    print("=" * 70)

    cursor.execute(
        """
        SELECT g.name, g.description, COUNT(e.id) AS n
        FROM groups g
        LEFT JOIN stock_entries e ON e.group_id = g.id
        GROUP BY g.id
        HAVING g.description LIKE '%业绩前瞻%'  -- 只显示本次新增的
        ORDER BY n DESC, g.name
        """
    )
    rows = cursor.fetchall()
    for g_name, _desc, n in rows:
        print(f"\n📁 {g_name}  ({n} 只)")
        cursor.execute(
            """
            SELECT e.code, e.name, e.note
            FROM stock_entries e
            JOIN groups g ON g.id = e.group_id
            WHERE g.name = ?
            ORDER BY e.code
            """,
            (g_name,),
        )
        for code, name, note in cursor.fetchall():
            print(f"     - {code} {name or '待回填':　<6}  | {note}")

    # 跨主题股
    print()
    print("=" * 70)
    print("🔀 跨主题股（在多个主题组里）")
    print("=" * 70)
    cursor.execute(
        """
        SELECT code, GROUP_CONCAT(name, ', ') AS groups
        FROM (
            SELECT e.code, g.name
            FROM stock_entries e
            JOIN groups g ON g.id = e.group_id
            WHERE g.description LIKE '%业绩前瞻%'
        )
        GROUP BY code
        HAVING COUNT(*) > 1
        """
    )
    cross = cursor.fetchall()
    if cross:
        for code, groups in cross:
            print(f"  {code}: {groups}")
    else:
        print("  （无）")


def main() -> None:
    parser = argparse.ArgumentParser(description="按主题建立自选股分组")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    parser.add_argument("--show", action="store_true", help="写完后展示分组")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    print(f"📂 数据库: {DB_PATH}\n")
    show_existing_groups(conn)

    print()
    print("=" * 70)
    print(f"🌱 开始建组 + 入股（{len(THEMATIC_GROUPS)} 个主题组，"
          f"{sum(len(v) for v in THEMATIC_GROUPS.values())} 条记录）")
    print("=" * 70)

    g_added, e_added, e_skipped = seed_groups(dry_run=args.dry_run)

    print()
    print(f"📊 汇总: 新建分组 {g_added}, 新增条目 {e_added}, 跳过 {e_skipped}")

    if args.show and not args.dry_run:
        show_result(conn)

    conn.close()


if __name__ == "__main__":
    main()
