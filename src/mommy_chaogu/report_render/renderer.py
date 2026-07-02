"""把 ReportData 渲染成独立 HTML 页面。

模板 + 数据 + (后续)AI 导语，三件合并出一份当日专属的报告页。
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from mommy_chaogu.report_render.parser import ReportData, SectorRow

# 模板所在目录
_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ───────────────────────── 主题色 ─────────────────────────


def _theme_for(report: ReportData) -> tuple[str, str, str]:
    """根据当日净合计选主题色（accent, accent-soft, bg）。

    - 当日净 > 5亿：暖红（资金涌入）
    - 当日净 < -5亿：冷青（资金撤退）
    - 当日净 ≈ 0：中灰
    """
    t = report.today_total
    if t >= Decimal("5e8"):
        return ("#d6336c", "rgba(214,51,108,0.12)", "#fef3f6")
    if t <= Decimal("-5e8"):
        return ("#1971c2", "rgba(25,113,194,0.12)", "#f3f8fc")
    return ("#5c6168", "rgba(92,97,104,0.10)", "#f5f6f7")


def _strongest_weakest(sectors: list[SectorRow]) -> tuple[SectorRow, SectorRow]:
    return max(sectors, key=lambda s: s.ratio_bp), min(sectors, key=lambda s: s.ratio_bp)


# ───────────────────────── Hero 文案 ─────────────────────────


def _build_hero(report: ReportData) -> tuple[str, str]:
    """根据数据派生 Hero 标题 + 导语（数据驱动，第一阶段不上 LLM）。"""

    weekday_cn = "一二三四五六日"[report.day.weekday()]
    month_d = report.day.day
    _ = weekday_cn  # 留给后续 hero 文案扩展

    t = report.today_total
    if t > Decimal("3e8"):
        mood = "净流入日"
    elif t < Decimal("-3e8"):
        mood = "净流出日"
    else:
        mood = "震荡日"

    strong, weak = _strongest_weakest(report.sectors)
    title = f"{month_d} 日半导体{mood}：{strong.name}领涨，{weak.name}承压"

    # 顶部流入个股
    lead_in = report.top_inflows[0]

    def fmt_yi(v: Decimal) -> str:
        return f"{(v / Decimal('1e8')).quantize(Decimal('0.01'))}亿"

    parts: list[str] = []
    if t > 0:
        parts.append(f"今天全池 <strong class='pos'>+{fmt_yi(t)}</strong>主力净流入")
    elif t < 0:
        parts.append(f"今天全池 <strong class='neg'>{fmt_yi(t)}</strong>主力净流出")
    else:
        parts.append("今天全池基本持平")

    if strong.ratio_bp > 0 and weak.ratio_bp < 0:
        parts.append(
            f"{strong.name}以 <strong>+{strong.ratio_bp}bp</strong> 领跑"
            f"，{weak.name}以 <strong>{weak.ratio_bp}bp</strong> 拖累"
        )

    parts.append(f"领涨个股 <strong>{lead_in.name}</strong>（+{lead_in.ratio_bp}bp）")
    if report.contradictions:
        c = report.contradictions[0]
        bp30 = c.extra.get("days_30_bp", Decimal(0))
        bp30_abs = int(-bp30) if isinstance(bp30, Decimal) else 0
        parts.append(f"<strong>{c.name}</strong>30d流出{bp30_abs}bp、今天逆势流入")

    lede = " · ".join(parts) + "。"
    return title, lede


# ───────────────────────── Bar 宽度 ─────────────────────────


def _bar_width(s: SectorRow, max_abs: Decimal) -> float:
    """计算 sector bar 的宽度（左半 or 右半，0-50%）。"""
    if max_abs == 0:
        return 0.0
    return min(50.0, abs(float(s.ratio_bp)) / float(max_abs) * 50.0)


# ───────────────────────── Render ─────────────────────────


def _yi(v: Decimal | None) -> float:
    """元 → 亿（float）。"""
    if v is None:
        return 0.0
    return float(v) / 1e8


def _yi_str(v: Decimal | None, n: int = 2) -> str:
    s = f"{_yi(v):.{n}f}"
    # 去掉无意义的负零
    if s == f"-{'0' * n}.{'0' * n}":
        return "0." + "0" * n
    return s


def _bp_str(v: Decimal | None, n: int = 1) -> str:
    if v is None:
        return "0.0"
    return f"{float(v):.{n}f}"


def _sign_prefix(v: Decimal | None) -> str:
    """>= 0 时返回 '+' (前端再加)。实际渲染时不用这里。"""
    return "+" if v is not None and v > 0 else ""


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["yi"] = _yi
    env.filters["yi_str"] = _yi_str
    env.filters["bp_str"] = _bp_str
    env.filters["sign_prefix"] = _sign_prefix
    return env


def _weekday_cn(d: date) -> str:
    return "一二三四五六日"[d.weekday()]


def render_report_html(report: ReportData) -> str:
    """单日报告 → 独立 HTML 字符串。"""

    env = _make_env()
    tmpl = env.get_template("report.html.j2")

    accent, soft, bg = _theme_for(report)
    sectors_max_abs = max(
        ((abs(s.ratio_bp) for s in report.sectors)),
        default=Decimal(0),
    )

    strong, weak = _strongest_weakest(report.sectors)
    hero_title, hero_lede = _build_hero(report)

    return tmpl.render(
        report=report,
        is_index=False,
        theme_color=accent,
        theme_soft=soft,
        bg_color=bg,
        weekday_cn=_weekday_cn(report.day),
        strongest_sector=strong,
        weakest_sector=weak,
        hero_title=hero_title,
        hero_lede=hero_lede,
        sector_bar_width=lambda s: _bar_width(s, sectors_max_abs),
        generated_at=date.today().isoformat(),
    )


def render_index_html(reports: list[ReportData]) -> str:
    """历史报告索引 → 独立 HTML 字符串。"""

    env = _make_env()
    tmpl = env.get_template("report.html.j2")

    return tmpl.render(
        report=None,
        is_index=True,
        reports=sorted(reports, key=lambda r: r.day, reverse=True),
        theme_color="#5c6168",
        theme_soft="rgba(92,97,104,0.10)",
        bg_color="#f8f9fa",
        generated_at=date.today().isoformat(),
    )


def render_one(report: ReportData, *, out_dir: str | Path) -> Path:
    """渲染单日报告，写到 `out_dir/<day>.html`。"""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html = render_report_html(report)
    path = out / f"{report.day.isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    return path


def render_index(reports: list[ReportData], *, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html = render_index_html(reports)
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


# calendar 模块保留引用防止 dead-code 警告（已在 _weekday_cn 中使用原则一致）
_ = calendar
