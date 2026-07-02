"""资金流 .md 报告 → dataclass。

专为 `flows/report.py` 输出的固定结构做解析，不做通用 markdown parser。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SectorRow:
    """板块汇总行。"""

    name: str  # 上游 / 中游 / 下游 / 末端
    stock_count: int
    today_main_net: Decimal  # 元
    float_market_cap: Decimal  # 元
    ratio_bp: Decimal  # bp


@dataclass(frozen=True, slots=True)
class StockRow:
    """个股行（TOP 流入 / 流出 / 矛盾股共用）。"""

    rank: int | None
    code: str
    name: str
    subcategory: str = ""
    main_net: Decimal | None = None
    float_market_cap: Decimal | None = None
    ratio_bp: Decimal | None = None
    extra: dict[str, Decimal | str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportData:
    """一份完整的资金流报告数据。"""

    day: date
    pool_name: str
    pool_size: int
    covered: int
    covered_ratio: float
    today_total: Decimal  # 元
    days_30_total: Decimal  # 元
    sectors: list[SectorRow]
    top_inflows: list[StockRow]
    top_outflows: list[StockRow]
    contradictions: list[StockRow]
    source_path: Path


# ───────────────────────────── helpers ─────────────────────────────


def _decimal(s: str) -> Decimal:
    """把「+5.19亿 / -29.73亿 / **+14.3bp** / 32856.52亿」之类的字符串规范化成元/bp。

    自动剥离 markdown 强调符 `**...**`，正负号直接接受。
    """

    s = s.strip().replace(",", "")
    # 去掉 markdown 加粗 `**...**`
    while s.startswith("**") or s.startswith("*"):
        if s.startswith("**") and s.endswith("**") and len(s) >= 4:
            s = s[2:-2]
        elif s.startswith("*"):
            s = s[1:]
        else:
            break
    # 处理后缀单位
    mult = Decimal(1)
    if s.endswith("亿"):
        mult = Decimal("1e8")
        s = s[:-1]
    elif s.endswith("万"):
        mult = Decimal("1e4")
        s = s[:-1]
    elif s.endswith("万亿"):
        mult = Decimal("1e12")
        s = s[:-2]
    elif s.endswith("bp"):
        s = s[:-2]
        mult = Decimal("1")
    val = Decimal(s)
    return val * mult


def _parse_int(s: str) -> int:
    return int(s.replace(",", "").strip())


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


# ───────────────────────────── public API ───────────────────────────


def parse_markdown_report(path: str | Path) -> ReportData:
    """解析 `flows/report.py` 产出的 markdown 报告。"""

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 标题 → 日期 + 池子名
    title_line = lines[0]
    m = re.match(r"# 资金流收盘日报 · (\d{4}-\d{2}-\d{2}) · (.+)", title_line)
    assert m, f"无法解析报告标题: {title_line!r}"
    day = date.fromisoformat(m.group(1))
    pool_name = m.group(2).strip()

    # 池子行
    pool_desc_line = next(line for line in lines if line.startswith("**池子**"))
    pool_size_m = re.search(r"(\d+)\s*只", pool_desc_line)
    pool_size = int(pool_size_m.group(1)) if pool_size_m else 0

    # 覆盖行
    cover_line = next(line for line in lines if line.startswith("**覆盖**"))
    cov_m = re.search(r"(\d+)/(\d+)\s*只", cover_line)
    if cov_m:
        covered = int(cov_m.group(1))
        total = int(cov_m.group(2))
        covered_ratio = covered / total if total else 0.0
    else:
        covered, total, covered_ratio = 0, pool_size, 0.0

    # 当日 / 30d 合计
    today_line = next(line for line in lines if line.startswith("**当日主力净合计**"))
    d30_line = next(line for line in lines if line.startswith("**30d 累计主力净合计**"))
    today_total = _decimal(today_line.split("：", 1)[1])
    d30_total = _decimal(d30_line.split("：", 1)[1])

    # 分段
    def section(starts: str) -> int:
        for i, line in enumerate(lines):
            if line.startswith(starts):
                return i
        return -1

    sec_sector = section("## 📊")
    sec_in = section("## 🟢")
    sec_out = section("## 🔴")
    sec_contra = section("## ⚠️")

    def slice_section(start: int, end: int) -> list[str]:
        if start < 0 or end < 0:
            return []
        if end < start:
            return []
        return lines[start + 1 : end]

    def parse_table(rows: list[str], *, has_rank: bool) -> list[StockRow]:
        """解析 TOP 流入/流出（has_rank=True）或矛盾股（has_rank=False）表格。"""
        body = [r for r in rows if r.startswith("|") and not re.match(r"\|\s*-+", r)]
        out: list[StockRow] = []
        for r in body[1:]:  # 跳过表头
            cols = _split_row(r)
            if has_rank and len(cols) >= 7:
                try:
                    rank = int(cols[0])
                except ValueError:
                    rank = None
                code = cols[1]
                name = cols[2]
                sub = cols[3]
                rest = cols[4:]
            elif not has_rank and len(cols) >= 5:
                rank = None
                code = cols[0]
                name = cols[1]
                sub = ""
                rest = cols[2:]
            else:
                continue
            main_net: Decimal | None = None
            mcap: Decimal | None = None
            ratio: Decimal | None = None
            extra: dict[str, Decimal | str] = {}
            try:
                if has_rank:
                    main_net = _decimal(rest[0])
                    mcap = _decimal(rest[1])
                    ratio = _decimal(rest[2])
                else:
                    extra["today_bp"] = _decimal(rest[0])
                    extra["days_30_bp"] = _decimal(rest[1])
                    extra["today_net"] = _decimal(rest[2])
                    if len(rest) >= 4:
                        extra["days_30_net"] = _decimal(rest[3])
            except Exception:
                pass
            out.append(
                StockRow(
                    rank=rank,
                    code=code,
                    name=name,
                    subcategory=sub,
                    main_net=main_net,
                    float_market_cap=mcap,
                    ratio_bp=ratio,
                    extra=extra,
                )
            )
        return out

    # 板块汇总
    sector_raw = slice_section(sec_sector, sec_in if sec_in > 0 else sec_out)
    sector_lines = [r for r in sector_raw if r.startswith("|") and not re.match(r"\|\s*-+", r)][1:]
    sectors: list[SectorRow] = []
    for r in sector_lines:
        cols = _split_row(r)
        if len(cols) < 5 or cols[0] == "板块":
            continue
        try:
            sectors.append(
                SectorRow(
                    name=cols[0],
                    stock_count=_parse_int(cols[1]),
                    today_main_net=_decimal(cols[2]),
                    float_market_cap=_decimal(cols[3]),
                    ratio_bp=_decimal(cols[4]),
                )
            )
        except Exception:
            continue

    # TOP 流入/流出
    in_raw = slice_section(sec_in, sec_out if sec_out > 0 else sec_contra)
    out_raw = slice_section(sec_out, sec_contra if sec_contra > 0 else len(lines))
    top_inflows = parse_table(in_raw, has_rank=True)
    top_outflows = parse_table(out_raw, has_rank=True)

    # 矛盾股
    contradictions: list[StockRow] = []
    if sec_contra >= 0:
        end = len(lines)
        for i in range(sec_contra + 1, len(lines)):
            if lines[i].startswith("*生成时间") or lines[i].startswith("---"):
                end = i
                break
        contra_raw = lines[sec_contra + 1 : end]
        contradictions = parse_table(contra_raw, has_rank=False)

    return ReportData(
        day=day,
        pool_name=pool_name,
        pool_size=pool_size,
        covered=covered,
        covered_ratio=covered_ratio,
        today_total=today_total,
        days_30_total=d30_total,
        sectors=sectors,
        top_inflows=top_inflows,
        top_outflows=top_outflows,
        contradictions=contradictions,
        source_path=p,
    )
