#!/usr/bin/env -S uv run python
"""一键迁移脚本：从旧版数据迁移到新格式。

解决的问题：
1. earnings_preview.db：41 条旧数据（有错误）→ 74 条新数据（修正后）
2. watchlist.db groups 4+：旧分组结构 → 新 sector 分组
3. supply_chains/*.json：旧版带运行时字段 → 纯静态种子（git pull 自动解决）
4. hub data/chains/：同步清洗后的 supply_chains

用法：
    uv run python scripts/migrate.py          # 执行迁移
    uv run python scripts/migrate.py --check   # 只检查不执行（dry-run）
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EP_JSON = PROJECT_ROOT / "data" / "earnings_preview.json"
EP_DB = PROJECT_ROOT / "data" / "earnings_preview.db"
WL_DB = PROJECT_ROOT / "data" / "watchlist.db"
SUPPLY_CHAINS = PROJECT_ROOT / "data" / "supply_chains"

# hub 路径（相对于 mommy-chaogu 的位置）
HUB_CHAINS = PROJECT_ROOT.parent / "mommy-hub" / "data" / "chains"


def header(msg: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {msg}")
    print("═" * 60)


def step(msg: str) -> None:
    print(f"\n▶ {msg}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def skip(msg: str) -> None:
    print(f"  ⏭️  {msg}")


def check_json_exists() -> bool:
    """检查 earnings_preview.json 是否存在。"""
    if not EP_JSON.exists():
        warn(f"{EP_JSON} 不存在，请先 git pull 拿到最新代码")
        return False
    return True


def check_db_needs_migrate() -> dict[str, bool]:
    """检查哪些 DB 需要迁移。"""
    needs: dict[str, bool] = {"ep": False, "wl": False}

    # 检查 earnings_preview.db 条数
    if EP_DB.exists():
        conn = sqlite3.connect(str(EP_DB))
        cur = conn.execute("SELECT COUNT(*) FROM earnings_preview")
        count = cur.fetchone()[0]
        conn.close()
        json_count = len(json.loads(EP_JSON.read_text("utf-8")).get("stocks", []))
        if count != json_count:
            needs["ep"] = True
            warn(f"earnings_preview.db: {count} 条 ≠ JSON {json_count} 条")
        else:
            ok(f"earnings_preview.db: {count} 条，与 JSON 一致")
    else:
        needs["ep"] = True
        warn("earnings_preview.db 不存在")

    # 检查 watchlist groups 4+ 是否匹配新 sector
    if WL_DB.exists():
        conn = sqlite3.connect(str(WL_DB))
        cur = conn.execute("SELECT name FROM groups WHERE id >= 4 ORDER BY id")
        wl_sectors = {row[0] for row in cur.fetchall()}
        conn.close()

        json_stocks = json.loads(EP_JSON.read_text("utf-8")).get("stocks", [])
        json_sectors = {s["sector"] for s in json_stocks}

        if wl_sectors != json_sectors:
            needs["wl"] = True
            warn("watchlist groups 4+ 分组不匹配")
            warn(f"  DB: {sorted(wl_sectors)}")
            warn(f"  JSON: {sorted(json_sectors)}")
        else:
            ok("watchlist groups 4+ 与 JSON 分组一致")
    else:
        needs["wl"] = True
        warn("watchlist.db 不存在")

    return needs


def migrate_earnings_db() -> int:
    """重建 earnings_preview.db from JSON。"""
    stocks = json.loads(EP_JSON.read_text("utf-8")).get("stocks", [])
    EP_DB.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(EP_DB))
    conn.execute("DELETE FROM earnings_preview")

    for s in stocks:
        growth_mid = (s["growth_low"] + s["growth_high"]) / 2
        conn.execute(
            """INSERT INTO earnings_preview
               (code, name, sector, subsector, growth_low, growth_high,
                growth_mid, growth_text, core_driver, highlight,
                report_period, report_source, report_date, watchlist_flag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s["code"], s["name"], s["sector"], s.get("subsector", ""),
                s["growth_low"], s["growth_high"], growth_mid, s["growth_text"],
                s.get("core_driver", ""), s.get("highlight", ""),
                s.get("report_period", "H1 2026"),
                s.get("report_source", "中信证券"),
                s.get("report_date", "2026-07-02"),
                s.get("watchlist_flag", 0),
            ),
        )

    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM earnings_preview").fetchone()[0]
    conn.close()
    return count


