"""把资金流 .md 报告渲染成独立 HTML 网页。

模板 + 数据 + (后续)AI 导语，三件合并出一份当日专属的报告页。
"""
from __future__ import annotations

from mommy_chaogu.report_render.parser import ReportData, parse_markdown_report
from mommy_chaogu.report_render.renderer import (
    render_index,
    render_index_html,
    render_one,
    render_report_html,
)

__all__ = [
    "ReportData",
    "parse_markdown_report",
    "render_index",
    "render_index_html",
    "render_one",
    "render_report_html",
]
