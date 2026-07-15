"""semicon command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# semicon 子命令
# ============================================================


def _semicon_store(args: argparse.Namespace) -> object:
    from mommy_chaogu.semicon import SemiconStore

    return SemiconStore(Path(args.db))


def cmd_semicon_seed(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon import seed_store

    s = _semicon_store(args)
    r = seed_store(s, overwrite=args.overwrite)
    print(f"✅ seed 完成: 新增 {r['inserted']}  更新 {r['updated']}  跳过 {r['skipped']}")
    return 0


def _print_stocks(stocks: list[object]) -> None:
    if not stocks:
        print("（暂无数据）")
        return
    print(f"{'代码':<8} {'名称':<10} {'主位置':<6} {'子分类':<8} {'产品':<16} {'板块':<6} 备注")
    print("─" * 90)
    for s in stocks:
        prod = (s.product or "—")[:14]
        note = (s.note or "")[:30]
        print(
            f"{s.code:<8} {s.name:<10} {s.chain_position:<6} {s.subcategory:<8} "
            f"{prod:<16} {s.board:<6} {note}"
        )


def cmd_semicon_list(args: argparse.Namespace) -> int:
    s = _semicon_store(args)
    if args.chain:
        rows = s.list_by_chain(args.chain)
    elif args.subcategory:
        rows = s.list_by_subcategory(args.subcategory)
    else:
        rows = s.list_all()
    _print_stocks(rows)
    print(f"\n共 {len(rows)} 条")
    return 0


def cmd_semicon_search(args: argparse.Namespace) -> int:
    s = _semicon_store(args)
    rows = s.search(args.keyword)
    print(f"🔍 关键字 {args.keyword!r} 命中 {len(rows)} 条")
    print("─" * 90)
    _print_stocks(rows)
    return 0


def cmd_semicon_get(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon.store import StockNotFoundError

    s = _semicon_store(args)
    try:
        row = s.require(args.code)
    except StockNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"代码: {row.code}")
    print(f"名称: {row.name}")
    print(f"主位置: {row.chain_position}")
    print(f"子分类: {row.subcategory}")
    print(f"产品: {row.product or '—'}")
    print(f"板块: {row.board}")
    print(f"备注: {row.note or '—'}")
    print(f"添加于: {row.created_at:%Y-%m-%d %H:%M:%S}")
    print(f"更新于: {row.updated_at:%Y-%m-%d %H:%M:%S}")
    return 0


def cmd_semicon_stats(args: argparse.Namespace) -> int:
    s = _semicon_store(args)
    st = s.stats()
    print("📊 半导体产业链参考库统计")
    print("─" * 60)
    print(f"  股票总数:    {st['total']}")
    print(f"  主位置数:    {st['chains']} ({' / '.join(c.value for c in ChainPosition)})")
    print(f"  子分类数:    {st['subcategories']}")
    print(f"  板块数:      {st['boards']}")
    print()
    print("按主位置分布:")
    for cp, n in s.count_by_chain():
        bar = "█" * min(n // 2, 30)
        print(f"  {cp:<6} {n:>3}  {bar}")
    print()
    print("按子分类分布（chain / subcategory / count）:")
    for cp, sub, n in s.count_by_subcategory():
        bar = "█" * min(n, 20)
        print(f"  {cp:<6} / {sub:<8} {n:>3}  {bar}")
    return 0


def cmd_semicon_add(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon.store import StockAlreadyExistsError

    s = _semicon_store(args)
    try:
        row = s.add(
            args.code,
            args.name,
            args.chain,
            args.subcategory,
            product=args.product,
            board=args.board,
            note=args.note,
        )
    except StockAlreadyExistsError as e:
        print(f"⚠️  {e}")
        return 1
    print(f"✅ 已添加 {row.code} {row.name} ({row.chain_position}/{row.subcategory})")
    return 0


def cmd_semicon_remove(args: argparse.Namespace) -> int:
    from mommy_chaogu.semicon.store import StockNotFoundError

    s = _semicon_store(args)
    try:
        s.remove(args.code)
    except StockNotFoundError as e:
        print(f"❌ {e}")
        return 1
    print(f"🗑️  已删除 {args.code}")
    return 0


def build_semicon_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-semicon",
        description="妈妈炒股 - 半导体产业链参考库（A 股，按位置/产品分组）",
        epilog=(
            "example:\n"
            "  mommy semicon seed\n"
            "  mommy semicon list --chain 上游\n"
            "  mommy semicon search 存储"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db",
        default=str(DEFAULT_SEMICON_DB_PATH),
        help=f"数据库路径 (默认 {DEFAULT_SEMICON_DB_PATH})",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # seed
    p_seed = sub.add_parser("seed", help="灌入种子数据")
    p_seed.add_argument("--overwrite", action="store_true", help="覆盖已有记录（更新字段）")
    p_seed.set_defaults(func=cmd_semicon_seed)

    # list
    p_l = sub.add_parser("list", help="列出股票")
    p_l.add_argument(
        "--chain",
        "-c",
        choices=[c.value for c in ChainPosition],
        help="按主位置过滤（上游/中游/下游/末端）",
    )
    p_l.add_argument("--subcategory", "-s", help="按子分类过滤（如 设备/材料/存储/...）")
    p_l.set_defaults(func=cmd_semicon_list)

    # search
    p_sr = sub.add_parser("search", help="按关键字模糊搜索 name/product/note/code")
    p_sr.add_argument("keyword", help="关键字")
    p_sr.set_defaults(func=cmd_semicon_search)

    # get
    p_g = sub.add_parser("get", help="查询单只股票详情")
    p_g.add_argument("code", help="股票代码")
    p_g.set_defaults(func=cmd_semicon_get)

    # stats
    sub.add_parser("stats", help="汇总统计 + 分布").set_defaults(func=cmd_semicon_stats)

    # add
    p_a = sub.add_parser("add", help="手动添加一条记录")
    p_a.add_argument("code", help="股票代码")
    p_a.add_argument("name", help="中文名")
    p_a.add_argument(
        "--chain", "-c", required=True, choices=[c.value for c in ChainPosition], help="主位置"
    )
    p_a.add_argument(
        "--subcategory",
        "-s",
        required=True,
        choices=[sc.value for sc in Subcategory],
        help="子分类",
    )
    p_a.add_argument("--product", "-p", help="具体产品")
    p_a.add_argument(
        "--board", "-b", default="主板", choices=[b.value for b in Board], help="板块（默认 主板）"
    )
    p_a.add_argument("--note", "-n", help="备注")
    p_a.set_defaults(func=cmd_semicon_add)

    # remove
    p_r = sub.add_parser("remove", help="删除一条记录")
    p_r.add_argument("code", help="股票代码")
    p_r.set_defaults(func=cmd_semicon_remove)

    return p


def main_semicon() -> NoReturn:
    parser = build_semicon_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)