def migrate_watchlist() -> tuple[int, int]:
    """重建 watchlist groups 4+ from JSON。"""
    from datetime import datetime

    stocks = json.loads(EP_JSON.read_text("utf-8")).get("stocks", [])

    # 按 sector 分组
    groups: dict[str, list[dict]] = {}
    for s in stocks:
        groups.setdefault(s["sector"], []).append(s)

    conn = sqlite3.connect(str(WL_DB))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM stock_entries WHERE group_id >= 4")
    conn.execute("DELETE FROM groups WHERE id >= 4")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'groups'")
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('groups', 3)")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'stock_entries'")
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('stock_entries', 0)")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = json.loads(EP_JSON.read_text("utf-8")).get("meta", {})
    desc = f"H1 2026 业绩前瞻（来源: {meta.get('source', '中信证券')} {meta.get('report_date', '2026-07-02')}）"

    n_groups = 0
    n_entries = 0
    next_id = 4

    for sector, sector_stocks in sorted(groups.items()):
        gid = next_id
        next_id += 1
        conn.execute(
            "INSERT INTO groups (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (gid, sector, desc, now),
        )
        n_groups += 1
        for s in sector_stocks:
            conn.execute(
                """INSERT INTO stock_entries (code, name, group_id, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (s["code"], s["name"], gid, None, now),
            )
            n_entries += 1

    conn.commit()
    conn.close()
    return n_groups, n_entries


def migrate_supply_chains() -> int:
    """清洗 supply_chains JSON（如果 git pull 还没做，手动清运行时字段）。"""
    if not SUPPLY_CHAINS.exists():
        skip("data/supply_chains/ 不存在")
        return 0

    runtime_fields = {
        "price", "prev_close", "change_pct", "open", "high", "low",
        "volume", "volume_hand", "turnover", "turnover_yi", "turnover_rate",
        "volume_ratio", "pe_dynamic", "total_market_cap", "circulating_market_cap",
        "main_net", "super_large_net", "large_net", "medium_net", "small_net",
        "amount", "amplitude", "change", "market_type_raw",
        "main_net_ratio",
    }

    cleaned = 0
    for path in sorted(SUPPLY_CHAINS.glob("*.json")):
        d = json.loads(path.read_text("utf-8"))
        changed = False

        if "snapshot" in d:
            del d["snapshot"]
            changed = True

        for stock in d.get("stocks", []):
            for key in list(stock.keys()):
                if key in runtime_fields:
                    del stock[key]
                    changed = True

        if changed:
            path.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
            cleaned += 1
            ok(f"清洗 {path.name}")

    if cleaned == 0:
        ok("supply_chains 已是纯静态（无需清洗）")

    return cleaned


def sync_hub_chains() -> None:
    """同步 supply_chains 到 hub data/chains/。"""
    if not HUB_CHAINS.exists():
        skip(f"hub chains 目录不存在: {HUB_CHAINS}")
        return

    for path in sorted(SUPPLY_CHAINS.glob("*.json")):
        dest = HUB_CHAINS / path.name
        shutil.copy2(path, dest)
        ok(f"同步 {path.name} → hub")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键迁移：旧版数据 → 新格式")
    parser.add_argument("--check", action="store_true", help="只检查不执行（dry-run）")
    args = parser.parse_args()

    header("mommy-chaogu 数据迁移")
    print(f"项目根目录: {PROJECT_ROOT}")

    # 前置检查
    step("检查前置条件")
    if not check_json_exists():
        print("\n❌ 迁移终止：请先 git pull 拿到最新的 earnings_preview.json")
        sys.exit(1)
    ok("earnings_preview.json 存在")

    # 检查需要迁移什么
    step("检查数据库状态")
    needs = check_db_needs_migrate()

    if not any(needs.values()):
        print("\n🎉 所有数据已是最新格式，无需迁移")
        return

    if args.check:
        print("\n⏸️  --check 模式：不执行迁移。去掉 --check 执行。")
        return

    # 执行迁移
    if needs["ep"]:
        step("迁移 1/4: 重建 earnings_preview.db")
        count = migrate_earnings_db()
        ok(f"earnings_preview.db: {count} 条")

    if needs["wl"]:
        step("迁移 2/4: 重建 watchlist groups 4+")
        n_grp, n_ent = migrate_watchlist()
        ok(f"watchlist: {n_grp} groups, {n_ent} entries")

    step("迁移 3/4: 清洗 supply_chains（移除运行时字段）")
    migrate_supply_chains()

    step("迁移 4/4: 同步到 hub chains（如有）")
    sync_hub_chains()

    # 验证
    header("迁移完成，验证结果")
    if EP_DB.exists():
        conn = sqlite3.connect(str(EP_DB))
        count = conn.execute("SELECT COUNT(*) FROM earnings_preview").fetchone()[0]
        ok(f"earnings_preview.db: {count} 条")
        conn.close()

    if WL_DB.exists():
        conn = sqlite3.connect(str(WL_DB))
        n_grp = conn.execute("SELECT COUNT(*) FROM groups WHERE id >= 4").fetchone()[0]
        n_ent = conn.execute("SELECT COUNT(*) FROM stock_entries WHERE group_id >= 4").fetchone()[0]
        ok(f"watchlist: {n_grp} groups (4+), {n_ent} entries")
        conn.close()

    # 检查已知修正
    if EP_DB.exists():
        conn = sqlite3.connect(str(EP_DB))
        for code, expected in [("688072", "拓荆科技"), ("300613", "富瀚微"), ("688007", "光峰科技")]:
            row = conn.execute("SELECT name FROM earnings_preview WHERE code = ?", (code,)).fetchone()
            actual = row[0] if row else "NOT FOUND"
            status = "✅" if actual == expected else "❌"
            print(f"  {status} {code} = {actual} (应为 {expected})")
        conn.close()

    print(f"\n{'═' * 60}")
    print("🎉 迁移完成！")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
