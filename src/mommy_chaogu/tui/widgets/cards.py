"""对话流富卡片族（§1.2②）。

slash 命令与 agent 工具结果渲染共用的卡片构建器。全部是纯函数：
接收 plain dict/list 数据，返回带 rich markup 的 Static，样式类 ``card``
（border round）由 styles.tcss 提供。A 股约定红涨绿跌，色盲主题下绿→蓝。

卡片清单（10 种）：Overview / Quote / Bars / Flow（单只+多只）/ Watch /
Portfolio / Predictions / Signals / Memory / Status。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.markup import escape
from textual.widgets import Static

from mommy_chaogu.tui.services.formatting import (
    change_arrow,
    change_color,
    format_amount,
    format_change_pct,
    format_flow,
    format_price,
)

CARD_CLASS = "card"


def _text(value: Any) -> str:
    """把外部数据安全嵌入 Rich markup。"""
    return escape(str(value))


def _styled_change(val: Any, theme: str) -> str:
    """涨跌 → 带色 ▲/▼ + 百分比。"""
    color = change_color(val, theme)
    return f"[{color}]{change_arrow(val)} {format_change_pct(val)}[/{color}]"


def _styled_flow(val: Any, theme: str) -> str:
    """资金流 → 带色符号金额。"""
    color = change_color(val, theme)
    return f"[{color}]{format_flow(val)}[/{color}]"


def _card(lines: list[str], classes: str = CARD_CLASS) -> Static:
    return Static("\n".join(lines), classes=classes)


# ---------------------------------------------------------------------------
# Overview（/today 总览卡 + 启动欢迎卡共用数据形态）
# ---------------------------------------------------------------------------


def overview_card(
    indexes: list[dict[str, Any]],
    watch_total: int,
    watch_up: int,
    watch_down: int,
    signals_count: int,
    pending_predictions: int,
    theme: str = "dark",
) -> Static:
    """今日总览卡：指数 + 自选红绿 + 信号 N 条 + 待验证预测 N 条。"""
    lines: list[str] = ["[bold cyan]⏺ 今日总览[/]"]
    if indexes:
        idx_parts = []
        for idx in indexes[:3]:
            name = _text(idx.get("name", ""))
            pct = idx.get("change_pct")
            idx_parts.append(f"{name} {_styled_change(pct, theme)}")
        lines.append("  " + " · ".join(idx_parts))
    else:
        lines.append("  [dim]指数数据不可用[/]")
    if watch_total:
        lines.append(f"  自选 {watch_total} 只 [red]{watch_up} 红[/] [green]{watch_down} 绿[/]")
    else:
        lines.append("  [dim]还没有自选股（mommy watchlist add 600519）[/]")
    extras: list[str] = []
    if signals_count:
        extras.append(f"信号 {signals_count} 条")
    if pending_predictions:
        extras.append(f"待验证预测 {pending_predictions} 条")
    if extras:
        lines.append("  " + " · ".join(extras) + "（/signals · /predictions 查看）")
    return _card(lines, classes=f"{CARD_CLASS} overview-card")


# ---------------------------------------------------------------------------
# Quote（报价卡）
# ---------------------------------------------------------------------------


def quote_card(data: dict[str, Any], theme: str = "dark") -> Static:
    """报价卡：名称/代码 + 现价涨跌 + OHLC + 量额（+ 可选主力净流入）。

    data 字段与 agent tools 的 _quote_to_dict 对齐（slash /quote 也组装成同样形态）。
    """
    code = _text(data.get("code", ""))
    name = _text(data.get("name", code))
    price = data.get("price")
    pct = data.get("change_pct")
    lines = [
        f"[bold]{name}[/] [dim]{code}[/]  [bold]{format_price(price)}[/] "
        f"{_styled_change(pct, theme)}"
    ]
    lines.append(
        f"开 {format_price(data.get('open'))}  高 {format_price(data.get('high'))}  "
        f"低 {format_price(data.get('low'))}  昨收 {format_price(data.get('prev_close'))}"
    )
    volume = data.get("volume")
    turnover = data.get("turnover")
    extras: list[str] = []
    if data.get("turnover_rate") is not None:
        extras.append(f"换手 {float(data['turnover_rate']):.2f}%")
    if data.get("volume_ratio") is not None:
        extras.append(f"量比 {float(data['volume_ratio']):.2f}")
    lines.append(
        f"量 {format_amount(volume)}  额 {format_amount(turnover)}"
        + ("  " + "  ".join(extras) if extras else "")
    )
    main_flow = data.get("main_flow")
    if main_flow is not None:
        lines.append(f"主力净流入 {_styled_flow(main_flow, theme)}")
    return _card(lines, classes=f"{CARD_CLASS} quote-card")


# ---------------------------------------------------------------------------
# Bars（迷你 K 线表，≤10 行）
# ---------------------------------------------------------------------------


def bars_card(bars: list[dict[str, Any]], theme: str = "dark") -> Static:
    """迷你 K 线表：最近 ≤10 根，列 = 日期/收盘/涨跌/成交量。"""
    rows = bars[-10:]
    name = _text(rows[-1].get("name", "")) if rows else ""
    code = _text(rows[-1].get("code", "")) if rows else ""
    title = f"[bold cyan]{name}（{code}）近期走势[/]" if name or code else "[bold cyan]近期走势[/]"
    lines = [title, "  [dim]日期          收盘      涨跌      成交量[/]"]
    for b in rows:
        ts = _text(str(b.get("timestamp", ""))[:10])
        close = format_price(b.get("close"))
        pct = b.get("change_pct")
        vol = format_amount(b.get("volume"))
        lines.append(f"  {ts}  {close:>8}  {_styled_change(pct, theme)}  {vol:>8}")
    return _card(lines, classes=f"{CARD_CLASS} bars-card")


# ---------------------------------------------------------------------------
# Flow（资金流卡）
# ---------------------------------------------------------------------------


def flow_tool_card(data: dict[str, Any], theme: str = "dark") -> Static:
    """单只今日资金流卡（agent get_money_flow_today 单 code 返回形态）。"""
    code = _text(data.get("code", ""))
    name = _text(data.get("name", code))
    lines = [f"[bold cyan]💰 {name}（{code}）今日资金流[/]"]
    lines.append(f"  主力净流入 {_styled_flow(data.get('main_net'), theme)}")
    lines.append(
        f"  超大单 {_styled_flow(data.get('super_large_net'), theme)}  "
        f"大单 {_styled_flow(data.get('large_net'), theme)}"
    )
    lines.append(
        f"  中单 {_styled_flow(data.get('medium_net'), theme)}  "
        f"小单 {_styled_flow(data.get('small_net'), theme)}"
    )
    ratio = data.get("main_net_ratio")
    if ratio is not None:
        lines.append(f"  主力占比 {float(ratio):+.1f}%")
    return _card(lines, classes=f"{CARD_CLASS} flow-card")


def flow_multi_card(items: list[dict[str, Any]], theme: str = "dark") -> Static:
    """多只资金流对比卡（agent get_money_flow_today codes 列表返回形态）。"""
    lines = ["[bold cyan]💰 今日资金流对比[/]"]
    for item in items[:10]:
        if not isinstance(item, dict) or "error" in item:
            continue
        name = _text(item.get("name", item.get("code", "")))
        lines.append(f"  {name:<10} 主力 {_styled_flow(item.get('main_net'), theme)}")
    if len(lines) == 1:
        lines.append("  [dim]暂无数据[/]")
    return _card(lines, classes=f"{CARD_CLASS} flow-card")


def flows_command_card(code: str, info: dict[str, Any], theme: str = "dark") -> Static:
    """/flows <code> 命令卡：今日 + 近 N 日（FlowService.show 返回形态）。"""
    today = info.get("today")
    history = info.get("history")
    days = int(info.get("history_days_cached", 0) or 0)
    name = _text(getattr(today or history, "name", code))
    code = _text(code)

    def _summary_line(label: str, fs: Any) -> str:
        main = _styled_flow(getattr(fs, "main_net", None), theme)
        big = (
            _styled_flow(getattr(fs, "big_money_net", None), theme)
            if hasattr(fs, "big_money_net")
            else "—"
        )
        ratio = getattr(fs, "main_net_ratio", None)
        ratio_str = f"{float(ratio):+.1f}%" if ratio is not None else "—"
        return f"  {label}  主力 {main}  超大+大单 {big}  占比 {ratio_str}"

    lines = [f"[bold cyan]💰 {name}（{code}）资金流[/]"]
    if today is not None:
        lines.append(_summary_line("今日", today))
    if history is not None and days > 0:
        lines.append(_summary_line(f"近{days}日", history))
    if today is None and history is None:
        lines.append("  [dim]暂无资金流数据[/]")
    lines.append(f"  [dim]详细：mommy flows show {code}[/]")
    return _card(lines, classes=f"{CARD_CLASS} flow-card")


# ---------------------------------------------------------------------------
# Watch（自选股表格卡）
# ---------------------------------------------------------------------------


def watch_card(rows: list[dict[str, Any]], theme: str = "dark") -> Static:
    """自选股表格卡：名称/现价/涨跌/主力净流入。"""
    lines = ["[bold cyan]👀 自选股[/]", "  [dim]代码      名称        现价      涨跌       主力[/]"]
    unavailable = bool(rows) and all(r.get("quote_unavailable") for r in rows)
    for r in rows:
        code = _text(r.get("code", ""))
        name = _text(str(r.get("name", code))[:6])
        price = format_price(r.get("price"))
        pct = _styled_change(r.get("change_pct"), theme)
        flow = _styled_flow(r.get("main_flow"), theme)
        if r.get("quote_unavailable"):
            lines.append(f"  {code}  {name:<8}  [dim]行情暂不可用[/]")
        else:
            lines.append(f"  {code}  {name:<8}  {price:>8}  {pct}  {flow}")
    if not rows:
        lines.append("  [dim]还没有自选股（mommy watchlist add 600519）[/]")
    elif unavailable:
        lines.append("  [yellow]行情源暂时不可用，请稍后重试[/]")
    return _card(lines, classes=f"{CARD_CLASS} watch-card")


# ---------------------------------------------------------------------------
# Portfolio（持仓卡）
# ---------------------------------------------------------------------------


def portfolio_card(summary: dict[str, Any], theme: str = "dark") -> Static:
    """持仓卡：代码/成本/现价/浮盈亏 + 汇总行。"""
    positions = summary.get("positions", []) or []
    lines = ["[bold cyan]💼 持仓[/]"]
    mv = summary.get("total_market_value")
    pnl = summary.get("total_unrealized_pnl")
    pnl_pct = summary.get("total_unrealized_pnl_pct")
    summary_parts = [f"总市值 {format_amount(mv)}"]
    if pnl is not None:
        summary_parts.append(f"浮盈亏 {_styled_flow(pnl, theme)}")
    if pnl_pct is not None:
        summary_parts.append(f"({_styled_change(pnl_pct, theme)})")
    lines.append("  " + "  ".join(summary_parts))
    if positions:
        lines.append("  [dim]代码      名称        成本      现价      盈亏[/]")
        for p in positions:
            if isinstance(p, dict):
                position = p.get("position")
                code = p.get("code") or getattr(position, "code", "")
                name_value = p.get("name") or getattr(position, "name", None) or code
                code = _text(code)
                name = _text(str(name_value)[:6])
                cost = format_price(p.get("avg_cost") or p.get("cost_price"))
                price = format_price(p.get("current_price") or p.get("price"))
                pnl_val = p.get("unrealized_pnl")
            else:
                code = _text(getattr(p, "code", ""))
                name = _text(str(getattr(p, "name", code))[:6])
                cost = format_price(getattr(p, "cost_price", None))
                price = format_price(getattr(p, "current_price", None))
                pnl_val = getattr(p, "unrealized_pnl", None)
            lines.append(
                f"  {code}  {name:<8}  {cost:>8}  {price:>8}  {_styled_flow(pnl_val, theme)}"
            )
    else:
        lines.append("  [dim]还没有持仓记录（mommy portfolio add-position ...）[/]")
    return _card(lines, classes=f"{CARD_CLASS} portfolio-card")


# ---------------------------------------------------------------------------
# Predictions（预测跟踪卡）
# ---------------------------------------------------------------------------

_DIRECTION_LABEL = {"up": "📈 看涨", "down": "📉 看跌"}
_STATUS_LABEL = {
    "pending": "待验证",
    "hit": "✓ 命中",
    "missed": "✗ 未中",
    "expired": "已过期",
}


def _verify_countdown(verify_after: Any) -> str:
    """verify_after（ISO 字符串）→ 倒计时提示。"""
    if not verify_after:
        return ""
    try:
        target = datetime.fromisoformat(str(verify_after))
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        days = (target.date() - datetime.now(UTC).date()).days
    except ValueError:
        return ""
    if days > 0:
        return f"{days}d 后验证"
    if days == 0:
        return "今日待验证"
    return "已到验证期"


def prediction_lines(preds: list[dict[str, Any]], theme: str = "dark") -> list[str]:
    """预测记录行（/predictions 卡与工具结果卡共用）。"""
    lines: list[str] = []
    for p in preds:
        name = _text(p.get("name") or p.get("code", ""))
        direction = _DIRECTION_LABEL.get(str(p.get("direction", "")), "➡️  震荡")
        status = _text(
            _STATUS_LABEL.get(str(p.get("status", "")), str(p.get("status", "")))
        )
        tf = _text(p.get("timeframe", ""))
        countdown = _verify_countdown(p.get("verify_after")) if p.get("status") == "pending" else ""
        tail = f" · {countdown}" if countdown else ""
        pred_text = _text(str(p.get("prediction", ""))[:30])
        lines.append(f"  {name} {direction}（{tf}） {status}{tail}")
        if pred_text:
            lines.append(f"    [dim]{pred_text}[/]")
    return lines


def predictions_card(
    stats: dict[str, Any] | None,
    preds: list[dict[str, Any]],
    theme: str = "dark",
) -> Static:
    """预测跟踪卡：命中率汇总 + 近期预测（记忆能力露出）。"""
    lines = ["[bold cyan]🎯 预测跟踪[/]"]
    if stats:
        hit = stats.get("hit", 0)
        missed = stats.get("missed", 0)
        total_verified = hit + missed
        hit_rate = stats.get("hit_rate", 0)
        rate_str = f"{float(hit_rate):.0%}" if total_verified else "—"
        lines.append(
            f"  共 {stats.get('total', 0)} 条 · 命中 {hit}/{total_verified}（{rate_str}）"
            f" · 待验证 {stats.get('pending', 0)} 条"
        )
    if preds:
        lines.extend(prediction_lines(preds, theme))
    elif not stats:
        lines.append("  [dim]还没有预测记录[/]")
    lines.append("  [dim]详细：mommy memory predictions[/]")
    return _card(lines, classes=f"{CARD_CLASS} predictions-card")


def predictions_tool_card(preds: list[dict[str, Any]], theme: str = "dark") -> Static:
    """agent get_prediction_history 工具结果卡。"""
    lines = ["[bold cyan]🎯 预测记录[/]"]
    lines.extend(prediction_lines(preds[:8], theme) or ["  [dim]暂无记录[/]"])
    return _card(lines, classes=f"{CARD_CLASS} predictions-card")


# ---------------------------------------------------------------------------
# Signals（信号卡）
# ---------------------------------------------------------------------------

_SEVERITY_BADGE = {
    "critical": "[red]🔴 紧急[/]",
    "warning": "[yellow]⚠️  注意[/]",
    "info": "[#8a8f98]📊 提示[/]",
}


def signals_card(signals: list[dict[str, Any]], theme: str = "dark") -> Static:
    """信号卡：近期触发，中文严重度徽章。"""
    lines = ["[bold cyan]🚨 近期信号[/]"]
    if not signals:
        lines.append("  [dim]暂无信号记录[/]")
    for s in signals[:8]:
        badge = _SEVERITY_BADGE.get(str(s.get("severity", "")), "[#8a8f98]📊 提示[/]")
        ts = _text(str(s.get("timestamp", ""))[5:16])
        name = _text(s.get("name") or s.get("code", ""))
        title = _text(str(s.get("title", ""))[:28])
        lines.append(f"  {badge} {name} {title} [dim]{ts}[/]")
    return _card(lines, classes=f"{CARD_CLASS} signals-card")


# ---------------------------------------------------------------------------
# Memory（记忆统计卡）
# ---------------------------------------------------------------------------


def memory_card(
    memory_stats: dict[str, Any],
    theme: str = "dark",
) -> Static:
    """记忆统计卡：事件/预测/知识 + token 用量与估算成本。

    memory_stats 是 bootstrap 的可调用 dict：
    {episodic, predictions, semantic, tokens?, cost?}，每项为 callable。
    """

    def _call(key: str) -> Any:
        fn = memory_stats.get(key)
        if not callable(fn):
            return None
        try:
            return fn()
        except Exception:
            return None

    lines = ["[bold cyan]🧠 记忆系统[/]"]
    ep = _call("episodic")
    if ep:
        by_type = ", ".join(f"{_text(k)} {v}" for k, v in ep.get("by_type", {}).items())
        lines.append(f"  事件：{ep.get('total', 0)} 条（{by_type}）")
    pred = _call("predictions")
    if pred:
        hit = pred.get("hit", 0)
        missed = pred.get("missed", 0)
        rate = pred.get("hit_rate", 0)
        rate_str = f"{float(rate):.0%}" if (hit + missed) else "—"
        lines.append(
            f"  预测：{pred.get('total', 0)} 条  命中 {hit}/{hit + missed}"
            f"（{rate_str}）  待验证 {pred.get('pending', 0)}"
        )
    sem = _call("semantic")
    if sem:
        lines.append(f"  知识：{sem.get('total', 0)} 条（活跃 {sem.get('active', 0)}）")
    tokens = _call("tokens")
    if tokens and tokens.get("calls"):
        total = tokens.get("total_tokens", 0)
        cost = _call("cost")
        cost_str = ""
        if cost and cost.get("total_usd") is not None:
            cost_str = f" · 估算成本 ${float(cost['total_usd']):.4f}"
        lines.append(f"  Token：{total:,}（{tokens.get('calls', 0)} 次调用）{cost_str}")
    if len(lines) == 1:
        lines.append("  [dim]记忆系统不可用[/]")
    lines.append("  [dim]详细：mommy memory events / mommy memory predictions[/]")
    return _card(lines, classes=f"{CARD_CLASS} memory-card")


# ---------------------------------------------------------------------------
# Status（服务状态卡）
# ---------------------------------------------------------------------------


def status_card(
    ai_label: str,
    model: str | None,
    source_label: str,
    cache_counters: dict[str, int] | None,
    db_paths: dict[str, str],
    theme: str = "dark",
) -> Static:
    """服务状态卡：AI provider/key 状态、缓存命中、DB 路径。"""
    lines = ["[bold cyan]🔌 服务状态[/]"]
    lines.append(
        f"  AI：{_text(ai_label)}" + (f"（模型 {_text(model)}）" if model else "")
    )
    lines.append(f"  数据源：{_text(source_label or '未知')}")
    if cache_counters:
        hits = cache_counters.get("hits", 0)
        misses = cache_counters.get("miss", 0)
        total = hits + misses
        rate = f"{hits / total:.0%}" if total else "—"
        lines.append(f"  缓存：命中 {hits}/{total}（{rate}）")
    for label, path in db_paths.items():
        lines.append(f"  [dim]{_text(label)}: {_text(path)}[/]")
    return _card(lines, classes=f"{CARD_CLASS} status-card")


# ---------------------------------------------------------------------------
# Welcome（启动欢迎卡）
# ---------------------------------------------------------------------------


def welcome_text(
    indexes: list[dict[str, Any]] | None,
    watch_total: int | None,
    watch_up: int,
    watch_down: int,
    has_agent: bool,
    theme: str = "dark",
) -> str:
    """启动欢迎卡文本：今日指数 + 自选红绿摘要 + 提示语（无 agent 时降级说明）。

    indexes / watch_total 为 None 表示数据尚未到达（先渲染骨架）。
    """
    lines = ["[bold cyan]⏺ 欢迎使用妈妈炒股[/]"]
    summary: list[str] = []
    if indexes:
        idx_parts = []
        for idx in indexes[:3]:
            name = str(idx.get("name", ""))
            # 指数名取前两个字（上证指数→上证）保持紧凑
            short = _text(name.replace("指数", "")[:2] if name else "")
            idx_parts.append(f"{short} {_styled_change(idx.get('change_pct'), theme)}")
        summary.append("今日：" + " ".join(idx_parts))
    elif indexes is None:
        summary.append("今日指数加载中…")
    if watch_total:
        summary.append(f"自选 {watch_total} 只 [red]{watch_up} 红[/] [green]{watch_down} 绿[/]")
    if summary:
        lines.append("  " + "｜".join(summary))
    lines.append("  [dim]试试：今天大盘怎么样 · @茅台 · /today · /help[/]")
    if not has_agent:
        lines.append("  [yellow]AI 未配置：仅数据命令可用，配置见 .env[/]")
    return "\n".join(lines)
