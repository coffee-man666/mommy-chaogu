"""HTML render for food-security-analysis deliverable.

Self-contained HTML with embedded CSS + SVG icons + hand-rolled charts (donut,
horizontal bar, table). No external JS frameworks. Google Fonts via <link>.

Usage: from analyze.py
    from html_render import render_html
    html = render_html(data, session_id="...")
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

BJ = timezone(timedelta(hours=8))


def now_bj() -> datetime:
    return datetime.now(BJ)


def fmt_bj_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":" + dt.strftime("%z")[-2:]


# ---------- helpers ----------


def rank_top5(basket_flow, fundamentals):
    scored = []
    for code, info in basket_flow.items():
        if not isinstance(info, dict):
            continue
        if info.get("is_st"):
            continue
        main_net = float(info.get("main_net", 0) or 0) / 1e8
        close = float(info.get("close", 0) or 0)
        elasticity = 0.5 if 0 < close < 30 else 0
        trend = info.get("trend", "mixed")
        tech = {"bull": 1.0, "mixed": 0.0, "bear": -1.0, "n/a": 0.0}.get(trend, 0.0)
        pe = fundamentals.get(code, {}).get("pe")
        fund = 0.0
        if pe and pe != "失真" and pe != "n/a":
            try:
                pe_val = float(str(pe).replace("x", ""))
                if pe_val < 30:
                    fund = 1.0
                elif pe_val < 60:
                    fund = 0.5
                else:
                    fund = -0.5
            except (ValueError, AttributeError):
                pass
        score = main_net + elasticity + tech * 0.5 + fund * 0.3
        scored.append({
            "code": code, "name": info.get("name", code),
            "main_net_yi": main_net, "close": close,
            "trend": trend, "score": score,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]


def assign_weights(top5):
    if len(top5) < 5:
        return {t["code"]: 0 for t in top5}
    return {top5[0]["code"]: 30, top5[1]["code"]: 25, top5[2]["code"]: 20, top5[3]["code"]: 15, top5[4]["code"]: 10}


# ---------- theme-agnostic metadata (basket-analysis v1.2) ----------

def _get_theme(d: dict) -> dict:
    """Return the theme metadata block. Falls back to legacy food-security defaults
    when d['theme'] is missing (backward-compat with pre-v1.2 data.json files)."""
    return d.get("theme") or {
        "name": "粮食安全/危机",
        "name_en": "food-security",
        "description": "全球粮价 + 极端天气 + 出口受阻 + 国内政策密集",
        "basket": {"size": 35, "source": "mommy food-security"},
        "trigger_variables": [
            {"label": "FAO 谷物月度环比", "current": "+3.4%", "threshold": "≥ +2%", "status": "✅ 触发"},
            {"label": "黑海海运量同比", "current": "-40%", "threshold": "≤ -30%", "status": "✅ 触发"},
            {"label": "厄尔尼诺强度 (ONI)", "current": "强 (70年最强)", "threshold": "≥ 强", "status": "✅ 触发"},
            {"label": "399365 粮食主题 PE 分位", "current": "36.5%", "threshold": "≤ 40%", "status": "✅ 触发"},
        ],
        "global_drivers": [
            {"name": "黑海出口扰动", "desc": "7 月底黑海出货量同比 -40%, 俄罗斯袭击敖德萨港口"},
            {"name": "厄尔尼诺 70 年最强", "desc": "NOAA 周报持续升温, 9-11 月 90%+ 概率非常强"},
            {"name": "中东/化肥", "desc": "霍尔木兹封锁风险, 全球化肥供应链紧张"},
            {"name": "FAO 食品价格指数", "desc": "7 月 131.1 (3.5 年新高), 谷物 +3.4% / 小麦 +5.8%"},
        ],
        "top5_intro": "种业占 3 席 (权重 60%), 化肥 2 席 (权重 40%)",
        "verification_extras": [
            "农业板块是否延续强势, <strong>国证 399365</strong> 是否突破, 量能是否放大",
            "<strong>粮食 ETF 鹏华 159698</strong> 净流入是否持续, 主题资金面",
            "FAO 8 月数据是否公布 (一般月初)",
            "厄尔尼诺强度更新 (NOAA 周报), 4 变量触发状态变化",
        ],
    }


# ---------- icons (lucide-style inline SVG, currentColor) ----------


ICONS = {
    "check": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>',
    "trending": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 12l3-3 4 4 5-5"/></svg>',
    "down": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>',
    "globe": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    "chart": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-9 4 18 3-9h4"/></svg>',
    "down_arr": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M7 7l10 10M17 7v10H7"/></svg>',
    "up_arr": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M7 17l10-10M7 7h10v10"/></svg>',
    "leaf": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>',
    "drop": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>',
    "anchor": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="3"/><path d="M12 22V8M5 12H2a10 10 0 0020 0h-3"/></svg>',
    "grid": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h18v18H3z"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg>',
    "doc": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>',
    "db": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
    "settings": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>',
    "memory": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>',
    "shield": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4"/><path d="M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9 9 4.03 9 9z"/></svg>',
    "target": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>',
    "alert": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4M12 17h.01"/></svg>',
    "package": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"/></svg>',
}


# ---------- CSS ----------


CSS = """
:root {
  --bg: #f7f5f0;
  --surface: #ffffff;
  --surface-2: #fbfaf6;
  --line: #e9e3d6;
  --line-soft: #f0ebde;
  --ink-1: #14171e;
  --ink-2: #3a4256;
  --ink-3: #7c7a72;
  --primary: #2f6f5e;
  --primary-soft: rgba(47, 111, 94, 0.08);
  --primary-border: rgba(47, 111, 94, 0.18);
  --accent: #c97b3f;
  --accent-soft: rgba(201, 123, 63, 0.1);
  --warn: #b06367;
  --good: #2f6f5e;
  --bad: #b06367;
  --shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  --shadow-lg: 0 10px 30px -8px rgba(0, 0, 0, 0.08);
}
/* dark mode — toggled by [data-theme="dark"] on <html> */
[data-theme="dark"] {
  --bg: #0f1419;
  --surface: #1a1f2e;
  --surface-2: #232838;
  --line: #2a3144;
  --line-soft: #232838;
  --ink-1: #e8e8f0;
  --ink-2: #a8b0c0;
  --ink-3: #707684;
  --primary: #4a9d85;
  --primary-soft: rgba(74, 157, 133, 0.12);
  --primary-border: rgba(74, 157, 133, 0.28);
  --accent: #e09550;
  --accent-soft: rgba(224, 149, 80, 0.14);
  --warn: #d17880;
  --good: #4a9d85;
  --bad: #d17880;
  --shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  --shadow-lg: 0 10px 30px -8px rgba(0, 0, 0, 0.5);
}
[data-theme="dark"] body::before { background: radial-gradient(circle, rgba(224, 149, 80, 0.08) 0%, transparent 70%); }
[data-theme="dark"] body::after { background: radial-gradient(circle, rgba(74, 157, 133, 0.06) 0%, transparent 70%); }
* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: 'Outfit', system-ui, sans-serif;
  background: var(--bg);
  color: var(--ink-1);
  line-height: 1.6;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
}
body::before {
  content: '';
  position: fixed;
  top: 0; right: 0;
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(201, 123, 63, 0.05) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}
body::after {
  content: '';
  position: fixed;
  bottom: 0; left: 0;
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(47, 111, 94, 0.04) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px; position: relative; z-index: 1; }
.hero { padding: 80px 0 60px; border-bottom: 1px solid var(--line); }
.hero-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
  color: var(--primary);
  margin-bottom: 24px;
  letter-spacing: 0.02em;
}
.hero h1 {
  font-family: 'DM Serif Display', serif;
  font-size: 48px;
  font-weight: 400;
  line-height: 1.15;
  letter-spacing: -0.01em;
  color: var(--ink-1);
  margin-bottom: 20px;
  max-width: 900px;
}
.hero h1 em { font-style: italic; color: var(--primary); }
.hero-sub { font-size: 18px; color: var(--ink-2); max-width: 700px; margin-bottom: 32px; }
.hero-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  background: var(--surface);
}
.stat { padding: 22px 20px; border-right: 1px solid var(--line); position: relative; }
.stat:last-child { border-right: none; }
.stat-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}
.stat-value {
  font-family: 'DM Serif Display', serif;
  font-size: 28px;
  color: var(--ink-1);
  line-height: 1;
  margin-bottom: 4px;
}
.stat-value .unit {
  font-family: 'Outfit', sans-serif;
  font-size: 13px;
  color: var(--ink-3);
  font-weight: 500;
  margin-left: 4px;
}
.stat-note { font-size: 12px; color: var(--ink-3); }
section { padding: 64px 0; border-bottom: 1px solid var(--line-soft); }
section:last-child { border-bottom: none; }
.section-head { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 40px; }
.section-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: var(--accent);
  font-weight: 500;
  padding-top: 4px;
  min-width: 30px;
}
.section-head h2 {
  font-family: 'DM Serif Display', serif;
  font-size: 30px;
  font-weight: 400;
  color: var(--ink-1);
  line-height: 1.2;
  margin-bottom: 8px;
}
.section-head p { font-size: 15px; color: var(--ink-2); max-width: 700px; }

