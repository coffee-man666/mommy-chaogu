"""earnings CLI 入口：mommy-earnings。

注册方式（在 pyproject.toml 里）：
    [project.scripts]
    mommy-earnings = "mommy_chaogu.earnings.cli:main_earnings"

用法示例：
    # 拉取某批股票的 actual 业绩
    mommy-earnings pull --codes 603662,603986 --period "H1 2026"

    # 批量比对 actual vs predicted
    mommy-earnings score --period "H1 2026"

    # 列出未来 7 天的披露日历
    mommy-earnings watch --days 7

    # 看 period 的 verdict 分布
    mommy-earnings summary --period "H1 2026"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from mommy_chaogu.earnings import (
    EarningsService,
    EarningsStore,
    EfinanceEarningsAdapter,
    MockEarningsAdapter,
)
from mommy_chaogu.earnings.types import VERDICT_LABEL, EarningsVerdict

# ---------- DB 构造 ----------


def _build_service(args: argparse.Namespace) -> EarningsService:
    """构造 EarningsService。

    默认 adapter: EfinanceEarningsAdapter（真实数据，依赖网络）
    可选 --adapter mock 切换为 MockEarningsAdapter（测试用）
    """
    actual_db = Path(args.db)
    preview_db = Path(args.preview_db)
    store = EarningsStore(actual_db)

    adapter_choice = getattr(args, "adapter", "efinance")
    adapter: MockEarningsAdapter | EfinanceEarningsAdapter = (
        MockEarningsAdapter() if adapter_choice == "mock" else EfinanceEarningsAdapter()
    )

    return EarningsService(adapter, store, preview_db)


# ---------- 子命令 ----------


def cmd_earnings_pull(args: argparse.Namespace) -> int:
    """拉取一批股票的 actual 业绩。"""
    service = _build_service(args)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    result = service.pull_actual(codes, args.period)

    print(f"📥 拉取完成: 成功 {result.ok}, 失败 {result.failed}")
    if result.failed_codes:
        print(f"   失败 codes: {', '.join(result.failed_codes)}")
    print(f"   耗时: {result.elapsed_seconds:.2f}s")
    return 0


def cmd_earnings_score(args: argparse.Namespace) -> int:
    """批量计算 actual vs predicted 的 score。"""
    service = _build_service(args)
    result = service.score_all(args.period)

    print(f"📊 比对完成: 成功 {result.ok}, 失败 {result.failed}")
    if result.failed_codes:
        print(f"   失败 codes: {', '.join(result.failed_codes)}")
    print(f"   耗时: {result.elapsed_seconds:.2f}s")

    # 列出 top 5 最显著的 score
    scores = service.store.list_scores(period=args.period)[:5]
    if scores:
        print("\n🏆 TOP 5 (按置信度 + gap 排序):")
        print(f"{'代码':<8} {'名称':<10} {'预测区间':<14} {'实际':<10} {'verdict':<12}")
        print("─" * 64)
        for s in scores:
            label = VERDICT_LABEL.get(s.verdict, s.verdict.value)
            pred = f"{s.predicted_low:.0f}~{s.predicted_high:.0f}%"
            actual = f"{s.actual_growth:.1f}%" if s.actual_growth is not None else "N/A"
            print(f"{s.code:<8} {s.name:<10} {pred:<14} {actual:<10} {label}")
    return 0


def cmd_earnings_watch(args: argparse.Namespace) -> int:
    """列出未来 N 天的披露日历。"""
    service = _build_service(args)
    upcoming = service.watch_calendar(days_ahead=args.days, period=args.period)

    print(f"📅 未来 {args.days} 天披露日历:")
    if not upcoming:
        print("   (空)")
        return 0
    print(f"{'代码':<8} {'报告期':<10} {'披露日期':<12}")
    print("─" * 36)
    for code, period, d in upcoming:
        print(f"{code:<8} {period:<10} {d.isoformat()}")
    return 0


def cmd_earnings_summary(args: argparse.Namespace) -> int:
    """看某 period 的 verdict 分布。"""
    service = _build_service(args)
    summary = service.summary(args.period)

    print("📈 H1 2026 业绩比对摘要:")
    if not summary:
        print("   (无数据)")
        return 0
    total = sum(summary.values())
    print(f"   总数: {total}\n")
    print(f"{'verdict':<14} {'数量':>4} {'占比':>8}")
    print("─" * 30)
    for v in EarningsVerdict:
        n = summary.get(v, 0)
        pct = (n / total * 100) if total > 0 else 0
        label = VERDICT_LABEL.get(v, v.value)
        print(f"{label:<14} {n:>4} {pct:>7.1f}%")
    return 0


# ---------- Parser ----------


def build_earnings_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-earnings",
        description="业绩前瞻 vs 实际披露 比对工具",
    )
    p.add_argument(
        "--db",
        default="data/earnings_actual.db",
        help="earnings_actual 数据库路径 (default: data/earnings_actual.db)",
    )
    p.add_argument(
        "--preview-db",
        default="data/earnings_preview.db",
        help="earnings_preview 数据库路径 (default: data/earnings_preview.db)",
    )
    p.add_argument(
        "--adapter",
        choices=["efinance", "mock"],
        default="efinance",
        help="数据源 adapter (default: efinance)",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # pull
    p_pull = sub.add_parser("pull", help="拉取 actual 业绩")
    p_pull.add_argument("--codes", required=True, help="逗号分隔的股票代码")
    p_pull.add_argument("--period", default="H1 2026", help="报告期")
    p_pull.set_defaults(func=cmd_earnings_pull)

    # score
    p_score = sub.add_parser("score", help="批量比对 actual vs predicted")
    p_score.add_argument("--period", default="H1 2026", help="报告期")
    p_score.set_defaults(func=cmd_earnings_score)

    # watch
    p_watch = sub.add_parser("watch", help="看未来 N 天披露日历")
    p_watch.add_argument("--days", type=int, default=7, help="未来天数")
    p_watch.add_argument("--period", default=None, help="报告期过滤")
    p_watch.set_defaults(func=cmd_earnings_watch)

    # summary
    p_summary = sub.add_parser("summary", help="看 verdict 分布")
    p_summary.add_argument("--period", default="H1 2026", help="报告期")
    p_summary.set_defaults(func=cmd_earnings_summary)

    return p


def main_earnings() -> NoReturn:
    parser = build_earnings_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)
