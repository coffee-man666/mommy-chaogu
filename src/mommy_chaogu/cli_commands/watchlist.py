"""watchlist command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ---------- 共用 ----------


def _store(args: argparse.Namespace) -> WatchlistStore:
    return WatchlistStore(Path(args.db))


# ============================================================
# watchlist 子命令
# ============================================================


def cmd_watchlist_add_group(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        g = s.add_group(args.name, description=args.description)
    except GroupAlreadyExistsError as e:
        print(f"⚠️  {e}")
        return 1
    print(f"✅ 已创建分组 {g.name!r} (id={g.id})")
    return 0


def cmd_watchlist_remove_group(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        s.remove_group(args.name)
    except GroupNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"🗑️  已删除分组 {args.name!r}")
    return 0


def cmd_watchlist_groups(args: argparse.Namespace) -> int:
    s = _store(args)
    rows = s.list_groups()
    if not rows:
        print("（暂无分组）")
        return 0
    print(f"{'分组':<16} {'描述':<30} {'股票数':>6}")
    print("─" * 56)
    for g, n in rows:
        desc = (g.description or "")[:28]
        print(f"{g.name:<16} {desc:<30} {n:>6}")
    return 0


def cmd_watchlist_add(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        entry = s.add_entry(args.code, args.group, note=args.note)
    except GroupNotFoundError as e:
        print(f"❌ {e}")
        return 1
    # 顺手拉一下名字回填
    if entry.name is None:
        try:
            adp = EfinanceAdapter()
            q = adp.get_quote(args.code)
            if q:
                s.backfill_name(args.code, q.name)
                refreshed = s.list_entries(group_name=args.group)
                match = next((e for e in refreshed if e.code == args.code), None)
                if match is not None:
                    entry = match
        except Exception:
            pass
    name = entry.name or "(名称待回填)"
    note = f"  # {entry.note}" if entry.note else ""
    print(f"✅ 已添加 {args.code} {name} 到分组 {args.group!r}{note}")
    return 0


def cmd_watchlist_remove(args: argparse.Namespace) -> int:
    s = _store(args)
    try:
        s.remove_entry(args.code, args.group)
    except GroupNotFoundError as e:
        print(f"❌ {e}")
        return 1
    except StockEntryNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"🗑️  已删除 {args.code} (从 {args.group!r})")
    return 0


def cmd_watchlist_list(args: argparse.Namespace) -> int:
    s = _store(args)
    if args.by_group:
        by_group = s.list_entries_by_group()
        if not by_group:
            print("（暂无自选股）")
            return 0
        for group_name, entries in by_group.items():
            print(f"\n📁 {group_name} ({len(entries)})")
            if not entries:
                print("   (empty)")
                continue
            for e in entries:
                name = e.name or "—"
                note = f"  # {e.note}" if e.note else ""
                print(f"   {e.code:<8} {name:<10}{note}")
        return 0

    entries = s.list_entries()
    if not entries:
        print("（暂无自选股，先 watchlist add）")
        return 0
    print(f"{'代码':<8} {'名称':<10} {'分组':<12} {'备注':<30}")
    print("─" * 64)
    for e in entries:
        name = e.name or "—"
        note = (e.note or "")[:28]
        print(f"{e.code:<8} {name:<10} {e.group.name:<12} {note:<30}")
    return 0


def cmd_watchlist_stats(args: argparse.Namespace) -> int:
    s = _store(args)
    st = s.stats()
    print(f"分组数: {st['groups']}  自选股条目: {st['entries']}  去重股票数: {st['codes']}")
    return 0


def cmd_watchlist_export(args: argparse.Namespace) -> int:
    s = _store(args)
    output = Path(args.output) if args.output else None
    path = s.export_to_json(
        output,
        indent=args.indent,
        ensure_ascii=args.ensure_ascii,
    )
    st = s.stats()
    print(f"已导出 {st['groups']} 组 / {st['entries']} 条 → {path}")
    return 0


def build_watchlist_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-watchlist",
        description="妈妈炒股 - 自选股池管理",
        epilog=(
            "example:\n"
            "  mommy watchlist add 600519 --group 白酒\n"
            "  mommy watchlist list --by-group\n"
            "  mommy watchlist groups"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})"
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # add-group
    p_ag = sub.add_parser("add-group", help="新建分组")
    p_ag.add_argument("name", help="分组名（中文/英文）")
    p_ag.add_argument("--description", "-d", help="分组描述")
    p_ag.set_defaults(func=cmd_watchlist_add_group)

    # remove-group
    p_rg = sub.add_parser("remove-group", help="删除分组（连带删自选股）")
    p_rg.add_argument("name", help="分组名")
    p_rg.set_defaults(func=cmd_watchlist_remove_group)

    # groups
    p_g = sub.add_parser("groups", help="列出所有分组")
    p_g.set_defaults(func=cmd_watchlist_groups)

    # add
    p_a = sub.add_parser("add", help="添加自选股")
    p_a.add_argument("code", help="股票代码（如 600519）")
    p_a.add_argument("--group", "-g", required=True, help="所属分组")
    p_a.add_argument("--note", "-n", help="备注")
    p_a.set_defaults(func=cmd_watchlist_add)

    # remove
    p_r = sub.add_parser("remove", help="删除自选股")
    p_r.add_argument("code", help="股票代码")
    p_r.add_argument("--group", "-g", required=True, help="所属分组")
    p_r.set_defaults(func=cmd_watchlist_remove)

    # list
    p_l = sub.add_parser("list", help="列出自选股")
    p_l.add_argument("--by-group", "-G", action="store_true", help="按分组显示")
    p_l.set_defaults(func=cmd_watchlist_list)

    # stats
    p_s = sub.add_parser("stats", help="汇总统计")
    p_s.set_defaults(func=cmd_watchlist_stats)

    # export
    p_e = sub.add_parser("export", help="导出自选股到 JSON 文件")
    p_e.add_argument(
        "--output",
        "-o",
        default=None,
        help="输出路径（默认 <db 所在目录>/watchlist.json）",
    )
    p_e.add_argument("--indent", type=int, default=2, help="JSON 缩进（默认 2）")
    p_e.add_argument(
        "--ensure-ascii",
        action="store_true",
        help="转义非 ASCII（默认不转义，保留中文）",
    )
    p_e.set_defaults(func=cmd_watchlist_export)

    return p


def main_watchlist() -> NoReturn:
    parser = build_watchlist_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)