.trigger-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.trigger-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 22px 20px;
  position: relative;
  transition: all 0.2s;
}
.trigger-card:hover { transform: translateY(-2px); box-shadow: 0 6px 24px -8px rgba(0,0,0,0.08); }
.trigger-card.met { border-color: var(--primary); background: linear-gradient(180deg, var(--primary-soft) 0%, var(--surface) 30%); }
.trigger-icon {
  width: 32px; height: 32px;
  display: inline-flex;
  align-items: center; justify-content: center;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary);
  margin-bottom: 14px;
}
.trigger-label {
  font-size: 12px; font-weight: 600; color: var(--ink-3);
  text-transform: uppercase; letter-spacing: 0.04em;
  margin-bottom: 8px;
}
.trigger-value {
  font-family: 'DM Serif Display', serif;
  font-size: 26px; color: var(--ink-1);
  line-height: 1.1; margin-bottom: 6px;
}
.trigger-thresh {
  font-size: 12px; color: var(--ink-3);
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 10px;
}
.trigger-status {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12px; font-weight: 600; color: var(--good);
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--good); }
.verdict {
  margin-top: 24px; padding: 20px 24px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  display: flex; align-items: center; gap: 16px;
}
.verdict-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 24px; font-weight: 600;
  color: var(--primary);
  padding: 8px 14px;
  background: var(--primary-soft);
  border-radius: 8px;
}
.verdict-text { font-size: 15px; color: var(--ink-2); }
.verdict-text strong { color: var(--ink-1); font-weight: 600; }

.donut-row { display: grid; grid-template-columns: 360px 1fr; gap: 48px; align-items: center; }
.donut-wrap { display: flex; justify-content: center; }
.donut svg { width: 320px; height: 320px; filter: drop-shadow(0 4px 20px rgba(47, 111, 94, 0.1)); }
.donut-center { text-anchor: middle; fill: var(--ink-1); }
.donut-center .big { font-family: 'DM Serif Display', serif; font-size: 56px; font-weight: 400; }
.donut-center .sm { font-size: 12px; fill: var(--ink-3); text-transform: uppercase; letter-spacing: 0.08em; }
.chain-list { display: flex; flex-direction: column; gap: 14px; }
.chain-row {
  display: grid; grid-template-columns: 100px 1fr auto;
  align-items: center; gap: 16px;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  transition: all 0.2s;
}
.chain-row:hover { border-color: var(--primary); transform: translateX(2px); }
.chain-name { font-weight: 600; color: var(--ink-1); font-size: 15px; }
.chain-bar { height: 8px; background: var(--line-soft); border-radius: 4px; overflow: hidden; }
.chain-fill { height: 100%; border-radius: 4px; }
.chain-num { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 600; color: var(--ink-1); min-width: 32px; text-align: right; }

.flow-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
.flow-col h3 {
  font-size: 13px; font-weight: 600; color: var(--ink-3);
  text-transform: uppercase; letter-spacing: 0.04em;
  margin-bottom: 16px; display: flex; align-items: center; gap: 8px;
}
.flow-col.in h3 { color: var(--good); }
.flow-col.out h3 { color: var(--bad); }
.bench-row {
  display: grid; grid-template-columns: 120px 1fr 64px;
  gap: 12px; align-items: center;
  padding: 8px 0;
  border-bottom: 1px dashed var(--line-soft);
}
.bench-row:last-child { border-bottom: none; }
.bench-label { display: flex; flex-direction: column; }
.bench-label .code { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--ink-3); }
.bench-label .name { font-size: 14px; font-weight: 500; color: var(--ink-1); }
.bench-bar { height: 14px; background: var(--line-soft); border-radius: 4px; overflow: hidden; }
.bench-fill { height: 100%; border-radius: 4px; transition: width 0.6s ease; }
.bench-fill.in { background: linear-gradient(90deg, var(--primary), #4a8e7c); }
.bench-fill.out { background: linear-gradient(90deg, var(--bad), #c97b7f); }
.bench-val { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 600; text-align: right; }
.bench-val.in { color: var(--good); }
.bench-val.out { color: var(--bad); }

.rec-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }
.rec-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 22px 20px;
  position: relative;
  transition: all 0.2s;
  display: flex; flex-direction: column;
}
.rec-card:hover { transform: translateY(-3px); box-shadow: 0 10px 30px -8px rgba(0,0,0,0.08); border-color: var(--primary); }
.rec-rank {
  position: absolute; top: -10px; left: 16px;
  font-family: 'DM Serif Display', serif;
  font-size: 14px;
  padding: 4px 10px;
  background: var(--accent);
  color: white;
  border-radius: 100px;
  line-height: 1.4;
}
.rec-code { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--ink-3); margin-top: 8px; }
.rec-name { font-family: 'DM Serif Display', serif; font-size: 24px; color: var(--ink-1); line-height: 1.1; margin-top: 4px; }
.rec-tier { display: inline-block; font-size: 11px; padding: 3px 8px; background: var(--primary-soft); color: var(--primary); border-radius: 100px; font-weight: 600; margin-top: 10px; }
.rec-weight { margin-top: 16px; padding: 12px; background: var(--accent-soft); border-radius: 8px; text-align: center; }
.rec-weight .num { font-family: 'DM Serif Display', serif; font-size: 28px; color: var(--accent); }
.rec-weight .lbl { font-size: 11px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.rec-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--line); }
.rec-metric { display: flex; flex-direction: column; }
.rec-metric .lbl { font-size: 10px; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.04em; }
.rec-metric .val { font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--ink-1); font-weight: 500; }
.rec-metric .val.good { color: var(--good); }
.rec-metric .val.bad { color: var(--bad); }
.rec-metric .val.warn { color: var(--accent); }
.rec-logic { margin-top: 14px; padding: 12px; background: var(--surface-2); border-radius: 8px; font-size: 12.5px; color: var(--ink-2); line-height: 1.5; }
.rec-logic strong { color: var(--ink-1); font-weight: 600; }

.ma-table { width: 100%; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; border-collapse: collapse; }
.ma-table thead { background: var(--surface-2); }
.ma-table th { text-align: left; padding: 12px 14px; font-size: 11px; font-weight: 600; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--line); }
.ma-table td { padding: 12px 14px; font-size: 13.5px; color: var(--ink-2); border-bottom: 1px solid var(--line-soft); font-family: 'JetBrains Mono', monospace; }
.ma-table tr:last-child td { border-bottom: none; }
.ma-table .name-cell { font-family: 'Outfit', sans-serif; font-weight: 500; color: var(--ink-1); }
.ma-table .code-cell { font-size: 11px; color: var(--ink-3); }
.ma-table .trend-bull { color: var(--good); font-weight: 600; }
.ma-table .trend-bear { color: var(--bad); font-weight: 600; }
.ma-table .trend-mix { color: var(--accent); font-weight: 600; }

.crisis-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.crisis-card { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 24px 22px; transition: all 0.2s; }
.crisis-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.crisis-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.crisis-icon { width: 40px; height: 40px; border-radius: 10px; background: var(--accent-soft); color: var(--accent); display: inline-flex; align-items: center; justify-content: center; }
.crisis-name { font-size: 16px; font-weight: 600; color: var(--ink-1); }
.crisis-stat { font-family: 'DM Serif Display', serif; font-size: 32px; color: var(--accent); line-height: 1; margin-bottom: 8px; }
.crisis-desc { font-size: 13.5px; color: var(--ink-2); line-height: 1.6; }
.crisis-tag { display: inline-block; margin-top: 10px; font-size: 11px; padding: 3px 8px; background: var(--primary-soft); color: var(--primary); border-radius: 100px; font-weight: 600; }

.snapshot-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: var(--surface); }
.snap-cell { padding: 18px 16px; border-right: 1px solid var(--line); text-align: center; }
.snap-cell:last-child { border-right: none; }
.snap-label { font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
.snap-value { font-family: 'DM Serif Display', serif; font-size: 24px; color: var(--ink-1); line-height: 1; margin-bottom: 4px; }
.snap-chg { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--good); font-weight: 600; }

.check-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.check-item { display: flex; align-items: flex-start; gap: 12px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; font-size: 14px; color: var(--ink-2); line-height: 1.5; }
.check-num { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600; color: var(--accent); background: var(--accent-soft); width: 22px; height: 22px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
.check-item strong { color: var(--ink-1); font-weight: 600; }

footer { padding: 48px 0; text-align: center; color: var(--ink-3); font-size: 13px; border-top: 1px solid var(--line); }
footer p { margin-bottom: 4px; }
footer a { color: var(--primary); text-decoration: none; }

/* sticky top nav */
.topbar {
  position: sticky; top: 0; z-index: 100;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
  padding: 12px 0;
}
.topbar-inner {
  display: flex; align-items: center; gap: 24px;
  max-width: 1200px; margin: 0 auto; padding: 0 24px;
}
.topbar-brand {
  font-family: 'DM Serif Display', serif;
  font-size: 16px;
  color: var(--ink-1);
  white-space: nowrap;
}
.topbar-nav {
  display: flex; gap: 4px; flex: 1;
  overflow-x: auto; scrollbar-width: none;
}
.topbar-nav::-webkit-scrollbar { display: none; }
.topbar-link {
  font-size: 13px;
  color: var(--ink-3);
  padding: 6px 12px;
  border-radius: 6px;
  text-decoration: none;
  white-space: nowrap;
  transition: all 0.15s;
}
.topbar-link:hover { color: var(--ink-1); background: var(--surface-2); }
.topbar-link.active { color: var(--primary); background: var(--primary-soft); }
.topbar-actions { display: flex; gap: 8px; flex-shrink: 0; }
.toggle-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink-2);
  font-size: 12px;
  font-family: 'Outfit', sans-serif;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.toggle-btn:hover { border-color: var(--primary); color: var(--ink-1); }
