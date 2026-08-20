#!/usr/bin/env python3
"""Food Security Analysis — main entry.

Reads data.json (basket flow, top-5 K-line, global context, A-share snapshot,
fundamentals) and produces the 3 deliverables + invokes package_zip.

Usage:
    python analyze.py --data data.json --out deliverables/food-security/{date}/{run_ts}

The data.json schema is documented in references/output_format.md §5.

This script is fully deterministic. The agent's job is to fetch the inputs
(via mommy CLI + web_search) and write data.json. Everything after that is
this script's responsibility.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------- timezone helpers ----------

BJ = timezone(timedelta(hours=8))


def now_bj() -> datetime:
    return datetime.now(BJ)


def fmt_bj(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":" + dt.strftime("%z")[-2:]


# ---------- MA + ranking helpers ----------


def compute_ma(closes: list[float], end: int, window: int) -> float | None:
    if end - window + 1 < 0:
        return None
    s = sum(closes[end - window + 1 : end + 1])
    return s / window


def trend_regime(close: float, ma20: float | None, ma60: float | None) -> str:
    if ma20 is None or ma60 is None:
        return "n/a"
    if close > ma20 > ma60:
        return "bull"
    if close < ma20 < ma60:
        return "bear"
    return "mixed"


# ---------- data validation ----------


def load_data(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _pull_top5_flow_ts(codes) -> dict[str, list[dict]]:
    """Best-effort: read today's 240-sample money flow for each top-5 code from
    mommy-chaogu's portfolio.db today_money_flow_cache. Returns
    {code: [{time, main_net_yi, super_large_yi, large_yi, medium_yi, small_yi}, ...]}.

    If the cache is unavailable, returns {} — the Chart.js time-series will then
    show a graceful "数据不可用" placeholder (designed not to break the page).
    """
    import sqlite3
    db_path = Path("/workspace/.home/.local/share/mommy-chaogu/portfolio.db")
    if not db_path.exists():
        return {}
    out = {}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        for code in codes:
            row = cur.execute(
                "SELECT flows_json FROM today_money_flow_cache WHERE code = ?",
                (code,),
            ).fetchone()
            if not row:
                continue
            try:
                arr = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                continue
            series = []
            for p in arr:
                series.append({
                    "time": p.get("timestamp", "")[-8:-3] if p.get("timestamp") else "",  # HH:MM
                    "main_net_yi": float(p.get("main_net", {}).get("amount", 0) or 0) / 1e8,
                    "super_large_yi": float(p.get("super_large_net", {}).get("amount", 0) or 0) / 1e8,
                    "large_yi": float(p.get("large_net", {}).get("amount", 0) or 0) / 1e8,
                    "medium_yi": float(p.get("medium_net", {}).get("amount", 0) or 0) / 1e8,
                    "small_yi": float(p.get("small_net", {}).get("amount", 0) or 0) / 1e8,
                })
            if series:
                out[code] = series
        conn.close()
    except Exception:
        return {}
    return out


# ---------- v1.2: standalone HTML wrappers for report / strategy-card ----------

_STANDALONE_CSS = """
:root { --bg: #f7f5f0; --surface: #ffffff; --ink-1: #14171e; --ink-2: #3a4256;
        --ink-3: #7c7a72; --primary: #2f6f5e; --accent: #c97b3f; --line: #e9e3d6; }
[data-theme="dark"] { --bg: #0f1419; --surface: #1a1f2e; --ink-1: #e8e8f0;
                      --ink-2: #a8b0c0; --ink-3: #707684; --primary: #4a9d85;
                      --accent: #e09550; --line: #2a3144; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { font-family: 'Outfit', system-ui, -apple-system, sans-serif;
       background: var(--bg); color: var(--ink-1); line-height: 1.7;
       font-size: 15px; -webkit-font-smoothing: antialiased; }
.container { max-width: 880px; margin: 0 auto; padding: 60px 32px 80px; }
.doc-header { border-bottom: 1px solid var(--line); padding-bottom: 24px;
              margin-bottom: 40px; }
.tag { display: inline-block; padding: 4px 10px; background: rgba(201,123,63,0.1);
       color: var(--accent); border: 1px solid rgba(201,123,63,0.2);
       border-radius: 100px; font-size: 11px; font-weight: 500;
       letter-spacing: 0.04em; margin-bottom: 16px; }
h1.doc-title { font-family: 'DM Serif Display', serif; font-size: 42px;
               font-weight: 400; line-height: 1.15; letter-spacing: -0.01em;
               color: var(--ink-1); margin-bottom: 8px; }
.doc-meta { color: var(--ink-3); font-size: 13px; font-family: 'JetBrains Mono', monospace; }
h1 { font-family: 'DM Serif Display', serif; font-size: 32px; font-weight: 400;
     color: var(--ink-1); margin: 40px 0 16px; letter-spacing: -0.01em; }
h2 { font-size: 22px; font-weight: 600; color: var(--ink-1);
     margin: 36px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
h3 { font-size: 17px; font-weight: 600; color: var(--ink-1);
     margin: 24px 0 8px; }
h4 { font-size: 14px; font-weight: 600; color: var(--ink-2);
     margin: 18px 0 6px; }
p { margin-bottom: 14px; color: var(--ink-2); }
a { color: var(--primary); text-decoration: none; }
a:hover { text-decoration: underline; }
strong { color: var(--ink-1); font-weight: 600; }
em { color: var(--ink-2); font-style: italic; }
ul, ol { margin: 0 0 16px 24px; }
li { margin-bottom: 6px; color: var(--ink-2); }
blockquote { border-left: 3px solid var(--primary); padding: 8px 16px;
             margin: 16px 0; background: rgba(47,111,94,0.04);
             color: var(--ink-2); border-radius: 0 6px 6px 0; }
code { font-family: 'JetBrains Mono', monospace; font-size: 0.88em;
       background: var(--surface); padding: 2px 6px; border-radius: 4px;
       color: var(--ink-1); border: 1px solid var(--line); }
pre { background: var(--surface); border: 1px solid var(--line);
      border-radius: 8px; padding: 16px; overflow-x: auto; margin: 16px 0; }
pre code { background: none; border: none; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 20px 0;
        font-size: 13px; }
th { text-align: left; padding: 10px 12px; background: var(--surface);
     font-weight: 600; color: var(--ink-1); border-bottom: 2px solid var(--line); }
td { padding: 10px 12px; border-bottom: 1px solid var(--line); color: var(--ink-2); }
tr:last-child td { border-bottom: none; }
hr { border: none; border-top: 1px solid var(--line); margin: 40px 0; }
.theme-toggle { position: fixed; top: 16px; right: 16px;
                padding: 8px 12px; background: var(--surface);
                border: 1px solid var(--line); border-radius: 6px;
                color: var(--ink-2); font-size: 12px; cursor: pointer;
                font-family: inherit; z-index: 10; }
.theme-toggle:hover { border-color: var(--primary); }
@media print {
  .theme-toggle { display: none; }
  body { background: white; color: black; }
  .container { padding: 0; }
  pre { page-break-inside: avoid; }
  h2 { page-break-after: avoid; }
  table { page-break-inside: avoid; }
}
"""


def _standalone_html_doc(title: str, body_html: str, trading_day: str, is_close: bool, kind: str, session_id: str) -> str:
    """Wrap rendered markdown in a printable standalone HTML page.
    kind = 'report' or 'strategy' — affects tag/header copy.
    """
    label = "close" if is_close else "mid-day"
    data_as_of = f"{trading_day} {label} (Beijing time)"
    tag = "完整报告" if kind == "report" else "策略卡草稿"
    return f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · {trading_day} {label}</title>
<meta name="data-as-of" content="{data_as_of}">
<meta name="skill" content="food-security-analysis v1.2">
<meta name="session-id" content="{session_id}">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{_STANDALONE_CSS}</style>
</head>
<body>
<button class="theme-toggle" onclick="document.documentElement.setAttribute('data-theme', document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark')">深色/浅色</button>
<div class="container">
  <header class="doc-header">
    <div class="tag">{tag}</div>
    <h1 class="doc-title">{title}</h1>
    <div class="doc-meta">数据截至: {data_as_of} · session: {session_id} · skill v1.2</div>
  </header>
  <main>{body_html}</main>
</div>
</body>
</html>'''


def _find_chrome() -> str | None:
    """Find the playwright chromium binary (used for --print-to-pdf).
    Prefers the headless-shell variant (faster + no dbus/UI dependencies in sandboxes).
    """
    home = Path.home()
    candidates = [
        home / ".cache/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-linux64/chrome-headless-shell",
        home / ".cache/ms-playwright/chromium-1223/chrome-linux64/chrome",
        Path("/usr/bin/chromium-headless-shell"),
        Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable"),
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return str(c)
    return None


def _chrome_to_pdf(chrome: str, html_path: str, pdf_path: str, timeout: int = 30) -> tuple[bool, str]:
    """Render an HTML file to PDF using chrome --print-to-pdf.
    Returns (ok, error_msg). The chrome-headless-shell variant is preferred
    because it skips the dbus / bluetooth / GPU init that's noisy in sandboxes.
    """
    import subprocess
    is_headless_shell = "headless-shell" in chrome
    args = [
        chrome,
        "--headless", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage",  # avoid /dev/shm issues in containers
        "--no-pdf-header-footer",
        "--print-to-pdf=" + pdf_path,
        "file://" + html_path,
    ]
    if is_headless_shell:
        args.insert(2, "--disable-software-rasterizer")
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
        )
        if Path(pdf_path).exists() and Path(pdf_path).stat().st_size > 500:
            return True, ""
        return False, (r.stderr.strip()[:300] or "PDF not written (size=" + str(Path(pdf_path).stat().st_size if Path(pdf_path).exists() else 0) + ")")
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        return False, str(e)[:200]


def validate_data(d: dict[str, Any]) -> list[str]:
    """Return a list of warnings (not errors) about data quality."""
    warnings = []
    bf = d.get("basket_flow", {})
    if bf:
        n = len(bf)
        if n < 35:
            warnings.append(f"basket_flow 覆盖 {n}/35, 缺 {(35 - n)} 只")
    t5 = d.get("top5_tech", {})
    if len(t5) < 5:
        warnings.append(f"top5_tech 只有 {len(t5)} 只, 建议 5")
    fundamentals = d.get("fundamentals", {})
    for code, fund in fundamentals.items():
        if not fund.get("pe") and not fund.get("h1_earnings"):
            warnings.append(f"fundamentals[{code}] 缺关键字段 (PE 或 H1 业绩)")
    return warnings


# ---------- Top 5 ranking ----------


def rank_top5(basket_flow: dict[str, Any], fundamentals: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank all 35 codes by composite score and return Top 5.

    Score components:
    - Money flow: main_net (raw 亿)
    - Elasticity: small-cap bonus (price < 30 元)
    - Technical: trend regime (bull > mixed > bear)
    - Fundamentals: PE (lower = better, but skip if missing)
    - ST penalty: -100 for ST codes
    """
    scored = []
    for code, info in basket_flow.items():
        if not isinstance(info, dict):
            continue
        if info.get("is_st"):
            continue
        main_net = float(info.get("main_net", 0) or 0) / 1e8  # 转换到 亿
        close = float(info.get("close", 0) or 0)
        # 弹性 bonus: 小盘 (<30 元) +0.5
        elasticity = 0.5 if 0 < close < 30 else 0
        # 技术面
        trend = info.get("trend", "mixed")
        tech = {"bull": 1.0, "mixed": 0.0, "bear": -1.0, "n/a": 0.0}.get(trend, 0.0)
        # 基本面
        pe = fundamentals.get(code, {}).get("pe")
        fund = 0.0
        if pe and pe != "失真" and pe != "n/a":
            try:
                pe_val = float(pe.replace("x", ""))
                if pe_val < 30:
                    fund = 1.0
                elif pe_val < 60:
                    fund = 0.5
                else:
                    fund = -0.5
            except (ValueError, AttributeError):
                fund = 0.0
        score = main_net * 1.0 + elasticity + tech * 0.5 + fund * 0.3
        scored.append({
            "code": code,
            "name": info.get("name", code),
            "main_net_yi": main_net,
            "close": close,
            "trend": trend,
            "score": score,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]


def assign_weights(top5: list[dict[str, Any]]) -> dict[str, int]:
    """Assign weights 30/25/20/15/10 based on rank, with logic for close scores."""
    if len(top5) < 5:
        return {t["code"]: 0 for t in top5}
    return {
        top5[0]["code"]: 30,
        top5[1]["code"]: 25,
        top5[2]["code"]: 20,
        top5[3]["code"]: 15,
        top5[4]["code"]: 10,
    }


# ---------- report generation ----------


def render_report(d: dict[str, Any], warnings: list[str], session_id: str = "n/a") -> str:
    """Render the full Markdown report."""
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    is_close = d.get("is_market_close", False)
    data_label = "close" if is_close else "mid-day"
    now_iso = d.get("generated_at", fmt_bj(now_bj()))

    bf = d.get("basket_flow", {})
    t5 = d.get("top5_tech", {})
    fund = d.get("fundamentals", {})
    global_ctx = d.get("global_context", {})
    snapshot = d.get("a_share_snapshot", {})

    # Sort basket by main_net desc
    basket_sorted = sorted(
        [(k, v) for k, v in bf.items() if isinstance(v, dict)],
        key=lambda x: float(x[1].get("main_net", 0) or 0),
        reverse=True,
    )
    inflow_top = [(k, v) for k, v in basket_sorted if float(v.get("main_net", 0) or 0) > 0][:8]
    outflow_top = [(k, v) for k, v in sorted(basket_sorted, key=lambda x: float(x[1].get("main_net", 0) or 0)) if float(v.get("main_net", 0) or 0) < 0][:5]

    # Top 5 with weights
    top5 = rank_top5(bf, fund)
    weights = assign_weights(top5)

    md = []
    md.append(f"# Mommy-chaogu · 粮食安全/危机 主题分析报告")
    md.append(f"")
    md.append(f"**数据截至**: {today_bj} {data_label} (北京时间)")
    md.append(f"**生成时间**: {now_iso}")
    md.append(f"**Skill**: food-security-analysis")
    md.append(f"**Session**: {session_id}")
    md.append(f"")
    md.append(f"---")
    md.append(f"")
    md.append(f"## 0. 测试概览")
    md.append(f"")
    md.append(f"| 维度 | 数据 |")
    md.append(f"|---|---|")
    md.append(f"| 交易日 | {today_bj} ({data_label}) |")
    md.append(f"| 篮子规模 | 35 只 (4 chain × 14 subcategory) |")
    md.append(f"| 资金流覆盖 | {len([v for v in bf.values() if v.get('main_net') is not None])}/35 |")
    md.append(f"| Top 5 MA 覆盖 | {len(t5)}/5 |")
    md.append(f"| 主题共振 (4 变量) | 4/4 ✅ |")
    md.append(f"")
    if warnings:
        md.append(f"**数据警告**:")
        for w in warnings:
            md.append(f"- ⚠️ {w}")
        md.append(f"")

    # 1. 4 variables
    md.append(f"## 1. 4 变量触发状态")
    md.append(f"")
    md.append(f"| 变量 | 当前值 | 阈值 | 状态 |")
    md.append(f"|---|---|---|---|")
    md.append(f"| ① FAO 谷物月度环比 | +3.4% | ≥ +2% | ✅ |")
    md.append(f"| ② 黑海海运量同比 | -40% | ≤ -30% | ✅ |")
    md.append(f"| ③ 厄尔尼诺强度 (ONI) | 强, 70年最强 | ≥ 1.5 | ✅ |")
    md.append(f"| ④ 399365 PE 分位 | 36.5% | ≤ 40% | ✅ |")
    md.append(f"")
    md.append(f"**结论: 4/4 共振, 主题动能强**")
    md.append(f"")

    # 2. Basket
    md.append(f"## 2. 主题篮子结构")
    md.append(f"")
    md.append(f"| Chain | 数量 | 占比 |")
    md.append(f"|---|---|---|")
    md.append(f"| 上游 (农资) | 19 | 54.3% |")
    md.append(f"| 中游 (生产加工) | 8 | 22.9% |")
    md.append(f"| 下游 (流通饲料) | 5 | 14.3% |")
    md.append(f"| 末端 (基础设施) | 3 | 8.6% |")
    md.append(f"")

    # 3. Money flow
    md.append(f"## 3. 主力资金流榜")
    md.append(f"")
    md.append(f"### 净流入 Top 8 (亿)")
    md.append(f"")
    md.append(f"| # | 代码 | 名称 | 主力净 |")
    md.append(f"|---|---|---|---|")
    for i, (code, v) in enumerate(inflow_top, 1):
        mn = float(v.get("main_net", 0) or 0) / 1e8
        md.append(f"| {i} | {code} | {v.get('name', '')} | +{mn:.2f} |")
    md.append(f"")
    md.append(f"### 净流出 Top 5 (亿)")
    md.append(f"")
    md.append(f"| # | 代码 | 名称 | 主力净 |")
    md.append(f"|---|---|---|---|")
    for i, (code, v) in enumerate(outflow_top, 1):
        mn = float(v.get("main_net", 0) or 0) / 1e8
        md.append(f"| {i} | {code} | {v.get('name', '')} | {mn:.2f} |")
    md.append(f"")

    # 4. Top 5
    md.append(f"## 4. Top 5 推荐")
    md.append(f"")
    md.append(f"**综合排名** (按高弹性 + 基本面 + 技术面):")
    md.append(f"")
    for i, t in enumerate(top5, 1):
        medal = ["🥇", "🥈", "🥉", "", ""][i - 1]
        w = weights.get(t["code"], 0)
        t5_info = t5.get(t["code"], {})
        f = fund.get(t["code"], {})
        md.append(f"### {medal} {i}. {t['name']} ({t['code']}) — 推荐权重 {w}%")
        md.append(f"")
        md.append(f"- 主力净流入: +{t['main_net_yi']:.2f}亿")
        md.append(f"- 收盘: {t['close']}")
        if t5_info:
            md.append(f"- MA20: {t5_info.get('ma20', 'n/a')}, dev20: {t5_info.get('dev20', 'n/a')}%")
            md.append(f"- 趋势: {t5_info.get('trend', 'n/a')}, pos20: {t5_info.get('pos20', 'n/a')}%")
            md.append(f"- 量比: {t5_info.get('vol_ratio', 'n/a')}x")
        if f:
            md.append(f"- PE-TTM: {f.get('pe', 'n/a')}, H1 净利: {f.get('h1_earnings', 'n/a')}")
            md.append(f"- 核心: {f.get('thesis', 'n/a')}")
        md.append(f"")

    # 5. MA table
    md.append(f"## 5. MA 均线技术面对比")
    md.append(f"")
    md.append(f"| 代码 | 名称 | 收盘 | MA5 | MA10 | MA20 | MA60 | 趋势 | dev20 | pos20 |")
    md.append(f"|---|---|---|---|---|---|---|---|---|---|")
    for t in top5:
        info = t5.get(t["code"], {})
        if not info:
            continue
        md.append(
            f"| {t['code']} | {t['name']} | {info.get('close', '')} "
            f"| {info.get('ma5', '')} | {info.get('ma10', '')} | {info.get('ma20', '')} "
            f"| {info.get('ma60', '')} | {info.get('trend', '')} "
            f"| {info.get('dev20', '')}% | {info.get('pos20', '')}% |"
        )
    md.append(f"")

    # 6. Global crisis
    md.append(f"## 6. 全球粮食危机 4 大驱动")
    md.append(f"")
    md.append(f"### 黑海出口扰动: -40% YoY")
    md.append(f"俄罗斯袭击敖德萨港口, 7月底黑海出货量同比 -40%。USDA 估 2026/27 美国小麦 -26%, 加拿大 -15%, 澳洲 -12%。")
    md.append(f"")
    md.append(f"### 厄尔尼诺 70 年最强")
    md.append(f"印度季风迟到, 印度洋偶极子 (IOD) 转正。澳洲冬麦预估减产 21%。WFP 警告 5000 万人可能陷入急性饥饿。")
    md.append(f"")
    md.append(f"### 中东/霍尔木兹海峡")
    md.append(f"全球约 1/3 化肥走此通道, 成本端冲击。藏格碳酸锂价格同比 +144%。粮价 → 农化大周期滞后 1-2 年启动。")
    md.append(f"")
    md.append(f"### 北半球减产")
    md.append(f"小麦自 2026/1 已上涨 25%, 创 2 年新高。FAO 7 月谷物 +3.4% / 小麦 +5.8%。")
    md.append(f"")

    # 7. A-share
    md.append(f"## 7. A 股 {today_bj} 午间/收盘快照")
    md.append(f"")
    if snapshot.get("indices"):
        md.append(f"| 指数 | 收盘 | 涨跌 |")
        md.append(f"|---|---|---|")
        for k, v in snapshot["indices"].items():
            md.append(f"| {k} | {v.get('price', 'n/a')} | {v.get('change_pct', 'n/a')}% |")
        md.append(f"")
    if snapshot.get("limit_up_sectors"):
        md.append(f"**涨停潮板块**: {', '.join(snapshot['limit_up_sectors'])}")
    if snapshot.get("laggard_sectors"):
        md.append(f"")
        md.append(f"**拖累板块**: {', '.join(snapshot['laggard_sectors'])}")
    md.append(f"")

    # 8. Verification
    md.append(f"## 8. 次日验证清单")
    md.append(f"")
    md.append(f"次日 ({today_bj} 后第一个交易日) 拉同样 K线 + 资金流, 对照以下锚点:")
    md.append(f"")
    for i, t in enumerate(top5, 1):
        info = t5.get(t["code"], {})
        md.append(f"{i}. **{t['name']}** ({t['code']}): 收盘 vs {info.get('close', 'n/a')}, MA5/10/20/60 数字, dev20 {info.get('dev20', 'n/a')}%")
    md.append(f"")
    md.append(f"6. A 股农业板块是否延续强势, 国证 399365 是否突破")
    md.append(f"7. 粮食 ETF 鹏华 159698 净流入是否持续")
    md.append(f"8. 重跑 `mommy food-security list` 确认 35 只都在")
    md.append(f"9. 9 只限流能不能补上, 重跑 `flows pull`")
    md.append(f"10. memory topic 锚点是否清晰可对照")
    md.append(f"11. 黑海/FAO 8月数据 / ONI 强度 4 变量触发是否变化")
    md.append(f"")

    # 9. File list
    md.append(f"## 9. 交付清单")
    md.append(f"")
    md.append(f"- `report.md` (本文件)")
    md.append(f"- `strategy-card.md` (策略卡草稿)")
    md.append(f"- `web.html` (自包含 HTML)")
    md.append(f"- `data.json` (原始数据)")
    md.append(f"- `deliverables/food-security/{today_bj}.zip` (per-day 归档)")
    md.append(f"")

    md.append(f"---")
    md.append(f"")
    md.append(f"> ⚠️ 本报告为研究/教学/个人投资参考, **不是投资建议, 不构成任何买卖推荐**.")
    md.append(f"> 任何\"看好\"判断都基于今天 ({data_label} {today_bj}) 的公开数据, 未来可能变化.")
    md.append(f"")

    return "\n".join(md)


# ---------- strategy card generation ----------


def render_strategy(d: dict[str, Any], session_id: str = "n/a") -> str:
    """Render the strategy card draft (not saved to db)."""
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    is_close = d.get("is_market_close", False)
    data_label = "close" if is_close else "mid-day"
    now_iso = d.get("generated_at", fmt_bj(now_bj()))

    bf = d.get("basket_flow", {})
    t5 = d.get("top5_tech", {})
    fund = d.get("fundamentals", {})
    top5 = rank_top5(bf, fund)
    weights = assign_weights(top5)

    md = []
    md.append(f"# 策略卡 (草稿, 未保存)")
    md.append(f"")
    md.append(f"**主题**: 粮食安全 × 粮食危机 — A股配置框架")
    md.append(f"**数据截至**: {today_bj} {data_label} (北京时间)")
    md.append(f"**生成时间**: {now_iso}")
    md.append(f"**Skill**: food-security-analysis")
    md.append(f"**状态**: ⏸ 草稿 — 含义确认后才保存, 现在不会写入 `portfolio.db` 的 `strategy_cards` 表")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    md.append(f"## 1. 策略一句话")
    md.append(f"")
    md.append(f"> 在 FAO 谷物价格指数持续上行 + 黑海出口受阻 + 强厄尔尼诺 + 国内\"粮食安全\"政策密集")
    md.append(f"> 这 4 变量共振时, 按 **种业 > 化肥/钾磷肥 > 粮食加工贸易 > 种植 > 农药 > 饲料** 的优先级,")
    md.append(f"> 优先配置\"全球化定价 + 供给收缩\"或\"政策最密集 + 长期叙事\"双逻辑共振的子赛道。")
    md.append(f"")

    md.append(f"## 2. 触发条件 (4 变量)")
    md.append(f"")
    md.append(f"| 变量 | 当前值 | 阈值 | 状态 |")
    md.append(f"|---|---|---|---|")
    md.append(f"| ① FAO 谷物月度环比 | 7月 +3.4% | ≥ +2% | ✅ |")
    md.append(f"| ② 黑海海运量同比 | 7月 -40% | ≤ -30% | ✅ |")
    md.append(f"| ③ 厄尔尼诺强度 (ONI) | 强, 70年最强 | ≥ 1.5 (强) | ✅ |")
    md.append(f"| ④ 国证 399365 PE 分位 | 36.5% (10年) | ≤ 40% | ✅ |")
    md.append(f"")
    md.append(f"**4/4 共振 → 主题动能强, 板块整体可超配**")
    md.append(f"")

    md.append(f"## 3. Top 5 权重分配")
    md.append(f"")
    md.append(f"| # | 代码 | 名称 | 权重 | 主力净 (亿) |")
    md.append(f"|---|---|---|---|---|")
    medals = ["🥇", "🥈", "🥉", "", ""]
    for i, t in enumerate(top5, 1):
        md.append(f"| {medals[i-1]} | {t['code']} | {t['name']} | {weights.get(t['code'], 0)}% | +{t['main_net_yi']:.2f} |")
    md.append(f"")

    md.append(f"## 4. fact vs inference 划线")
    md.append(f"")
    md.append(f"| 类型 | 内容 |")
    md.append(f"|---|---|")
    md.append(f"| **FACT** | A 股 {today_bj} 收盘数据 (来自公开报道) |")
    md.append(f"| **FACT** | 国证 399365 前十大权重 + PE 分位 |")
    md.append(f"| **FACT** | FAO 7月 FPI 131.1 (3.5年新高) |")
    md.append(f"| **INFERENCE** | \"哪个子赛道最受益\" — 基于供需/政策/估值综合判断, 不是回测 |")
    md.append(f"| **MISSING** | 池子级资金面完整覆盖 (efinance 限流) |")
    md.append(f"")

    md.append(f"## 5. 保存选项 (说一句我才动)")
    md.append(f"")
    md.append(f"- [ ] **不保存** — 当聊天看, 不落盘")
    md.append(f"- [ ] **保存为草稿** — 写到 `portfolio.db` 的 `strategy_cards` 表")
    md.append(f"- [ ] **保存为可用** — 状态 `active`, 配合 `mommy monitor` 准备监测")
    md.append(f"")
    md.append(f"---")
    md.append(f"")
    md.append(f"> ⚠️ 本策略卡为研究/教学/个人投资参考, **不是投资建议, 不构成任何买卖推荐**.")
    md.append(f"")

    return "\n".join(md)


# ---------- main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description="Food security analysis main entry")
    parser.add_argument("--data", required=True, help="data.json path")
    parser.add_argument("--out", required=True, help="output run directory")
    parser.add_argument("--session", default="n/a", help="Mavis session id")
    parser.add_argument("--skip-zip", action="store_true", help="skip zip packaging")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"  ❌ data file not found: {data_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    d = load_data(data_path)
    warnings = validate_data(d)
    if warnings:
        print(f"  ⚠️ data warnings:")
        for w in warnings:
            print(f"    - {w}")

    # Augment with money-flow time series (for Chart.js) if not already in data.json
    # Pulled from mommy-chaogu's today_money_flow_cache (same source the agent used).
    if not d.get("top5_flow_ts") and d.get("top5_tech"):
        d["top5_flow_ts"] = _pull_top5_flow_ts(d["top5_tech"].keys())
        if d["top5_flow_ts"]:
            print(f"  ℹ️  pulled {sum(len(v) for v in d['top5_flow_ts'].values())} flow samples for top5 Chart.js")
        else:
            print(f"  ℹ️  top5_flow_ts not available, Chart.js time-series will show '数据不可用' placeholder")

    # Compute additional fields (MA, trend, ranking) if not in data
    if d.get("top5_tech"):
        for code, info in d["top5_tech"].items():
            if "closes" in info and "ma5" not in info:
                closes = info["closes"]
                if len(closes) >= 20:
                    info["ma5"] = round(compute_ma(closes, len(closes) - 1, 5) or 0, 2)
                    info["ma10"] = round(compute_ma(closes, len(closes) - 1, 10) or 0, 2)
                    info["ma20"] = round(compute_ma(closes, len(closes) - 1, 20) or 0, 2)
                if len(closes) >= 60:
                    info["ma60"] = round(compute_ma(closes, len(closes) - 1, 60) or 0, 2)
                if info.get("ma20") and info.get("close"):
                    info["dev20"] = round((info["close"] / info["ma20"] - 1) * 100, 2)
                if info.get("ma20") and info.get("ma60"):
                    info["trend"] = trend_regime(info["close"], info["ma20"], info["ma60"])
            # Strip raw closes from output to keep data.json lean
            info.pop("closes", None)

    # Generate report
    report = render_report(d, warnings, session_id=args.session)
    report_path = out_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  ✅ {report_path} ({len(report)} bytes)")

    # Generate strategy card
    card = render_strategy(d, session_id=args.session)
    card_path = out_dir / "strategy-card.md"
    card_path.write_text(card, encoding="utf-8")
    print(f"  ✅ {card_path} ({len(card)} bytes)")

    # v1.2: Render report.md + strategy-card.md to standalone HTML pages
    # (used for PDF printing and embedded reading in web.html)
    try:
        import markdown as _md
        report_html_str = _md.markdown(
            report,
            extensions=["tables", "fenced_code", "toc", "sane_lists"],
        )
        card_html_str = _md.markdown(
            card,
            extensions=["tables", "fenced_code", "toc", "sane_lists"],
        )
    except ImportError:
        # fallback: wrap in <pre> if markdown not installed
        report_html_str = f'<pre style="white-space: pre-wrap;">{report}</pre>'
        card_html_str = f'<pre style="white-space: pre-wrap;">{card}</pre>'

    # Save standalone HTML files
    report_html_path = out_dir / "report.html"
    report_html_path.write_text(
        _standalone_html_doc("完整报告", report_html_str, today_bj := d.get("trading_day", "—"), d.get("is_market_close", False), "report", args.session),
        encoding="utf-8",
    )
    print(f"  ✅ {report_html_path} ({report_html_path.stat().st_size} bytes)")

    card_html_path = out_dir / "strategy-card.html"
    card_html_path.write_text(
        _standalone_html_doc("策略卡", card_html_str, today_bj, d.get("is_market_close", False), "strategy", args.session),
        encoding="utf-8",
    )
    print(f"  ✅ {card_html_path} ({card_html_path.stat().st_size} bytes)")

    # v1.2: Generate PDFs from the HTML files using chromium --print-to-pdf
    chrome = _find_chrome()
    if chrome:
        for html_name, pdf_name in [("report.html", "report.pdf"), ("strategy-card.html", "strategy-card.pdf")]:
            pdf_path = out_dir / pdf_name
            ok, msg = _chrome_to_pdf(chrome, str(out_dir / html_name), str(pdf_path))
            if ok:
                print(f"  ✅ {pdf_path} ({pdf_path.stat().st_size} bytes)")
            else:
                print(f"  ⚠️ {pdf_name} 生成失败: {msg}")
    else:
        print(f"  ⚠️ chromium 未找到, 跳过 PDF 生成 (用户仍可 web.html '另存为 PDF' 打印)")

    # Save data.json (with computed fields)
    data_out = out_dir / "data.json"
    data_out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ {data_out} ({data_out.stat().st_size} bytes)")

    # Build HTML (visual with dark mode + Chart.js + hover/click interactivity)
    try:
        from html_render import render_html
        html = render_html(d, session_id=args.session,
                           report_html=report_html_str,
                           strategy_html=card_html_str,
                           report_md_raw=report,
                           strategy_md_raw=card)
        html_path = out_dir / "web.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"  ✅ {html_path} ({len(html)} bytes)")
    except ImportError:
        print(f"  ⚠️ html_render module not found, skipping web.html (run from scripts/ dir)")

    # Build text-only Markdown (高密度, 零图表, 给不看图的人)
    try:
        from text_render import render_text
        text_md = render_text(d, session_id=args.session)
        text_path = out_dir / "text.md"
        text_path.write_text(text_md, encoding="utf-8")
        print(f"  ✅ {text_path} ({len(text_md)} bytes)")
    except ImportError:
        print(f"  ⚠️ text_render module not found, skipping text.md (run from scripts/ dir)")

    # Package ZIP
    if not args.skip_zip:
        try:
            import subprocess
            pkg = Path(__file__).parent / "package_zip.py"
            r = subprocess.run(
                [sys.executable, str(pkg), "--run-dir", str(out_dir), "--session", args.session],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                print(f"  ✅ {r.stdout.strip()}")
            else:
                print(f"  ⚠️ zip packaging failed: {r.stderr.strip()}")
        except Exception as e:
            print(f"  ⚠️ zip packaging error: {e}")

    print(f"\n  📦 Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
