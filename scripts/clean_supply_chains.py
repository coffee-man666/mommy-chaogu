"""清理 supply_chains JSON：移除所有运行时/动态字段，只留静态信息。

适用对象：data/supply_chains/*.json

设计原则（与 watchlist.json 一致）：
- 静态 = 不随时间变化（板块元数据 + 股票的代码/名称/角色/层级/分类/备注）
- 动态 = 任何会随市场变化的值（价格、涨跌幅、资金流、PE、市值、snapshot 整块）

白名单字段：
- meta:   name, description, id, name_en, total_stocks,
          subcategories, chain_positions, levels, roles, categories, source
- stocks: code, name, role, level, subcategory, category, note, board

用法：
    uv run python scripts/clean_supply_chains.py semiconductor
    uv run python scripts/clean_supply_chains.py --all          # 处理全部
    uv run python scripts/clean_supply_chains.py --check semiconductor  # dry-run + diff
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPLY_DIR = REPO_ROOT / "data" / "supply_chains"

META_KEEP = {
    "name",
    "description",
    "id",
    "name_en",
    "total_stocks",
    "subcategories",
    "chain_positions",
    "levels",
    "roles",
    "categories",
    "source",
}
STOCK_KEEP = {
    "code",
    "name",
    "role",
    "level",
    "subcategory",
    "category",
    "note",
    "board",
}


def clean_payload(payload: dict) -> tuple[dict, list[str]]:
    """清理 payload，返回 (cleaned, removed_fields_list)。

    设计要点：
    - 只保留白名单字段，未知字段会被丢弃（但记录到 removed_fields）
    - 整个 snapshot 块永远删除
    - stocks 保持原顺序（不变更用户已校对过的列表）
    """
    removed: list[str] = []

    # meta: 白名单过滤
    old_meta = payload.get("meta", {})
    new_meta = {k: v for k, v in old_meta.items() if k in META_KEEP}
    for k in old_meta:
        if k not in META_KEEP:
            removed.append(f"meta.{k}")

    # stocks: 白名单过滤 + 保持顺序
    new_stocks: list[dict] = []
    for s in payload.get("stocks", []):
        new_s = {k: v for k, v in s.items() if k in STOCK_KEEP}
        for k in s:
            if k not in STOCK_KEEP:
                removed.append(f"stocks[].{k}")
        new_stocks.append(new_s)

    # snapshot: 整个删除
    if "snapshot" in payload:
        for k in payload["snapshot"]:
            removed.append(f"snapshot.{k}")

    cleaned = {"meta": new_meta, "stocks": new_stocks}
    return cleaned, sorted(set(removed))


def process_file(path: Path, check: bool = False) -> int:
    """处理单个文件。返回 0 = 成功, 1 = 没变化, 2 = 错误。"""
    try:
        original = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR 读 {path.name}: {e}", file=sys.stderr)
        return 2

    cleaned, removed = clean_payload(original)

    if not removed:
        print(f"  skip   {path.name}: 已经干净（无动态字段）")
        return 1

    print(f"  clean  {path.name}: 移除 {len(removed)} 个动态字段")
    if check:
        # dry-run: 打印要移除的字段，不写盘
        for f in removed:
            print(f"         - {f}")
        return 0

    # 写回（用 ensure_ascii=False 保留中文，indent=2 跟原文件一致）
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="清理 supply_chains JSON：移除动态字段")
    p.add_argument("chain", nargs="?", help="板块名（如 semiconductor）")
    p.add_argument("--all", action="store_true", help="处理全部 supply_chains 文件")
    p.add_argument("--check", action="store_true", help="dry-run，只显示要移除的字段")
    args = p.parse_args()

    if not args.all and not args.chain:
        p.error("必须传 chain 名或 --all")

    if args.all:
        files = sorted(SUPPLY_DIR.glob("*.json"))
    else:
        target = SUPPLY_DIR / f"{args.chain}.json"
        if not target.exists():
            print(f"  ERROR 文件不存在: {target}", file=sys.stderr)
            return 2
        files = [target]

    mode = "CHECK" if args.check else "CLEAN"
    print(f"[{mode}] 处理 {len(files)} 个文件")
    rc = 0
    for f in files:
        r = process_file(f, check=args.check)
        rc = rc or r
    return rc


if __name__ == "__main__":
    sys.exit(main())