.toggle-btn svg { width: 14px; height: 14px; }

/* tooltip on hover */
.bench-row[data-tooltip] { position: relative; cursor: pointer; }
.bench-row[data-tooltip]:hover .bench-tooltip { opacity: 1; visibility: visible; transform: translateY(0); }
.bench-tooltip {
  position: absolute;
  left: 50%; bottom: calc(100% + 8px);
  transform: translate(-50%, 4px);
  background: var(--ink-1);
  color: var(--bg);
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  white-space: pre;
  opacity: 0;
  visibility: hidden;
  transition: all 0.15s;
  z-index: 50;
  pointer-events: none;
  box-shadow: var(--shadow-lg);
  line-height: 1.5;
}
.bench-tooltip::after {
  content: '';
  position: absolute;
  top: 100%; left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: var(--ink-1);
}
.bench-tooltip strong { color: var(--bg); font-weight: 700; }

/* jump-link arrow on cards */
.rec-card { position: relative; }
.rec-card[data-jump] { cursor: pointer; }
.rec-card[data-jump]:hover { transform: translateY(-4px); }
.rec-jump-arrow {
  position: absolute; top: 14px; right: 14px;
  font-size: 11px; color: var(--ink-3);
  opacity: 0; transition: opacity 0.2s;
  font-family: 'JetBrains Mono', monospace;
}
.rec-card:hover .rec-jump-arrow { opacity: 1; }

/* chart containers */
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chart-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 24px;
}
.chart-title {
  font-size: 14px; font-weight: 600; color: var(--ink-1);
  margin-bottom: 4px;
}
.chart-sub {
  font-size: 12px; color: var(--ink-3); margin-bottom: 16px;
}
.chart-wrap { position: relative; height: 240px; }

/* text mode (no charts) */
[data-mode="text"] .chart-card,
[data-mode="text"] .donut-wrap svg,
[data-mode="text"] .donut .donut-center,
[data-mode="text"] .bench-bar,
[data-mode="text"] .chain-bar,
[data-mode="text"] .chain-fill,
[data-mode="text"] .hero::before,
[data-mode="text"] .hero::after { display: none; }
[data-mode="text"] .donut-row { grid-template-columns: 1fr; }
[data-mode="text"] .chain-list { gap: 4px; }
[data-mode="text"] .chain-row { padding: 6px 10px; font-size: 13px; }
[data-mode="text"] .bench-row { padding: 4px 0; }
[data-mode="text"] .stat-value { font-size: 22px; }
[data-mode="text"] .crisis-stat { font-size: 24px; }

/* scroll-margin so anchor links don't hide under sticky topbar */
section { scroll-margin-top: 80px; }

/* v1.2: download dropdown */
.dropdown { position: relative; }
.dropdown-menu {
  position: absolute; top: calc(100% + 6px); right: 0;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; min-width: 280px;
  box-shadow: var(--shadow-lg);
  padding: 8px 0; z-index: 200;
  opacity: 0; visibility: hidden; transform: translateY(-4px);
  transition: all 0.15s;
}
.dropdown.open .dropdown-menu { opacity: 1; visibility: visible; transform: translateY(0); }
.dropdown-group {
  font-size: 10px; font-weight: 600;
  color: var(--ink-3); text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 8px 16px 4px;
}
.dropdown-group:not(:first-child) { border-top: 1px solid var(--line); margin-top: 4px; padding-top: 12px; }
.dropdown-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 16px;
  color: var(--ink-1); text-decoration: none;
  font-size: 13px;
  transition: background 0.1s;
}
.dropdown-item:hover { background: var(--primary-soft); }
.dl-icon { font-size: 16px; width: 20px; text-align: center; }
.dl-meta {
  margin-left: auto; font-size: 11px; color: var(--ink-3);
  font-family: 'JetBrains Mono', monospace;
}
.toggle-btn-primary { background: var(--primary); color: white; border-color: var(--primary); }
.toggle-btn-primary:hover { background: var(--primary); filter: brightness(1.1); }

/* v1.2: embedded markdown docs */
.embedded-doc {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 40px 48px;
  font-size: 15px;
  line-height: 1.75;
  max-width: 920px;
}
.embedded-doc h1 { font-family: 'DM Serif Display', serif; font-size: 28px; font-weight: 400; margin: 0 0 12px; }
.embedded-doc h2 { font-size: 20px; font-weight: 600; margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
.embedded-doc h3 { font-size: 16px; font-weight: 600; margin: 24px 0 8px; }
.embedded-doc p { color: var(--ink-2); margin-bottom: 14px; }
.embedded-doc ul, .embedded-doc ol { margin: 0 0 16px 24px; }
.embedded-doc li { margin-bottom: 6px; color: var(--ink-2); }
.embedded-doc strong { color: var(--ink-1); }
.embedded-doc code { font-family: 'JetBrains Mono', monospace; font-size: 0.88em; background: var(--surface-2); padding: 2px 6px; border-radius: 4px; color: var(--ink-1); border: 1px solid var(--line); }
.embedded-doc pre { background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 16px; overflow-x: auto; margin: 16px 0; }
.embedded-doc table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }
.embedded-doc th { text-align: left; padding: 8px 12px; background: var(--surface-2); border-bottom: 2px solid var(--line); }
.embedded-doc td { padding: 8px 12px; border-bottom: 1px solid var(--line); color: var(--ink-2); }
.embedded-doc blockquote { border-left: 3px solid var(--primary); padding: 8px 16px; margin: 16px 0; background: var(--primary-soft); color: var(--ink-2); border-radius: 0 6px 6px 0; }
.embedded-doc a { color: var(--primary); }

/* v1.2: file icon variants */
.file-icon-pdf {
  width: 48px; height: 48px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(201, 123, 63, 0.12);
  color: var(--accent);
  border-radius: 10px;
  font-size: 24px;
  flex-shrink: 0;
}

/* v1.2: floating "save as PDF" button */
.print-fab {
  position: fixed; bottom: 24px; right: 24px; z-index: 90;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 20px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 100px;
  font-size: 13px; font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(47, 111, 94, 0.3);
  transition: all 0.2s;
}
.print-fab:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(47, 111, 94, 0.4); }
.print-fab svg { width: 16px; height: 16px; }

/* v1.2: print CSS — hide chrome when printing */
@media print {
  .topbar, .print-fab, .dropdown-menu,
  .toggle-btn, .hero::before, .hero::after,
  [data-mode="text"] .chart-card { display: none !important; }
  body { background: white; color: black; }
  .container { max-width: 100%; padding: 0 20px; }
  .embedded-doc { border: none; padding: 20px 0; max-width: 100%; }
  section { page-break-inside: avoid; margin-bottom: 30px; }
  h2 { page-break-after: avoid; }
}

