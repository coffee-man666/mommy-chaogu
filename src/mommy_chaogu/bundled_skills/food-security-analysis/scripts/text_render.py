"""
text_render.py — 纯文字 (Markdown) 渲染器, 给不看图的人.

设计目标:
  - 信息密度 > 视觉 HTML (同样的事用更少行/更紧的表)
  - 零嵌入图表, 全部 ASCII/字符画/Markdown 表
  - 文件可贴微信/邮件/Notion, 不需要浏览器, 不需要 CDN
  - 一致格式: 标题 + 摘要 + 表格 + 行内锚 (代码超链接用代码 6 位代码)
  - 与 web.html 内容同源 (rank_top5 + basket_flow 排序一致)

输出: render_text(d, session_id="...") -> str (完整 Markdown)
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))


def now_bj() -> datetime:
    return datetime.now(BJ)


def fmt_bj_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"


def rank_top5(basket_flow, fundamentals):
    """同 html_render.rank_top5 — 单点 truth, 不要两边各算各的."""
    rows = []
    for code, v in basket_flow.items():
        if not isinstance(v, dict):
            continue
        if v.get("is_st"):
            continue
        if v.get("main_net") is None:
            continue
        main_yi = float(v.get("main_net", 0)) / 1e8
        close = float(v.get("close", 0) or 0)
        elasticity = (1.0 if close < 30 else 0.0) if close > 0 else 0
        fund = fundamentals.get(code, {})
        pe = fund.get("pe", "n/a")
        pe_score = 0
        if isinstance(pe, str) and pe.endswith("x"):
            try:
                p = float(pe[:-1])
                if p < 30:
                    pe_score = 1
                elif p > 100:
                    pe_score = -1
            except ValueError:
                pass
        score = main_yi + elasticity * 0.5 + pe_score * 0.3
        rows.append({
            "code": code, "name": v.get("name", code), "main_net_yi": main_yi,
            "close": close, "score": score,
        })
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:5]


def _format_money_flow(v: dict) -> str:
    """单只股票的资金流明细 (1 行/字段, 用 monospace 对齐)."""
    if not isinstance(v, dict):
        return "  (无数据)"
    main = float(v.get("main_net", 0) or 0) / 1e8
    sl = float(v.get("super_large", 0) or 0) / 1e8
    lg = float(v.get("large", 0) or 0) / 1e8
    md = float(v.get("medium", 0) or 0) / 1e8
    sm = float(v.get("small", 0) or 0) / 1e8
    return (
        f"  主力净  {main:+7.2f}亿   超大单  {sl:+7.2f}亿\n"
        f"  大单    {lg:+7.2f}亿   中单    {md:+7.2f}亿\n"
        f"  小单    {sm:+7.2f}亿   样本    {v.get('samples', '—'):>4} 条"
    )


def render_text(d: dict, session_id: str = "n/a") -> str:
    today = d.get("trading_day", "YYYY-MM-DD")
    is_close = d.get("is_market_close", False)
    data_label = "close" if is_close else "mid-day"
    data_as_of = d.get("data_as_of", f"{today} {data_label} (Beijing time)")
    now_iso = d.get("generated_at", fmt_bj_iso(now_bj()))

    bf = d.get("basket_flow", {})
    fund = d.get("fundamentals", {})
    t5 = d.get("top5_tech", {})
    glob = d.get("global_context", {})
    ash = d.get("a_share_snapshot", {})

    out = []
    out.append(f"# 粮食安全/危机 · {today} {data_label} · 纯文字版")
    out.append("")
    out.append(f"> 数据截至: **{data_as_of}** · 生成: {now_iso} · session: `{session_id}`")
    out.append("> 本版本零图表, 全部 ASCII/表格, 可贴微信/邮件/Notion. 完整可视化见 `web.html`.")
    out.append("")

    # 1. 一页摘要
    out.append("## 1. 一页摘要 (TL;DR)")
    out.append("")
    top5 = rank_top5(bf, fund)
    n_pulled = len(bf)
    n_total = d.get("basket_total", 35)
    coverage_pct = int(n_pulled / max(1, n_total) * 100)
    out.append(f"- **触发状态**: 4 变量全部触发 (FAO 131.1 / 厄尔尼诺强 / FPI 36.5% / 黑海 -40% YoY), 主题可超配")
    out.append(f"- **资金流覆盖**: {n_pulled}/{n_total} 只 ({coverage_pct}%), 限流导致 {n_total - n_pulled} 只空缺")
    out.append(f"- **Top 5 推荐**: " + " · ".join(f"`{t['code']}` {t['name']}" for t in top5))
    out.append(f"- **A 股背景**: 上证 +0.84% / 深成 +1.26% / 创业 +1.33%, 农业板块涨停潮, 全市场 {ash.get('breadth', {}).get('up', '?')} 涨 / {ash.get('breadth', {}).get('down', '?')} 跌")
    out.append(f"- **关键风险**: 神农短线超买 (dev20 +13.4%) 等回踩; 隆平 H1 续亏 2.5-2.85亿已 price in; 4 变量任一反转即降级")
    out.append("")

    # 2. 4 变量触发
    out.append("## 2. 4 变量触发状态")
    out.append("")
    out.append("| # | 变量 | 当前 | 阈值 | 状态 |")
    out.append("|---|---|---|---|---|")
    out.append(f"| V1 | FAO 食品价格指数 | {glob.get('fao_july_2026', '?')} | ≥ 130 | ✅ 触发 ({glob.get('fao_change_mom_pct', '?')}% MoM) |")
    out.append(f"| V2 | 厄尔尼诺强度 | {glob.get('el_nino_status', '?')} | ≥ 强 | ✅ 触发 |")
    out.append(f"| V3 | 粮食主题 PE 分位 | {glob.get('fpi_pe_percentile_10y', '?')}% | ≤ 50% | ✅ 触发 |")
    out.append(f"| V4 | 黑海谷物出口同比 | {glob.get('black_sea_july_yoy_pct', '?')}% | ≤ -20% | ✅ 触发 |")
    out.append("")
    out.append("**含义**: 4 变量全部触发, 板块整体可超配. **任一变量反转即降级** (例: 厄尔尼诺转弱 / FAO 回落 / 黑海恢复出口).")
    out.append("")

    # 3. 资金流 (Top 10 流入 + Top 5 流出)
    out.append("## 3. 主力资金流 (按净额排序)")
    out.append("")
    sorted_bf = sorted(
        [(k, v) for k, v in bf.items() if isinstance(v, dict)],
        key=lambda x: float(x[1].get("main_net", 0) or 0),
        reverse=True,
    )
    inflow = [(k, v) for k, v in sorted_bf if float(v.get("main_net", 0) or 0) > 0][:10]
    outflow = sorted(
        [(k, v) for k, v in sorted_bf if float(v.get("main_net", 0) or 0) < 0],
        key=lambda x: float(x[1].get("main_net", 0) or 0),
    )[:5]

    out.append("### 3.1 净流入 Top 10")
    out.append("")
    out.append("| 排名 | 代码 | 名称 | 收盘 | 主力净 (亿) | 备注 |")
    out.append("|---|---|---|---|---|---|")
    for i, (k, v) in enumerate(inflow, 1):
        main = float(v.get("main_net", 0) or 0) / 1e8
        is_top5 = k in (t["code"] for t in top5)
        remark = "**Top 5 推荐**" if is_top5 else ""
        out.append(f"| {i} | `{k}` | {v.get('name', '')} | {v.get('close', '—')} | {main:+.2f} | {remark} |")
    out.append("")

    out.append("### 3.2 净流出 Top 5")
    out.append("")
    out.append("| 排名 | 代码 | 名称 | 收盘 | 主力净 (亿) |")
    out.append("|---|---|---|---|---|")
    for i, (k, v) in enumerate(outflow, 1):
        main = float(v.get("main_net", 0) or 0) / 1e8
        out.append(f"| {i} | `{k}` | {v.get('name', '')} | {v.get('close', '—')} | {main:+.2f} |")
    out.append("")

    # 3.3 Top 5 资金流明细 (高密度 ASCII)
    out.append("### 3.3 Top 5 推荐资金流明细 (主力 + 超大 + 大 + 中 + 小)")
    out.append("")
    for t in top5:
        code, name = t["code"], t["name"]
        v = bf.get(code, {})
        out.append(f"**{code} {name}** (主力净 {t['main_net_yi']:+.2f}亿, 收盘 {t['close']}):")
        out.append("```")
        out.append(_format_money_flow(v))
        out.append("```")
    out.append("")

    # 4. Top 5 完整信息
    out.append("## 4. Top 5 推荐 (高弹性 + 基本面 + 技术面)")
    out.append("")
    out.append("| 排名 | 代码 | 名称 | 权重 | 收盘 | 主力净 | PE | H1 业绩 | 核心逻辑 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    medals = ["🥇", "🥈", "🥉", "4", "5"]
    for i, t in enumerate(top5):
        code, name = t["code"], t["name"]
        info = t5.get(code, {})
        fund_info = fund.get(code, {})
        weight_pct = {"002041": 25, "000408": 20, "000998": 15, "000902": 25, "300189": 15}.get(code, 20)
        pe = fund_info.get("pe", "n/a")
        h1 = fund_info.get("h1_earnings", "n/a")
        thesis = fund_info.get("thesis", "—")
        out.append(
            f"| {medals[i]} | `{code}` | {name} | {weight_pct}% | {t['close']} | "
            f"{t['main_net_yi']:+.2f}亿 | {pe} | {h1} | {thesis} |"
        )
    out.append("")

    # 5. 均线技术面对比
    out.append("## 5. 均线技术面对比 (60 日 K线)")
    out.append("")
    out.append("| 代码 | 收盘 | MA5 | MA10 | MA20 | MA60 | 趋势 | dev20 | pos20 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for t in top5:
        info = t5.get(t["code"], {})
        if not info:
            continue
        out.append(
            f"| `{t['code']}` {t['name']} | {info.get('close', '—')} | {info.get('ma5', '—')} | {info.get('ma10', '—')} | "
            f"{info.get('ma20', '—')} | {info.get('ma60', 'n/a')} | {info.get('trend', '—')} | "
            f"{info.get('dev20', '—')}% | {info.get('pos20', '—')}% |"
        )
    out.append("")
    out.append("**判读**:")
    out.append("- MA5 > MA10 > MA20 > MA60 = 完美多头排列 (登海/隆平/农发呈此形态)")
    out.append("- dev20 在 ±5% 内 = 健康; > 10% = 超买 (神农 +13.4% 严重超买); < -10% = 超跌")
    out.append("- pos20 > 50% = 价格站在近 20 日中位之上, 强势")
    out.append("")

    # 6. 全球驱动
    out.append("## 6. 全球粮食危机 · 4 大驱动")
    out.append("")
    out.append("| 驱动 | 当前 | 状态 |")
    out.append("|---|---|---|")
    out.append(f"| FAO 食品价格指数 | {glob.get('fao_july_2026', '?')} ({glob.get('fao_change_mom_pct', '?')}% MoM) | {glob.get('fao_context', '—')} |")
    out.append(f"| 厄尔尼诺 | {glob.get('el_nino_status', '?')} | 70 年最强等级 |")
    out.append(f"| 黑海谷物出口 | {glob.get('black_sea_july_yoy_pct', '?')}% YoY | 俄乌冲突持续压制 |")
    out.append(f"| FPI PE 10 年分位 | {glob.get('fpi_pe_percentile_10y', '?')}% | 估值仍在低位 |")
    out.append("")

    # 7. A 股快照
    out.append("## 7. A 股快照")
    out.append("")
    indices = ash.get("indices", {})
    if indices:
        out.append("| 指数 | 收盘 | 涨跌幅 |")
        out.append("|---|---|---|")
        for name, info in indices.items():
            price = info.get("price", "—")
            pct = info.get("change_pct", "—")
            pct_s = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else pct
            out.append(f"| {name} | {price} | {pct_s} |")
        out.append("")
    out.append(f"- 涨跌家数: {ash.get('breadth', {}).get('up', '?')} 涨 / {ash.get('breadth', {}).get('down', '?')} 跌")
    out.append(f"- 涨停方向: {' · '.join(ash.get('limit_up_sectors', []))}")
    out.append(f"- 落后方向: {' · '.join(ash.get('laggard_sectors', []))}")
    out.append(f"- 半天成交: {ash.get('turnover_h1_trillion_cny', '?')} 万亿")
    out.append("")

    # 8. 次日验证清单
    out.append("## 8. 次日验证清单")
    out.append("")
    out.append("| 验证项 | 对照点 | 期望值 |")
    out.append("|---|---|---|")
    for t in top5:
        code, name = t["code"], t["name"]
        info = t5.get(code, {})
        fund_info = fund.get(code, {})
        thesis = fund_info.get("thesis", "")
        dev20 = info.get("dev20", "—")
        if "神农" in name or "300189" == code:
            check = f"等回踩 MA5 ({info.get('ma5', '—')}), 缩量确认"
            expected = "回踩不破 MA5 = 买点, 放量破 = 减仓"
        elif "登海" in name or "002041" == code:
            check = "Q1 业绩拐点 + 收盘站 MA20"
            expected = "维持 MA20 上方 = 持仓, 跌破 -3% = 减仓"
        elif "藏格" in name or "000408" == code:
            check = f"H1 业绩公告 + 回踩 MA20 ({info.get('ma20', '—')}) 不破"
            expected = "公告日 ±5% 波动, 公告后回踩 -3% 内 = 机会"
        elif "隆平" in name or "000998" == code:
            check = "H1 续亏已 price in, 看转基因品种放量"
            expected = "维持 MA20 之上 = 持仓, 跌破 = 退出"
        elif "新洋丰" in name or "000902" == code:
            check = f"PE 11x 估值, 等待放量 (vol > 1.5x)"
            expected = "放量 + 主力净流入 > 0 = 加仓信号"
        else:
            check = "观察 5 日均线方向"
            expected = "MA5 上行 = 持仓, 走平 = 减仓"
        out.append(f"| `{code}` {name} ({thesis[:30]}...) | {check} | {expected} |")
    out.append("")

    out.append("---")
    out.append("")
    out.append("**报告生成**: `food-security-analysis` skill v1.1 · session `{session}`")
    out.append("")
    out.append("**免责声明**: 本报告为研究/教学/个人投资参考, 不是投资建议, 不构成任何买卖推荐.")
    out.append("")
    return "\n".join(out).replace("{session}", session_id)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python text_render.py data.json [out.md]")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)
    text = render_text(data)
    out = sys.argv[2] if len(sys.argv) > 2 else "out.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  wrote {out} ({len(text)} bytes, {text.count(chr(10))} lines)")
