"""监控输出格式化。

输出两种格式：
- format_table：人类可读的表格（控制台刷新用）
- format_log_line：单行紧凑格式（追加到日志文件）

不做富文本（rich/tabulate 依赖），保持 vanilla print 风格，避免动妈妈机器上的字体。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mommy_chaogu.monitor.poller import Snapshot


def _fmt_money(amount: Decimal, unit: str = "元") -> str:
    """金额紧凑格式。>=1亿显示 'X.XX亿'，>=1万显示 'X.XX万'，否则 'X.XX元'。"""
    a = float(amount)
    if abs(a) >= 1e8:
        return f"{a / 1e8:+.2f}亿"
    if abs(a) >= 1e4:
        return f"{a / 1e4:+.2f}万"
    return f"{a:+.2f}{unit}"


def _fmt_pct(p: Decimal | None) -> str:
    if p is None:
        return "—"
    return f"{float(p):+.2f}%"


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    return ts.strftime("%H:%M")


def format_table(snapshot: Snapshot) -> str:
    """格式化为定宽表格。"""
    lines: list[str] = []
    lines.append(
        f"📊 自选股快照 @ {snapshot.timestamp:%Y-%m-%d %H:%M:%S}  "
        f"共 {snapshot.n_codes} 只  "
        f"↑{snapshot.n_up} ↓{snapshot.n_down} —{snapshot.n_flat}  "
        f"主力净流入 {_fmt_money(snapshot.total_main_net)}"
    )
    lines.append("")
    if not snapshot.rows:
        lines.append("（自选股池为空，先 watchlist add 几只股票）")
        return "\n".join(lines)

    # 表头
    header = (
        f"{'代码':<8} {'名称':<10} {'分组':<8} {'现价':>10} "
        f"{'涨跌幅':>8} {'量':>12} {'主力净流入':>14} {'时间':>8}"
    )
    lines.append(header)
    lines.append("─" * len(header))

    for row in snapshot.rows:
        q = row.quote
        flow = row.latest_flow
        flow_amt = flow.main_net.amount if flow is not None else None
        flow_ts = flow.timestamp if flow is not None else None
        lines.append(
            f"{q.code:<8} {q.name[:10]:<10} {row.group_name:<8} "
            f"{q.price:>10} {_fmt_pct(q.change_pct):>8} "
            f"{q.volume:>12,} "
            f"{_fmt_money(flow_amt) if flow_amt is not None else '—':>14} "
            f"{_fmt_ts(flow_ts):>8}"
        )

    return "\n".join(lines)


def format_log_line(snapshot: Snapshot) -> str:
    """单行紧凑格式，适合追加到日志文件。

    例：[2026-06-26 12:30:00] snapshot  6 codes  ↑2 ↓3 —1  主力+5.2亿  rows=[600519:1184.98(+0.08%) 主力-3.6亿, ...]
    """
    parts = [
        f"[{snapshot.timestamp:%Y-%m-%d %H:%M:%S}]",
        f"snapshot #{snapshot.snapshot_id}",
        f"codes={snapshot.n_codes}",
        f"↑{snapshot.n_up} ↓{snapshot.n_down} —{snapshot.n_flat}",
        f"主力净流入={_fmt_money(snapshot.total_main_net)}",
    ]
    if snapshot.rows:
        row_strs = [
            f"{r.quote.code}:{r.quote.price}({_fmt_pct(r.quote.change_pct)})"
            + (
                f" 主力{_fmt_money(r.latest_flow.main_net.amount)}"
                if r.latest_flow is not None
                else ""
            )
            for r in snapshot.rows
        ]
        parts.append("rows=[" + ", ".join(row_strs) + "]")
    return " ".join(parts)