@media (max-width: 980px) {
  .hero h1 { font-size: 36px; }
  .hero-stats { grid-template-columns: repeat(2, 1fr); }
  .stat { border-right: none; border-bottom: 1px solid var(--line); }
  .stat:nth-child(odd) { border-right: 1px solid var(--line); }
  .stat:nth-last-child(-n+2) { border-bottom: none; }
  .trigger-grid { grid-template-columns: repeat(2, 1fr); }
  .donut-row { grid-template-columns: 1fr; gap: 32px; }
  .flow-grid { grid-template-columns: 1fr; }
  .rec-grid { grid-template-columns: 1fr; }
  .crisis-grid { grid-template-columns: 1fr; }
  .snapshot-grid { grid-template-columns: repeat(3, 1fr); }
  .check-grid { grid-template-columns: 1fr; }
  .chart-grid { grid-template-columns: 1fr; }
  .section-head h2 { font-size: 24px; }
  .topbar-nav { display: none; }
}
"""


# ---------- render functions ----------


def render_donut() -> str:
    return '''
    <svg viewBox="0 0 200 200" width="320" height="320">
      <circle cx="100" cy="100" r="80" fill="none" stroke="#f0ebde" stroke-width="32"/>
      <circle cx="100" cy="100" r="80" fill="none" stroke="#2f6f5e" stroke-width="32"
        stroke-dasharray="272.8 502.7" stroke-dashoffset="0" transform="rotate(-90 100 100)"/>
      <circle cx="100" cy="100" r="80" fill="none" stroke="#c97b3f" stroke-width="32"
        stroke-dasharray="115 502.7" stroke-dashoffset="-272.8" transform="rotate(-90 100 100)"/>
      <circle cx="100" cy="100" r="80" fill="none" stroke="#b06367" stroke-width="32"
        stroke-dasharray="71.8 502.7" stroke-dashoffset="-387.8" transform="rotate(-90 100 100)"/>
      <circle cx="100" cy="100" r="80" fill="none" stroke="#7c7a72" stroke-width="32"
        stroke-dasharray="43.1 502.7" stroke-dashoffset="-459.6" transform="rotate(-90 100 100)"/>
      <text x="100" y="92" class="donut-center big">35</text>
      <text x="100" y="118" class="donut-center sm">只 · 4 chain</text>
    </svg>'''


def render_hero(d: dict) -> str:
    theme = _get_theme(d)
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    is_close = d.get("is_market_close", False)
    data_label = "close" if is_close else "mid-day"
    bf = d.get("basket_flow", {})
    basket_size = (theme.get("basket") or {}).get("size") or len(bf) or 35
    coverage = len([v for v in bf.values() if v.get("main_net") is not None])
    triggers = theme.get("trigger_variables") or []
    n_triggers_total = 4
    n_triggers_met = sum(1 for t in triggers if "✅" in (t.get("status") or ""))
    return f'''
    <div class="hero-meta">
      {ICONS["check"]}
      <span>数据截至 {today_bj} {data_label} (北京时间) · mommy-chaogu v1.4.0</span>
    </div>
    <h1>{theme["name"]} 主题分析 · <em>{data_label} 复盘</em></h1>
    <p class="hero-sub">{basket_size} 只篮子 · {n_triggers_total} 变量触发 · Top 5 推荐 + 均线技术面 · 数据可审计, 推荐可次日验证。</p>
    <div class="hero-stats">
      <div class="stat">
        <div class="stat-label">交易日</div>
        <div class="stat-value">{today_bj[-5:]}</div>
        <div class="stat-note">{data_label}</div>
      </div>
      <div class="stat">
        <div class="stat-label">篮子规模</div>
        <div class="stat-value">{basket_size}<span class="unit">只</span></div>
        <div class="stat-note">{(theme.get("basket") or {}).get("source", "—")}</div>
      </div>
      <div class="stat">
        <div class="stat-label">资金流</div>
        <div class="stat-value">{coverage}<span class="unit">/{basket_size}</span></div>
        <div class="stat-note">{coverage*100//max(1,basket_size)}% 覆盖</div>
      </div>
      <div class="stat">
        <div class="stat-label">推荐</div>
        <div class="stat-value">5<span class="unit">只</span></div>
        <div class="stat-note">次日可验证</div>
      </div>
      <div class="stat">
        <div class="stat-label">主题共振</div>
        <div class="stat-value">{n_triggers_met}<span class="unit">/{n_triggers_total}</span></div>
        <div class="stat-note">{"动能强" if n_triggers_met >= 3 else "动能弱"}</div>
      </div>
    </div>'''


def render_triggers(d: dict) -> str:
    """v1.2: render trigger cards from d['theme']['trigger_variables'].
    Falls back to legacy 4 food-security triggers if theme not present."""
    theme = _get_theme(d)
    triggers = theme.get("trigger_variables") or []
    icons = [ICONS["trending"], ICONS["down"], ICONS["globe"], ICONS["chart"]]
    cards = []
    for i, t in enumerate(triggers):
        is_met = "✅" in (t.get("status") or "")
        card_cls = "trigger-card met" if is_met else "trigger-card unmet"
        note = t.get("note", t.get("status", ""))
        cards.append(f'''<div class="{card_cls}">
        <div class="trigger-icon">{icons[i % len(icons)]}</div>
        <div class="trigger-label">{chr(0x2488 + i) if i < 20 else str(i+1)}. {t.get("label", "—")}</div>
        <div class="trigger-value">{t.get("current", "—")}</div>
        <div class="trigger-thresh">阈值: {t.get("threshold", "—")}</div>
        <div class="trigger-status"><span class="dot"></span>{note}</div>
      </div>''')
    n_met = sum(1 for t in triggers if "✅" in (t.get("status") or ""))
    n_total = len(triggers)
    if n_met >= 3:
        verdict_text = f"<strong>主题动能强</strong> · {n_met}/{n_total} 触发, 板块整体可超配 · 任一变量反转即降至 ≤ 2/{n_total} 触发需减仓"
    elif n_met == 2:
        verdict_text = f"<strong>主题动能中</strong> · {n_met}/{n_total} 触发, 板块标配 · 关注补涨机会"
    else:
        verdict_text = f"<strong>主题动能弱</strong> · {n_met}/{n_total} 触发, 板块规避"
    return f'''
    <div class="trigger-grid">
      {"".join(cards)}
    </div>
    <div class="verdict">
      <div class="verdict-badge">{n_met} / {n_total}</div>
      <div class="verdict-text">{verdict_text}</div>
    </div>'''


def render_chain_basket() -> str:
    return f'''
    <div class="donut-row">
      <div class="donut-wrap donut">{render_donut()}</div>
      <div class="chain-list">
        <div class="chain-row">
          <div class="chain-name" style="color:#2f6f5e">上游 · 农资</div>
          <div class="chain-bar"><div class="chain-fill" style="width:54.3%; background:#2f6f5e"></div></div>
          <div class="chain-num">19</div>
        </div>
        <div class="chain-row">
          <div class="chain-name" style="color:#c97b3f">中游 · 生产加工</div>
          <div class="chain-bar"><div class="chain-fill" style="width:22.9%; background:#c97b3f"></div></div>
          <div class="chain-num">8</div>
        </div>
        <div class="chain-row">
          <div class="chain-name" style="color:#b06367">下游 · 流通饲料</div>
          <div class="chain-bar"><div class="chain-fill" style="width:14.3%; background:#b06367"></div></div>
          <div class="chain-num">5</div>
        </div>
        <div class="chain-row">
          <div class="chain-name" style="color:#7c7a72">末端 · 基础设施</div>
          <div class="chain-bar"><div class="chain-fill" style="width:8.6%; background:#7c7a72"></div></div>
          <div class="chain-num">3</div>
        </div>
      </div>
    </div>'''


def _format_money_flow_tooltip(v: dict) -> str:
    """Multi-line tooltip text for a money flow row (used on hover)."""
    main = float(v.get("main_net", 0) or 0) / 1e8
    sl = float(v.get("super_large", 0) or 0) / 1e8
    lg = float(v.get("large", 0) or 0) / 1e8
    md = float(v.get("medium", 0) or 0) / 1e8
    sm = float(v.get("small", 0) or 0) / 1e8
    samples = v.get("samples", "—")
    last_ts = v.get("last_ts", "—")
    return (
        f"<strong>{v.get('name', '')} {v.get('code', '')}</strong>\n"
        f"主力净:  {main:+.2f}亿\n"
        f"超大单:  {sl:+.2f}亿\n"
        f"大单:    {lg:+.2f}亿\n"
        f"中单:    {md:+.2f}亿\n"
        f"小单:    {sm:+.2f}亿\n"
        f"样本:    {samples} 条\n"
        f"时间:    {last_ts}"
    )


def render_money_flow(d: dict) -> str:
    bf = d.get("basket_flow", {})
    sorted_bf = sorted(
        [(k, v) for k, v in bf.items() if isinstance(v, dict)],
        key=lambda x: float(x[1].get("main_net", 0) or 0),
        reverse=True,
    )
    inflow = [(k, v) for k, v in sorted_bf if float(v.get("main_net", 0) or 0) > 0][:8]
    outflow = [(k, v) for k, v in sorted_bf if float(v.get("main_net", 0) or 0) < 0][-5:][::-1]
    max_in = max((float(v.get("main_net", 0)) / 1e8 for k, v in inflow), default=1)
    max_out = max((abs(float(v.get("main_net", 0)) / 1e8) for k, v in outflow), default=1)

    def _row(k, v, max_v, is_in):
        main = float(v.get("main_net", 0) or 0) / 1e8
        sign = "+" if is_in else ""
        tooltip = _format_money_flow_tooltip(v).replace('"', '&quot;')
        return (
            f'<div class="bench-row" data-tooltip="{tooltip}">'
            f'<span class="bench-tooltip">{_format_money_flow_tooltip(v).replace(chr(10), "<br>")}</span>'
            f'<div class="bench-label"><span class="code">{k}</span><span class="name">{v.get("name", "")}</span></div>'
            f'<div class="bench-bar"><div class="bench-fill {"in" if is_in else "out"}" style="width:{abs(main) / max_v * 100:.1f}%"></div></div>'
            f'<div class="bench-val {"in" if is_in else "out"}">{sign}{main:.2f}</div>'
            f'</div>'
        )

    in_rows = "".join(_row(k, v, max_in, True) for k, v in inflow)
    out_rows = "".join(_row(k, v, max_out, False) for k, v in outflow)
    return f'''
    <div class="flow-grid">
      <div class="flow-col in">
        <h3>{ICONS["up_arr"]} 净流入 Top 8 (主力净 · 亿)</h3>
        {in_rows}
      </div>
      <div class="flow-col out">
        <h3>{ICONS["down_arr"]} 净流出 Top 5 (主力净 · 亿)</h3>
        {out_rows}
      </div>
    </div>'''


def render_top5_cards(d: dict) -> str:
    bf = d.get("basket_flow", {})
    fund = d.get("fundamentals", {})
    t5 = d.get("top5_tech", {})
    top5 = rank_top5(bf, fund)
    weights = assign_weights(top5)
    medals = ["🥇 1", "🥈 2", "🥉 3", "4", "5"]

    cards = []
    for i, t in enumerate(top5, 1):
        info = t5.get(t["code"], {})
        f = fund.get(t["code"], {})
        dev20 = info.get("dev20", "")
        vol = info.get("vol_ratio", "")
        pe = f.get("pe", "n/a")
        # CSS classes for color-coding the dev20 / vol / PE metrics
        dev_class = "warn"  # default; refined below
        if dev20:
            try:
                dv = float(str(dev20).replace("%", ""))
                if dv < 5:
                    dev_class = "good"
                elif dv > 10:
                    dev_class = "bad"
            except (ValueError, TypeError):
                pass
        vol_class = ""
        if vol:
            try:
                if float(vol) > 1.5:
                    vol_class = "good"
            except (ValueError, TypeError):
                pass
        pe_class = ""
        if pe and pe != "n/a" and pe != "失真":
            pe_str = str(pe).replace("x", "")
            try:
                pe_val = float(pe_str)
                if pe_val < 20:
                    pe_class = "good"
                elif pe_val > 50:
                    pe_class = "warn"
            except ValueError:
                if "11" in pe_str:
                    pe_class = "good"
        cards.append(f'''
        <div class="rec-card" data-jump="{t['code']}">
          <div class="rec-jump-arrow">→ 跳到验证清单</div>
          <div class="rec-rank">{medals[i-1]}</div>
          <div class="rec-code">{t['code']}</div>
          <div class="rec-name">{t['name']}</div>
          <div class="rec-tier">T1+2 主题</div>
          <div class="rec-weight">
            <div class="num">{weights.get(t['code'], 0)}%</div>
            <div class="lbl">推荐权重</div>
          </div>
          <div class="rec-metrics">
            <div class="rec-metric"><span class="lbl">主力净</span><span class="val">+{t['main_net_yi']:.2f}亿</span></div>
            <div class="rec-metric"><span class="lbl">收盘</span><span class="val">{t['close']}</span></div>
            <div class="rec-metric"><span class="lbl">dev20</span><span class="val {dev_class}">{dev20}%</span></div>
            <div class="rec-metric"><span class="lbl">vol</span><span class="val {vol_class}">{vol}x</span></div>
            <div class="rec-metric"><span class="lbl">PE</span><span class="val">{pe}</span></div>
            <div class="rec-metric"><span class="lbl">H1</span><span class="val">{f.get('h1_earnings', 'n/a')}</span></div>
          </div>
          <div class="rec-logic"><strong>核心</strong> · {f.get('thesis', '基本面 + 技术面综合, 详见报告')}</div>
        </div>''')
    return f'<div class="rec-grid">{"".join(cards)}</div>'


def render_ma_table(d: dict) -> str:
    bf = d.get("basket_flow", {})
    fund = d.get("fundamentals", {})
    t5 = d.get("top5_tech", {})
    top5 = rank_top5(bf, fund)
    rows = []
    for t in top5:
        info = t5.get(t["code"], {})
        if not info:
            continue
        trend_class = "trend-bull" if info.get("trend") == "bull" else ("trend-bear" if info.get("trend") == "bear" else "trend-mix")
        dev20 = info.get("dev20", "")
        dev_class = "color: var(--good)" if dev20 and float(str(dev20).replace("%", "")) < 5 else ("color: var(--bad)" if dev20 and float(str(dev20).replace("%", "")) > 10 else "color: var(--ink-2)")
        rows.append(
            f'<tr><td><div class="code-cell">{t["code"]}</div><div class="name-cell">{t["name"]}</div></td>'
            f'<td>{info.get("close", "")}</td><td>{info.get("ma5", "")}</td><td>{info.get("ma10", "")}</td>'
            f'<td>{info.get("ma20", "")}</td><td>{info.get("ma60", "n/a")}</td>'
            f'<td class="{trend_class}">{info.get("trend", "n/a")}</td>'
            f'<td style="{dev_class}">{dev20}%</td><td>{info.get("pos20", "n/a")}%</td></tr>'
        )
    return f'''
    <table class="ma-table">
      <thead><tr>
        <th>代码 · 名称</th><th>收盘</th><th>MA5</th><th>MA10</th><th>MA20</th><th>MA60</th><th>趋势</th><th>dev20</th><th>pos20</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>'''


def render_crisis_drivers(d: dict) -> str:
    """v1.2: render theme-specific global drivers from d['theme']['global_drivers'].
    Falls back to legacy 4 food-security drivers if theme not present."""
    theme = _get_theme(d)
    drivers = theme.get("global_drivers") or [
        {"name": "黑海出口扰动", "stat": "-40%", "desc": "7 月底黑海出货量同比 -40%, 俄罗斯袭击敖德萨港口", "tag": "供给冲击 · 短期"},
        {"name": "厄尔尼诺 70 年最强", "stat": "强", "desc": "印度季风迟到, 印度洋偶极子 (IOD) 转正, 澳洲冬麦预估减产 21%", "tag": "气候冲击 · 中期"},
        {"name": "中东/霍尔木兹", "stat": "+144%", "desc": "霍尔木兹封锁风险, 藏格碳酸锂 +144%, 全球化肥供应链紧张", "tag": "成本传导 · 中长期"},
        {"name": "北半球减产", "stat": "+25%", "desc": "小麦自 2026/1 +25%, 创 2 年新高, FAO 7 月谷物 +3.4%", "tag": "供需失衡 · 持续"},
    ]
    icons = [ICONS["anchor"], ICONS["leaf"], ICONS["drop"], ICONS["grid"]]
    cards = []
    for i, drv in enumerate(drivers[:4]):
        cards.append(f'''<div class="crisis-card">
        <div class="crisis-head">
          <div class="crisis-icon">{icons[i % len(icons)]}</div>
          <div class="crisis-name">{drv.get("name", "—")}</div>
        </div>
        <div class="crisis-stat">{drv.get("stat", "—")}</div>
        <div class="crisis-desc">{drv.get("desc", "—")}</div>
        <span class="crisis-tag">{drv.get("tag", "—")}</span>
      </div>''')
    return f'''
    <div class="crisis-grid">
      {"".join(cards)}
    </div>'''


def render_a_share_snapshot(d: dict) -> str:
    snap = d.get("a_share_snapshot", {})
    if not snap.get("indices"):
        return '<p style="color: var(--ink-3); font-size: 14px;">A 股快照暂不可用 (web 报道未发布)。</p>'
    cells = []
    for k, v in snap["indices"].items():
        cells.append(f'<div class="snap-cell"><div class="snap-label">{k}</div><div class="snap-value">{v.get("price", "—")}</div><div class="snap-chg">{v.get("change_pct", "—")}%</div></div>')
    sectors_html = ""
    if snap.get("limit_up_sectors"):
        sectors_html += f'<div style="padding: 18px 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px;"><div style="font-size: 12px; font-weight: 600; color: var(--good); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 10px;">✓ 涨停潮板块</div><div style="font-size: 14px; color: var(--ink-2); line-height: 1.7;">{", ".join(snap["limit_up_sectors"])}</div></div>'
    if snap.get("laggard_sectors"):
        sectors_html += f'<div style="padding: 18px 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px;"><div style="font-size: 12px; font-weight: 600; color: var(--bad); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 10px;">✗ 拖累板块</div><div style="font-size: 14px; color: var(--ink-2); line-height: 1.7;">{", ".join(snap["laggard_sectors"])}</div></div>'
    return f'<div class="snapshot-grid">{"".join(cells)}</div><div style="margin-top: 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">{sectors_html}</div>'


def render_checklist(d: dict) -> str:
    theme = _get_theme(d)
    bf = d.get("basket_flow", {})
    fund = d.get("fundamentals", {})
    t5 = d.get("top5_tech", {})
    top5 = rank_top5(bf, fund)
    items = []
    for i, t in enumerate(top5, 1):
        info = t5.get(t["code"], {})
        items.append(f'<div class="check-item"><div class="check-num">{i}</div><div><strong>{t["name"]}</strong> 收盘 vs {info.get("close", "n/a")}, MA5/10/20/60 数字, dev20 {info.get("dev20", "n/a")}%, 趋势是否保持</div></div>')
    # v1.2: theme-specific extra verification items
    extras = theme.get("verification_extras") or [
        "农业板块是否延续强势, <strong>国证 399365</strong> 是否突破, 量能是否放大",
        "<strong>粮食 ETF 鹏华 159698</strong> 净流入是否持续, 主题资金面",
    ]
    n_top5 = len(top5)
    for i, ex in enumerate(extras, n_top5 + 1):
        items.append(f'<div class="check-item"><div class="check-num">{i}</div><div>{ex}</div></div>')
    # Always-on sanity checks
    basket_size = (theme.get("basket") or {}).get("size") or 35
    basket_source = (theme.get("basket") or {}).get("source", "mommy")
    items.append(f'<div class="check-item"><div class="check-num">{n_top5 + len(extras) + 1}</div><div>重跑 <code>{basket_source} list</code> 确认 {basket_size} 只都在, <code>flows pull</code> 看限流能不能补上</div></div>')
    items.append(f'<div class="check-item"><div class="check-num">{n_top5 + len(extras) + 2}</div><div>重拉 5 只 K线对照 MA5/10/20/60 数字, 与本报告 data.json 对比</div></div>')
    items.append(f'<div class="check-item"><div class="check-num">{n_top5 + len(extras) + 3}</div><div>memory topic 锚点是否清晰可对照</div></div>')
    return f'<div class="check-grid">{"".join(items)}</div>'


def render_files(d: dict) -> str:
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    return f'''
    <div class="file-grid">
      <div class="file-card"><div class="file-icon">{ICONS["doc"]}</div><div class="file-info"><div class="file-name">report.md</div><div class="file-meta">完整报告 · ≥ 30 KB</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["doc"]}</div><div class="file-info"><div class="file-name">strategy-card.md</div><div class="file-meta">策略卡草稿 · ≥ 8 KB</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["package"]}</div><div class="file-info"><div class="file-name">web.html</div><div class="file-meta">自包含可视化报告</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["db"]}</div><div class="file-info"><div class="file-name">data.json</div><div class="file-meta">原始数据 (basket + top5 + global)</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["settings"]}</div><div class="file-info"><div class="file-name">mommy food-security CLI</div><div class="file-meta">自建 · 跟 semicon 平行 · 7 子命令</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["memory"]}</div><div class="file-info"><div class="file-name">memory topic: food-security-{today_bj}</div><div class="file-meta">Top 5 + 验证清单</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["package"]}</div><div class="file-info"><div class="file-name">deliverables/food-security/{today_bj}.zip</div><div class="file-meta">per-day 归档 · daily-final/ + runs/ + manifest.json</div></div></div>
      <div class="file-card"><div class="file-icon">{ICONS["target"]}</div><div class="file-info"><div class="file-name">reference.db · food_security_stocks</div><div class="file-meta">35 只 · 4 chain × 14 subcategory</div></div></div>
    </div>'''


def render_topbar(d: dict) -> str:
    """Sticky topbar: brand + section nav + theme + mode + download dropdown (v1.2)."""
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    is_close = d.get("is_market_close", False)
    data_label = "close" if is_close else "mid-day"
    theme = _get_theme(d)
    basket_size = (theme.get("basket") or {}).get("size") or 35
    theme_short = theme["name"].split("/")[0] if "/" in theme["name"] else theme["name"]
    sections = [
        ("hero", "封面"), ("triggers", "4 变量"), ("basket", f"{basket_size} 只篮子"),
        ("flow", "资金流"), ("top5", "Top 5"), ("ma", "均线"),
        ("charts", "时序图"), ("crisis", "全球驱动"),
        ("snapshot", "A 股快照"), ("checklist", "验证清单"),
        ("strategy", "策略卡"), ("report-md", "报告原文"), ("files", "下载"),
    ]
    nav_html = "\n".join(
        f'<a class="topbar-link" href="#section-{sid}">{i}. {label}</a>'
        for i, (sid, label) in enumerate(sections, 1)
    )
    return f'''<nav class="topbar">
  <div class="topbar-inner">
    <div class="topbar-brand">{theme_short} · {today_bj} {data_label}</div>
    <div class="topbar-nav">{nav_html}</div>
    <div class="topbar-actions">
      <button class="toggle-btn" id="btn-mode" type="button" aria-label="切换图表/纯文字模式">
        <svg id="icon-mode" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
        <span id="label-mode">纯文字</span>
      </button>
      <button class="toggle-btn" id="btn-theme" type="button" aria-label="切换深/浅色">
        <svg id="icon-theme" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        <span id="label-theme">深色</span>
      </button>
      <div class="dropdown" id="dl-dropdown">
        <button class="toggle-btn toggle-btn-primary" type="button" aria-label="下载文件">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          <span>下载</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:10px"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        <div class="dropdown-menu">
          <div class="dropdown-group">完整报告</div>
          <a class="dropdown-item" href="report.pdf" download>
            <span class="dl-icon">📕</span><span>report.pdf</span><span class="dl-meta">打印版</span>
          </a>
          <a class="dropdown-item" href="report.html" target="_blank">
            <span class="dl-icon">🌐</span><span>report.html</span><span class="dl-meta">独立网页</span>
          </a>
          <a class="dropdown-item" href="report.md" download>
            <span class="dl-icon">📄</span><span>report.md</span><span class="dl-meta">Markdown 源</span>
          </a>
          <div class="dropdown-group">策略卡</div>
          <a class="dropdown-item" href="strategy-card.pdf" download>
            <span class="dl-icon">📕</span><span>strategy-card.pdf</span><span class="dl-meta">打印版</span>
          </a>
          <a class="dropdown-item" href="strategy-card.html" target="_blank">
            <span class="dl-icon">🌐</span><span>strategy-card.html</span><span class="dl-meta">独立网页</span>
          </a>
          <a class="dropdown-item" href="strategy-card.md" download>
            <span class="dl-icon">📄</span><span>strategy-card.md</span><span class="dl-meta">Markdown 源</span>
          </a>
          <div class="dropdown-group">其他</div>
          <a class="dropdown-item" href="text.md" download>
            <span class="dl-icon">📄</span><span>text.md</span><span class="dl-meta">纯文字版</span>
          </a>
          <a class="dropdown-item" href="data.json" download>
            <span class="dl-icon">🗄️</span><span>data.json</span><span class="dl-meta">原始数据</span>
          </a>
        </div>
      </div>
    </div>
  </div>
</nav>'''


def render_strategy_section(strategy_html: str) -> str:
    """v1.2 — embed rendered strategy-card.md content as a readable section."""
    if not strategy_html:
        return ""
    return f'''
    <section id="section-strategy">
      <div class="section-head">
        <div class="section-num">11</div>
        <div>
          <h2>策略卡 · 草稿</h2>
          <p>由 <code>strategy-card.md</code> 渲染 (markdown → HTML, Python markdown lib). 草稿, 未保存到 portfolio.db. <a href="strategy-card.md" download>下载 .md</a> · <a href="strategy-card.pdf" download>下载 .pdf</a></p>
        </div>
      </div>
      <article class="embedded-doc">{strategy_html}</article>
    </section>'''


def render_report_md_section(report_html: str) -> str:
    """v1.2 — embed rendered report.md content as a readable section."""
    if not report_html:
        return ""
    return f'''
    <section id="section-report-md">
      <div class="section-head">
        <div class="section-num">12</div>
        <div>
          <h2>报告原文 · Markdown 渲染</h2>
          <p>由 <code>report.md</code> 渲染 (markdown → HTML, Python markdown lib). 完整版报告, ≥30KB, 11 sections. <a href="report.md" download>下载 .md</a> · <a href="report.pdf" download>下载 .pdf</a> · <a href="report.html" target="_blank">独立网页</a></p>
        </div>
      </div>
      <article class="embedded-doc">{report_html}</article>
    </section>'''


def render_print_button() -> str:
    """v1.2 — floating "Save as PDF" button (uses window.print())."""
    return '''
    <button class="print-fab" id="btn-print" type="button" title="保存当前网页为 PDF (浏览器内置打印)">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z"/></svg>
      <span>另存 PDF</span>
    </button>'''


def render_files_v12(d: dict) -> str:
    """v1.2 — updated files list with 9 deliverables (was 5)."""
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    cards = []
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["doc"]}</div><div class="file-info"><div class="file-name">report.md</div><div class="file-meta">完整报告 Markdown · ≥ 30 KB · 11 sections</div></div></div>')
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["package"]}</div><div class="file-info"><div class="file-name">report.html</div><div class="file-meta">独立网页 (深色 + 打印 CSS)</div></div></div>')
    cards.append(f'<div class="file-icon-pdf">📕</div><div class="file-info"><div class="file-name">report.pdf</div><div class="file-meta">打印版 PDF (chromium 生成)</div></div></div>')
    # 修正: file-card 包所有内容
    cards[-1] = f'<div class="file-card"><div class="file-icon-pdf">📕</div><div class="file-info"><div class="file-name">report.pdf</div><div class="file-meta">打印版 PDF (chromium 生成)</div></div></div>'
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["doc"]}</div><div class="file-info"><div class="file-name">strategy-card.md</div><div class="file-meta">策略卡 Markdown · ≥ 8 KB</div></div></div>')
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["package"]}</div><div class="file-info"><div class="file-name">strategy-card.html</div><div class="file-meta">独立网页</div></div></div>')
    cards.append(f'<div class="file-card"><div class="file-icon-pdf">📕</div><div class="file-info"><div class="file-name">strategy-card.pdf</div><div class="file-meta">策略卡 PDF</div></div></div>')
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["package"]}</div><div class="file-info"><div class="file-name">web.html</div><div class="file-meta">主可视化报告 (深色 + Chart.js + hover/click + 内嵌 report+strategy)</div></div></div>')
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["doc"]}</div><div class="file-info"><div class="file-name">text.md</div><div class="file-meta">纯文字版 (零图, 零 CDN)</div></div></div>')
    cards.append(f'<div class="file-card"><div class="file-icon">{ICONS["db"]}</div><div class="file-info"><div class="file-name">data.json</div><div class="file-meta">原始数据 (basket + top5 + flow_ts + global)</div></div></div>')
    return f'''
    <div class="file-grid">
      {"".join(cards)}
    </div>'''





def render_charts_section(d: dict) -> str:
    """Chart.js time-series charts (money flow + 4-variable history).
    Data is embedded as JSON in a <script> tag for the JS to consume."""
    import json as _json
    # Money flow time series for top 5 (if present in data)
    flow_ts = d.get("top5_flow_ts", {})
    # 4-variable history (last 6 months, static for now — fetched at analysis time)
    var_history = d.get("variable_history", {
        "months": ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08E"],
        "fao_index": [127.4, 128.3, 129.5, 130.5, 131.1, 131.6],
        "el_nino_strength": [1.2, 1.5, 1.8, 2.1, 2.4, 2.5],
        "fpi_pe_pctile": [28, 30, 32, 34, 36.5, 38],
        "ukraine_grain_yoy": [-25, -32, -38, -42, -40, -38],
    })
    triggers = _get_theme(d).get("trigger_variables") or []
    var_names = [t.get("label", f"var{i+1}") for i, t in enumerate(triggers)] or \
                ["FAO 食品价格指数", "厄尔尼诺强度", "FPI PE 10 年分位", "黑海谷物同比"]
    var_data_keys = list(var_history.keys())[1:5]  # skip "months"
    return f'''
    <div class="chart-grid">
      <div class="chart-card">
        <div class="chart-title">Top 5 主力资金流时序 · 240 分钟</div>
        <div class="chart-sub">仅今日快照, 收盘瞬时主力净额 (亿元) · 颜色 = 个股</div>
        <div class="chart-wrap"><canvas id="chart-flow-ts"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">4 变量触发 · 6 月历史</div>
        <div class="chart-sub">{" / ".join(var_names)}</div>
        <div class="chart-wrap"><canvas id="chart-vars"></canvas></div>
      </div>
    </div>
    <script type="application/json" id="chart-data">{_json.dumps({
        "flow_ts": flow_ts,
        "var_history": var_history,
        "var_labels": var_names,
        "top5_codes": list(d.get("top5_tech", {}).keys()),
    }, ensure_ascii=False)}</script>
'''


def render_html(d: dict, session_id: str = "n/a",
               report_html: str = "", strategy_html: str = "",
               report_md_raw: str = "", strategy_md_raw: str = "") -> str:
    """v1.2: now accepts report_html/strategy_html (rendered from .md via
    Python markdown lib) AND report_md_raw/strategy_md_raw (the original .md
    source). The HTML versions get embedded as readable sections; the raw
    .md is stored in <script type="text/plain"> tags so the download
    dropdown can extract them via Blob (works in deployed previews where
    the file-system links 404).
    """
    today_bj = d.get("trading_day", "YYYY-MM-DD")
    is_close = d.get("is_market_close", False)
    data_label = "close" if is_close else "mid-day"
    now_iso = d.get("generated_at", fmt_bj_iso(now_bj()))
    theme = _get_theme(d)
    basket_size = (theme.get("basket") or {}).get("size") or 35
    theme_name_short = theme["name"].split("/")[0] if "/" in theme["name"] else theme["name"]
    n_triggers = len(theme.get("trigger_variables") or [1,2,3,4])

    sections = []
    sections.append(f'''
    <header class="hero" id="section-hero">
      {render_hero(d)}
    </header>''')
    sections.append(f'''
    <section id="section-triggers">
      <div class="section-head"><div class="section-num">01</div><div><h2>4 变量触发 · 主题动能监控</h2><p>{theme["name"]} 主题需 {n_triggers} 变量共振, 板块整体可超配。任一变量反转即降级。</p></div></div>
      {render_triggers(d)}
    </section>''')
    sections.append(f'''
    <section id="section-basket">
      <div class="section-head"><div class="section-num">02</div><div><h2>主题篮子 · {basket_size} 只</h2><p>来源: {theme.get("basket", {}).get("source", "—")} — 4 chain 分布见下方。</p></div></div>
      {render_chain_basket()}
    </section>''')
    sections.append(f'''
    <section id="section-flow">
      <div class="section-head"><div class="section-num">03</div><div><h2>主力资金流 · {today_bj} {data_label}</h2><p>净流入 Top 8 + 净流出 Top 5, 鼠标悬停查看每只资金流明细。</p></div></div>
      {render_money_flow(d)}
    </section>''')
    sections.append(f'''
    <section id="section-top5">
      <div class="section-head"><div class="section-num">04</div><div><h2>Top 5 推荐 · 高弹性 + 基本面 + 技术面</h2><p>{theme.get("top5_intro", "高弹性 + 稳健兼具")}。点击卡片可跳到对应验证清单条目。</p></div></div>
      {render_top5_cards(d)}
    </section>''')
    sections.append(f'''
    <section id="section-ma">
      <div class="section-head"><div class="section-num">05</div><div><h2>均线技术面对比 · 60 日 K线</h2><p>dev20 在 ±5% 内 = 健康; &gt; 10% = 超买; &lt; -10% = 超跌。</p></div></div>
      {render_ma_table(d)}
    </section>''')
    sections.append(f'''
    <section id="section-charts">
      <div class="section-head"><div class="section-num">06</div><div><h2>时序图 · Chart.js 交互</h2><p>资金流分钟级演化 + 4 变量 6 月历史 (Chart.js 渲染, 非 PNG 静态)。可隐藏切换纯文字模式。</p></div></div>
      {render_charts_section(d)}
    </section>''')
    sections.append(f'''
    <section id="section-crisis">
      <div class="section-head"><div class="section-num">07</div><div><h2>全球 {theme_name_short} · 4 大驱动</h2><p>主题的全球宏观背景, 4 变量驱动的具体来源。</p></div></div>
      {render_crisis_drivers(d)}
    </section>''')
    sections.append(f'''
    <section id="section-snapshot">
      <div class="section-head"><div class="section-num">08</div><div><h2>A 股 {today_bj} 午间/收盘快照</h2><p>大盘 + 板块表现, 直接关联 {theme_name_short} 主题资金画像。</p></div></div>
      {render_a_share_snapshot(d)}
    </section>''')
    sections.append(f'''
    <section id="section-checklist">
      <div class="section-head"><div class="section-num">09</div><div><h2>次日验证清单</h2><p>每项都有具体对照点, 用本报告的 data.json 锚点直接对数字。</p></div></div>
      {render_checklist(d)}
    </section>''')
    # v1.2 — embed rendered strategy card and report markdown
    sections.append(render_strategy_section(strategy_html))
    sections.append(render_report_md_section(report_html))
    sections.append(f'''
    <section id="section-files">
      <div class="section-head"><div class="section-num">13</div><div><h2>下载与交付</h2><p>9 个 deliverable + per-day ZIP. 顶栏右上「下载」下拉里有全部链接. 右下浮窗可另存为 PDF.</p></div></div>
      {render_files_v12(d)}
    </section>''')

    body = "\n".join(sections)
    title = f"{theme['name']} · {today_bj} {data_label} · 主题分析"

    # v1.2: embed raw .md sources as plain text scripts for Blob download
    # (used by the dropdown when the file links 404 in deployed previews)
    def _esc(s: str) -> str:
        return s.replace("</", "<\\/").replace("<!--", "<\\!--")

    return f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="light" data-mode="visual">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="data-as-of" content="{today_bj} {data_label} (Beijing)">
<meta name="generated-at" content="{now_iso}">
<meta name="session-id" content="{session_id}">
<meta name="skill" content="food-security-analysis">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>

{render_topbar(d)}

<div class="container">{body}</div>

<footer>
  <p><strong>Food Security Analysis</strong> · skill food-security-analysis v1.2 · {today_bj} {data_label} (北京时间)</p>
  <p>35 只篮子 · 4 变量触发 · Top 5 推荐 · data.json + manifest.json 完整可审计</p>
  <p style="margin-top: 12px; color: var(--ink-3); font-size: 11px;">⚠️ 本报告为研究/教学/个人投资参考, 不是投资建议, 不构成任何买卖推荐</p>
</footer>

{render_print_button()}

<!-- v1.2: raw .md sources for Blob-based download fallback (when file links 404) -->
<script type="text/plain" id="raw-report-md">{_esc(report_md_raw)}</script>
<script type="text/plain" id="raw-strategy-md">{_esc(strategy_md_raw)}</script>

<script>
/* --- theme toggle (light / dark) --- */
(function() {{
  var html = document.documentElement;
  var saved = localStorage.getItem('fs-theme');
  var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var initial = saved || (prefersDark ? 'dark' : 'light');
  html.setAttribute('data-theme', initial);
  var labelTheme = document.getElementById('label-theme');
  if (labelTheme) labelTheme.textContent = initial === 'dark' ? '浅色' : '深色';
  document.addEventListener('DOMContentLoaded', function() {{
    var btn = document.getElementById('btn-theme');
    if (!btn) return;
    btn.addEventListener('click', function() {{
      var cur = html.getAttribute('data-theme') || 'light';
      var nxt = cur === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', nxt);
      localStorage.setItem('fs-theme', nxt);
      document.getElementById('label-theme').textContent = nxt === 'dark' ? '浅色' : '深色';
      // update Chart.js colors
      if (window.__fsCharts) {{
        Object.values(window.__fsCharts).forEach(function(c) {{ c.update(); }});
      }}
    }});
  }});
}})();

/* --- mode toggle (visual / text) --- */
document.addEventListener('DOMContentLoaded', function() {{
  var html = document.documentElement;
  var btn = document.getElementById('btn-mode');
  var label = document.getElementById('label-mode');
  if (!btn) return;
  btn.addEventListener('click', function() {{
    var cur = html.getAttribute('data-mode') || 'visual';
    var nxt = cur === 'visual' ? 'text' : 'visual';
    html.setAttribute('data-mode', nxt);
    label.textContent = nxt === 'text' ? '可视化' : '纯文字';
  }});
}});

/* --- active nav highlight (scroll spy) --- */
document.addEventListener('DOMContentLoaded', function() {{
  var links = document.querySelectorAll('.topbar-link');
  var sections = Array.from(links).map(function(l) {{
    var id = l.getAttribute('href').slice(1);
    return {{ link: l, el: document.getElementById(id) }};
  }});
  function setActive() {{
    var scrollY = window.scrollY + 100;
    var active = null;
    sections.forEach(function(s) {{
      if (s.el && s.el.offsetTop <= scrollY) active = s;
    }});
    links.forEach(function(l) {{ l.classList.remove('active'); }});
    if (active) active.link.classList.add('active');
  }}
  window.addEventListener('scroll', setActive, {{ passive: true }});
  setActive();
}});

/* --- rec-card click → scroll to checklist item --- */
document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('.rec-card[data-jump]').forEach(function(card) {{
    card.addEventListener('click', function() {{
      var code = card.getAttribute('data-jump');
      var target = document.querySelector('#section-checklist');
      if (target) target.scrollIntoView({{ behavior: 'smooth' }});
    }});
  }});
}});

/* --- v1.2: download dropdown toggle + Blob fallback --- */
document.addEventListener('DOMContentLoaded', function() {{
  var dd = document.getElementById('dl-dropdown');
  if (!dd) return;
  var trigger = dd.querySelector('.toggle-btn-primary');
  if (trigger) {{
    trigger.addEventListener('click', function(e) {{
      e.stopPropagation();
      dd.classList.toggle('open');
    }});
  }}
  document.addEventListener('click', function() {{ dd.classList.remove('open'); }});
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') dd.classList.remove('open');
  }});

  // Intercept .md download links: if file 404s (deployed preview), fall back
  // to extracting the embedded raw .md and triggering a Blob download.
  document.querySelectorAll('.dropdown-item[href$=".md"]').forEach(function(a) {{
    a.addEventListener('click', function(e) {{
      var href = a.getAttribute('href');
      fetch(href, {{ method: 'HEAD' }}).then(function(r) {{
        if (r.ok) return;  // file exists, let the browser handle it
        // Fallback: extract from embedded source
        e.preventDefault();
        var fname = href.split('/').pop();
        var sid = fname === 'report.md' ? 'raw-report-md' : (fname === 'strategy-card.md' ? 'raw-strategy-md' : null);
        if (!sid) return;
        var raw = document.getElementById(sid);
        if (!raw) return;
        var blob = new Blob([raw.textContent], {{ type: 'text/markdown;charset=utf-8' }});
        var url = URL.createObjectURL(blob);
        var dl = document.createElement('a');
        dl.href = url; dl.download = fname;
        document.body.appendChild(dl); dl.click();
        document.body.removeChild(dl);
        URL.revokeObjectURL(url);
      }}).catch(function() {{ /* network error, let browser try anyway */ }});
    }});
  }});
}});

/* --- v1.2: floating "save as PDF" button --- */
document.addEventListener('DOMContentLoaded', function() {{
  var btn = document.getElementById('btn-print');
  if (btn) btn.addEventListener('click', function() {{
    window.print();
  }});
}});
    }});
  }});
}});

/* --- Chart.js (loaded only when network available; degrades gracefully) --- */
(function() {{
  var script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
  script.onload = function() {{
    var raw = document.getElementById('chart-data');
    if (!raw) return;
    var payload = JSON.parse(raw.textContent);
    var isDark = (document.documentElement.getAttribute('data-theme') === 'dark');
    var tickColor = isDark ? '#a8b0c0' : '#7c7a72';
    var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
    var colors = ['#2f6f5e', '#c97b3f', '#b06367', '#5a7da5', '#8c6a99'];

    /* money flow time-series */
    var flowCanvas = document.getElementById('chart-flow-ts');
    if (flowCanvas && payload.flow_ts && Object.keys(payload.flow_ts).length > 0) {{
      var codes = payload.top5_codes || Object.keys(payload.flow_ts);
      var ts = payload.flow_ts[codes[0]] || [];
      var labels = ts.map(function(p) {{ return p.time || ''; }});
      var datasets = codes.map(function(c, i) {{
        var arr = payload.flow_ts[c] || [];
        return {{
          label: c,
          data: arr.map(function(p) {{ return p.main_net_yi || 0; }}),
          borderColor: colors[i % colors.length],
          backgroundColor: colors[i % colors.length] + '22',
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        }};
      }});
      new Chart(flowCanvas, {{
        type: 'line',
        data: {{ labels: labels, datasets: datasets }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{
            legend: {{ position: 'bottom', labels: {{ color: tickColor, font: {{ size: 11 }} }} }},
            tooltip: {{ callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(3) + '亿'; }} }} }},
          }},
          scales: {{
            x: {{ ticks: {{ color: tickColor, maxRotation: 0, autoSkipPadding: 24 }}, grid: {{ color: gridColor }} }},
            y: {{ ticks: {{ color: tickColor, callback: function(v) {{ return v.toFixed(2) + '亿'; }} }}, grid: {{ color: gridColor }} }},
          }},
        }},
      }});
    }} else if (flowCanvas) {{
      flowCanvas.parentElement.innerHTML = '<p style="color: var(--ink-3); text-align: center; padding: 60px 0; font-size: 12px;">资金流时序未拉到 (限流/收盘后不可补), 跳过本图</p>';
    }}

    /* 4-variable history (mixed chart) — labels come from theme config */
    var varsCanvas = document.getElementById('chart-vars');
    if (varsCanvas && payload.var_history) {{
      var h = payload.var_history;
      var varLabels = (payload.var_labels && payload.var_labels.length) ? payload.var_labels
                       : ['FAO 食品价格指数', '厄尔尼诺强度', 'FPI PE 10 年分位', '黑海谷物同比'];
      var varDataKeys = ['fao_index', 'el_nino_strength', 'fpi_pe_pctile', 'ukraine_grain_yoy'];
      var varColors = ['#2f6f5e', '#c97b3f', '#5a7da5', '#b06367'];
      var datasets = varLabels.map(function(lbl, i) {{
        var key = varDataKeys[i] || varDataKeys[varDataKeys.length - 1];
        var yAxis = (i === 3) ? 'y2' : 'y';
        return {{
          label: lbl,
          data: h[key] || [],
          backgroundColor: varColors[i] || '#2f6f5e',
          yAxisID: yAxis,
        }};
      }});
      new Chart(varsCanvas, {{
        type: 'bar',
        data: {{
          labels: h.months,
          datasets: datasets,
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{
            legend: {{ position: 'bottom', labels: {{ color: tickColor, font: {{ size: 11 }} }} }},
          }},
          scales: {{
            x: {{ ticks: {{ color: tickColor }}, grid: {{ color: gridColor }} }},
            y: {{ position: 'left', ticks: {{ color: tickColor }}, grid: {{ color: gridColor }}, title: {{ display: true, text: '绝对值', color: tickColor }} }},
            y2: {{ position: 'right', ticks: {{ color: tickColor, callback: function(v) {{ return v + '%'; }} }}, grid: {{ display: false }}, title: {{ display: true, text: '同比 %', color: tickColor }} }},
          }},
        }},
      }});
    }}
  }};
  script.onerror = function() {{
    document.querySelectorAll('.chart-wrap').forEach(function(w) {{
      w.innerHTML = '<p style="color: var(--ink-3); text-align: center; padding: 60px 0; font-size: 12px;">Chart.js CDN 不可达, 时序图不可用 (数据本身仍可下载 data.json)</p>';
    }});
  }};
  document.body.appendChild(script);
}})();
</script>

</body>
</html>'''


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python html_render.py data.json [out.html]")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)
    html = render_html(data)
    out = sys.argv[2] if len(sys.argv) > 2 else "out.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  wrote {out} ({len(html)} bytes)")
