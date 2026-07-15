"""report command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# report 子命令（HTML 报告渲染）
# ============================================================


DEFAULT_REPORT_HTML_DIR = Path("reports")


def _resolve_report_md(day: str | None) -> Path:
    """根据 --day 找到对应的 .md 报告。"""
    from datetime import date

    d = date.fromisoformat(day) if day else date.today()
    return Path(DEFAULT_FLOWS_REPORT_DIR) / f"flows_report_{d.isoformat()}.md"


def cmd_report_render(args: argparse.Namespace) -> int:
    from mommy_chaogu.report_render import parse_markdown_report, render_one

    md_path = _resolve_report_md(args.day)
    if not md_path.exists():
        print(f"❌ 找不到报告: {md_path}")
        print(f"   先跑: uv run mommy-flows --pool {args.pool} report --day {args.day or '今天'}")
        return 1

    r = parse_markdown_report(md_path)
    out_dir = Path(args.out_dir)
    p = render_one(r, out_dir=out_dir)
    print(f"✅ {p}  ({p.stat().st_size:,} B)")
    print(f"   打开: open {p}")
    return 0


def cmd_report_index(args: argparse.Namespace) -> int:
    """扫描所有 .md 报告，渲染 index.html。"""
    from mommy_chaogu.report_render import (
        ReportData,
        parse_markdown_report,
        render_index,
    )

    src_dir = Path(DEFAULT_FLOWS_REPORT_DIR)
    if not src_dir.exists():
        print(f"❌ 报告目录不存在: {src_dir}")
        return 1

    md_files = sorted(src_dir.glob("*.md"))
    if not md_files:
        print(f"❌ 没有任何报告: {src_dir}/*.md")
        return 1

    reports: list[ReportData] = []
    for p in md_files:
        try:
            reports.append(parse_markdown_report(p))
        except Exception:
            # 跳过非 flows 日报格式的 .md 文件
            continue
    if not reports:
        print(f"❌ 没有找到可解析的 flows 日报: {src_dir}/*.md")
        return 1
    p = render_index(reports, out_dir=args.out_dir)
    print(f"✅ {p}  ({len(reports)} 份报告)")
    return 0


def cmd_report_serve(args: argparse.Namespace) -> int:
    """起一个临时 HTTP server 预览 reports/。"""
    import http.server
    import socketserver

    out_dir = Path(args.out_dir).resolve()
    if not out_dir.exists():
        print(f"❌ {out_dir} 不存在，先跑 mommy-report render")
        return 1

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(out_dir), **kwargs)

    with socketserver.TCPServer(("0.0.0.0", args.port), _Handler) as srv:
        print(f"🌐 {out_dir} listening on http://localhost:{args.port}/")
        print("   Ctrl+C 退出")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 bye")
    return 0


def build_report_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-report",
        description="把 .md 资金流报告渲染成独立 HTML 网页",
        epilog=(
            "example:\n"
            "  mommy report render\n"
            "  mommy report index\n"
            "  mommy report serve --port 8787"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_r = sub.add_parser("render", help="渲染单日报告 HTML")
    p_r.add_argument("--day", help="日期 YYYY-MM-DD（默认今天）")
    p_r.add_argument("--pool", default="semicon", help="池子（决定报告路径）")
    p_r.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_HTML_DIR),
        help=f"HTML 输出目录 (默认 {DEFAULT_REPORT_HTML_DIR})",
    )
    p_r.set_defaults(func=cmd_report_render)

    p_i = sub.add_parser("index", help="扫描全部 .md 报告，重建 index.html")
    p_i.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_HTML_DIR),
        help=f"HTML 输出目录 (默认 {DEFAULT_REPORT_HTML_DIR})",
    )
    p_i.set_defaults(func=cmd_report_index)

    p_s = sub.add_parser("serve", help="起 HTTP server 预览 reports/")
    p_s.add_argument("--port", type=int, default=8787, help="端口（默认 8787）")
    p_s.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_HTML_DIR),
        help=f"HTML 输出目录 (默认 {DEFAULT_REPORT_HTML_DIR})",
    )
    p_s.set_defaults(func=cmd_report_serve)

    return p


def main_report() -> NoReturn:
    parser = build_report_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)
