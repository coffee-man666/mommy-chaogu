from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.report_render import (
    parse_markdown_report,
    render_index,
    render_index_html,
    render_one,
    render_report_html,
)
from mommy_chaogu.report_render.parser import ReportData, SectorRow, StockRow, _decimal


def _report(tmp_path: Path, today_total: str = "600000000") -> ReportData:
    return ReportData(
        day=date(2026, 7, 14),
        pool_name="半导体",
        pool_size=2,
        covered=2,
        covered_ratio=1.0,
        today_total=Decimal(today_total),
        days_30_total=Decimal("-100000000"),
        sectors=[
            SectorRow("上游", 1, Decimal("700000000"), Decimal("1e10"), Decimal("7")),
            SectorRow("下游", 1, Decimal("-100000000"), Decimal("2e10"), Decimal("-2")),
        ],
        top_inflows=[
            StockRow(1, "600001", "甲公司", "设备", Decimal("5e8"), Decimal("1e10"), Decimal("5"))
        ],
        top_outflows=[
            StockRow(1, "600002", "乙公司", "制造", Decimal("-1e8"), Decimal("2e10"), Decimal("-1"))
        ],
        contradictions=[
            StockRow(
                None,
                "600003",
                "丙公司",
                extra={
                    "today_bp": Decimal("2"),
                    "days_30_bp": Decimal("-12"),
                    "today_net": Decimal("2e8"),
                    "days_30_net": Decimal("-4e8"),
                },
            )
        ],
        source_path=tmp_path / "report.md",
    )


def test_parse_markdown_report(tmp_path: Path) -> None:
    source = tmp_path / "report.md"
    source.write_text(
        """# 资金流收盘日报 · 2026-07-14 · 半导体

**池子**：2 只
**覆盖**：2/2 只
**当日主力净合计**：+6.00亿
**30d 累计主力净合计**：-1.00亿

## 📊 板块汇总
| 板块 | 数量 | 当日 | 流通市值 | ratio |
|---|---:|---:|---:|---:|
| 上游 | 1 | +7亿 | 100亿 | **+7bp** |
## 🟢 TOP 流入
| 排名 | 代码 | 名称 | 分类 | 净流入 | 市值 | ratio |
|---:|---|---|---|---:|---:|---:|
| 1 | 600001 | 甲公司 | 设备 | +5亿 | 100亿 | +5bp |
## 🔴 TOP 流出
| 排名 | 代码 | 名称 | 分类 | 净流入 | 市值 | ratio |
|---:|---|---|---|---:|---:|---:|
| 1 | 600002 | 乙公司 | 制造 | -1亿 | 200亿 | -1bp |
## ⚠️ 矛盾股
| 代码 | 名称 | 今日bp | 30dbp | 今日净额 | 30d净额 |
|---|---|---:|---:|---:|---:|
| 600003 | 丙公司 | +2bp | -12bp | +2亿 | -4亿 |
---
""",
        encoding="utf-8",
    )
    report = parse_markdown_report(source)
    assert report.day == date(2026, 7, 14)
    assert report.today_total == Decimal("6e8")
    assert report.sectors[0].ratio_bp == Decimal("7")
    assert report.top_inflows[0].name == "甲公司"
    assert report.contradictions[0].extra["days_30_bp"] == Decimal("-12")


def test_render_report_and_index(tmp_path: Path) -> None:
    report = _report(tmp_path)
    html = render_report_html(report)
    assert "14 日半导体净流入日" in html
    assert "甲公司" in html
    assert render_one(report, out_dir=tmp_path).read_text(encoding="utf-8") == html
    index_html = render_index_html([report])
    assert "2026-07-14" in index_html
    assert render_index([report], out_dir=tmp_path).name == "index.html"


def test_render_theme_variants_and_decimal_units(tmp_path: Path) -> None:
    assert "净流出日" in render_report_html(_report(tmp_path, "-600000000"))
    assert "震荡日" in render_report_html(_report(tmp_path, "0"))
    assert _decimal("1万") == Decimal("1e4")
    assert _decimal("1万亿") == Decimal("1e12")
