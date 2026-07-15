"""memory command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# memory 子命令（记忆系统可见性）
# ============================================================


def _truncate(text: str, width: int) -> str:
    """把文本截断到 *width* 个字符，超出则加省略号。"""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_memory_stats(args: argparse.Namespace) -> int:
    """显示记忆系统汇总统计。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.memory import ConversationMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    db_path = Path(args.db)
    conv = ConversationMemory(db_path).summary()
    ep = EpisodicMemory(db_path).summary()
    pred = PredictionTracker(db_path).stats()
    sem = SemanticMemory(db_path).summary()

    print("🧠 记忆系统统计")
    print("─" * 60)
    print(f"  数据库: {db_path}")
    print()
    print("对话记忆 (agent_memory):")
    print(f"  总条数: {conv['total']}  (user {conv['user']} / assistant {conv['assistant']})")
    print()
    print("事件记忆 (episodic_events):")
    print(f"  总条数: {ep['total']}")
    if ep.get("earliest"):
        print(f"  时间跨度: {ep['earliest'][:10]} ~ {ep['latest'][:10]}")
    if ep["by_type"]:
        print("  按类型:")
        for t, n in sorted(ep["by_type"].items(), key=lambda x: -x[1]):
            print(f"    {t}: {n}")
    print()
    print("预测追踪 (predictions):")
    print(
        f"  总数: {pred['total']}  "
        f"命中 {pred['hit']}  未中 {pred['missed']}  待验证 {pred['pending']}"
    )
    if pred["hit"] + pred["missed"] > 0:
        print(f"  命中率: {pred['hit_rate']:.1%}")
    print()
    print("知识记忆 (semantic_knowledge):")
    print(f"  总条数: {sem['total']}  (active {sem['active']} / superseded {sem['superseded']})")
    return 0


def cmd_memory_events(args: argparse.Namespace) -> int:
    """显示最近的结构化事件。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    em = EpisodicMemory(Path(args.db))
    events = em.recent(days=args.days, limit=args.limit)
    if not events:
        print("（暂无事件）")
        return 0
    print(f"📋 最近事件（{len(events)} 条）")
    print("─" * 80)
    print(f"{'时间':<21} {'类型':<18} {'代码':<8} {'摘要'}")
    print("─" * 80)
    for e in events:
        ts = str(e["timestamp"])[:19]
        etype = _truncate(e["event_type"], 18)
        code = e.get("code") or "—"
        summary = _truncate(e["summary"], 40)
        print(f"{ts:<21} {etype:<18} {code:<8} {summary}")
    return 0


def cmd_memory_predictions(args: argparse.Namespace) -> int:
    """显示最近的预测。"""
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(Path(args.db))
    preds = tracker.all(limit=args.limit, status=args.status)
    if not preds:
        print("（暂无预测）")
        return 0
    print(f"🎯 预测记录（{len(preds)} 条）")
    print("─" * 90)
    print(f"{'时间':<21} {'代码':<8} {'方向':<6} {'状态':<10} {'周期':<6} {'预测内容'}")
    print("─" * 90)
    for p in preds:
        ts = str(p.get("created_at", ""))[:19]
        code = p.get("code") or "—"
        direction = p.get("direction") or "—"
        status = p.get("status") or "—"
        timeframe = p.get("timeframe") or "—"
        prediction = _truncate(p.get("prediction") or "", 30)
        print(f"{ts:<21} {code:<8} {direction:<6} {status:<10} {timeframe:<6} {prediction}")
    return 0


def cmd_memory_knowledge(args: argparse.Namespace) -> int:
    """显示语义知识条目。"""
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    sm = SemanticMemory(Path(args.db))
    entries = sm.get_active(limit=args.limit)
    if not entries:
        print("（暂无知识条目）")
        return 0
    print(f"💡 知识记忆（{len(entries)} 条 active）")
    print("─" * 80)
    for e in entries:
        ktype = e.get("knowledge_type") or "—"
        scope = e.get("scope") or "—"
        content = _truncate(e.get("content") or "", 60)
        confidence = e.get("confidence", 0.0)
        print(f"  [{ktype}] {scope}")
        print(f"    {content}  (置信度 {confidence:.0%})")
    return 0


def cmd_memory_history(args: argparse.Namespace) -> int:
    """显示最近对话历史。"""
    from mommy_chaogu.agent.memory import ConversationMemory

    mem = ConversationMemory(Path(args.db))
    msgs = mem.recent(limit=args.limit)
    if not msgs:
        print("（暂无对话历史）")
        return 0
    print(f"💬 对话历史（最近 {len(msgs)} 条）")
    print("─" * 80)
    for m in msgs:
        ts = m["timestamp"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)[:19]
        role = m["role"]
        content = _truncate(m["content"], 60)
        print(f"{ts_str}  [{role}] {content}")
    return 0


def build_memory_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-memory",
        description="妈妈炒股 - 记忆系统查看（对话 / 事件 / 预测 / 知识）",
    )
    p.add_argument(
        "--db",
        default=str(AGENT_DB),
        help=f"记忆数据库路径 (默认 {AGENT_DB})",
    )

    sub = p.add_subparsers(dest="cmd")

    # stats（默认）
    p_stats = sub.add_parser("stats", help="汇总统计")
    p_stats.set_defaults(func=cmd_memory_stats)

    # events
    p_ev = sub.add_parser("events", help="最近结构化事件")
    p_ev.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_ev.add_argument("--days", type=int, default=90, help="只看最近 N 天 (默认 90)")
    p_ev.set_defaults(func=cmd_memory_events)

    # predictions
    p_pr = sub.add_parser("predictions", help="预测记录")
    p_pr.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_pr.add_argument(
        "--status",
        choices=["pending", "hit", "missed", "expired", "unverifiable"],
        default=None,
        help="按状态过滤",
    )
    p_pr.set_defaults(func=cmd_memory_predictions)

    # knowledge
    p_kn = sub.add_parser("knowledge", help="语义知识条目")
    p_kn.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_kn.set_defaults(func=cmd_memory_knowledge)

    # history
    p_hi = sub.add_parser("history", help="最近对话历史")
    p_hi.add_argument("--limit", "-n", type=int, default=20, help="最多显示 N 条 (默认 20)")
    p_hi.set_defaults(func=cmd_memory_history)

    return p


def main_memory() -> NoReturn:
    parser = build_memory_parser()
    args = parser.parse_args()
    # 无子命令时默认 stats
    if not getattr(args, "func", None):
        args.func = cmd_memory_stats
    rc = args.func(args)
    sys.exit(rc)
