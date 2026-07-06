"""flows.report 单测 — FlowReport markdown 日报生成。

策略：真实 CacheStore（tmp_path）+ FakeAdapter，传入 market_caps 跳过行情拉取，
用 CustomPool 避免 SemiconStore 依赖，直接灌缓存验证报告结构。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.cache import CacheStore
from mommy_chaogu.flows.pool import CustomPool, PoolSource
from mommy_chaogu.flows.report import FlowReport, _fmt_bp, _fmt_pct, _fmt_yi
from mommy_chaogu.flows.service import FlowService
from mommy_chaogu.market_data.types import Quote

# ---------- Helpers（与 test_service 共享风格） ----------


class FakeAdapter:
    def __init__(self) -> None:
        self._last_fetch_attempt: dict[str, datetime] = {}

    def get_quote(self, code: str) -> Quote | None:
        return None

    def get_today_money_flow(self, code: str) -> list[Any]:
        return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[Any]:
        return []


def _flow_dict(
    code: str = "600519",
    name: str = "茅台",
    main: float = 0.0,
    ts: str = "2026-07-06T10:00:00",
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "timestamp": ts,
        "main_net": {"amount": str(main), "currency": "CNY"},
        "small_net": {"amount": "0", "currency": "CNY"},
        "medium_net": {"amount": "0", "currency": "CNY"},
        "large_net": {"amount": "0", "currency": "CNY"},
        "super_large_net": {"amount": "0", "currency": "CNY"},
    }


@pytest.fixture
def service(tmp_path: Path) -> FlowService:
    store = CacheStore(tmp_path / "test.db")
    return FlowService(FakeAdapter(), store)


@pytest.fixture
def store_of(service: FlowService) -> CacheStore:
    return service.store  # type: ignore[attr-defined]


# ---------- 格式化 helpers ----------


def test_fmt_bp_positive() -> None:
    assert _fmt_bp(Decimal("0.0005")) == "+5.0bp"


def test_fmt_bp_negative() -> None:
    assert _fmt_bp(Decimal("-0.0003")) == "-3.0bp"


def test_fmt_bp_zero() -> None:
    # bp == 0 时 sign 不加 "+"（sign = "+" if bp > 0 else ""）
    assert _fmt_bp(Decimal("0")) == "0.0bp"


def test_fmt_yi_positive() -> None:
    assert _fmt_yi(Decimal("150000000")) == "+1.50亿"


def test_fmt_yi_negative() -> None:
    assert _fmt_yi(Decimal("-50000000")) == "-0.50亿"


def test_fmt_pct_normal() -> None:
    assert _fmt_pct(3, 4) == "75%"


def test_fmt_pct_zero_total() -> None:
    assert _fmt_pct(0, 0) == "0%"


# ---------- FlowReport.generate ----------


def test_generate_basic_structure(
    service: FlowService, store_of: CacheStore, tmp_path: Path
) -> None:
    pool = CustomPool(["600519", "000001"])
    market_caps = {
        "600519": ("茅台", Decimal("100000000000")),
        "000001": ("平安", Decimal("200000000000")),
    }
    store_of.set_today_money_flow("600519", [_flow_dict("600519", "茅台", 50_000_000)])
    store_of.set_today_money_flow("000001", [_flow_dict("000001", "平安", -30_000_000)])

    out = tmp_path / "report.md"
    report = FlowReport(service)
    result = report.generate(
        pool, day=__import__("datetime").date(2026, 7, 6), output=out, market_caps=market_caps
    )
    assert result == out
    content = out.read_text(encoding="utf-8")
    # 标题
    assert "# 资金流收盘日报" in content
    assert "2026-07-06" in content
    assert "custom" in content
    # 覆盖
    assert "2/2" in content
    # 板块汇总
    assert "板块汇总" in content
    # TOP 流入 / 流出
    assert "净流入 TOP 10" in content
    assert "净流出 TOP 10" in content
    # 茅台流入，平安流出
    assert "茅台" in content
    assert "平安" in content


def test_generate_top_inflow_ordering(
    service: FlowService, store_of: CacheStore, tmp_path: Path
) -> None:
    """流入 TOP 按 ratio 降序（ratio = main_net / float_mcap）。"""
    # 600519: 5e7 / 1e11 = 0.0005
    # 000001: 6e7 / 2e11 = 0.0003
    store_of.set_today_money_flow("600519", [_flow_dict("600519", "茅台", 50_000_000)])
    store_of.set_today_money_flow("000001", [_flow_dict("000001", "平安", 60_000_000)])
    pool = CustomPool(["600519", "000001"])
    market_caps = {
        "600519": ("茅台", Decimal("100000000000")),
        "000001": ("平安", Decimal("200000000000")),
    }
    out = tmp_path / "r.md"
    FlowReport(service).generate(pool, output=out, market_caps=market_caps)
    content = out.read_text(encoding="utf-8")
    pos_inflow = content.index("净流入 TOP 10")
    # 茅台 ratio (5bp) > 平安 ratio (3bp) → 茅台在前
    pos_maotai = content.index("茅台")
    assert pos_inflow < pos_maotai


def test_generate_no_data_codes(
    service: FlowService, store_of: CacheStore, tmp_path: Path
) -> None:
    pool = CustomPool(["600519", "000001"])
    # 只有 600519 有市值，000001 无市值 → no_data
    market_caps = {"600519": ("茅台", Decimal("100000000000"))}
    out = tmp_path / "r.md"
    FlowReport(service).generate(pool, output=out, market_caps=market_caps)
    content = out.read_text(encoding="utf-8")
    assert "无数据" in content
    assert "000001" in content


def test_generate_creates_parent_dir(
    service: FlowService, tmp_path: Path
) -> None:
    pool = CustomPool([])
    out = tmp_path / "nested" / "deep" / "report.md"
    FlowReport(service).generate(pool, output=out, market_caps={})
    assert out.exists()


def test_generate_empty_pool(
    service: FlowService, tmp_path: Path
) -> None:
    pool: PoolSource = CustomPool([])
    out = tmp_path / "r.md"
    FlowReport(service).generate(pool, output=out, market_caps={})
    content = out.read_text(encoding="utf-8")
    assert "0/0" in content
    # 空数据时表格区显示「（无数据）」
    assert "无数据" in content


def test_generate_contradiction_section(
    service: FlowService, store_of: CacheStore, tmp_path: Path
) -> None:
    """今日 ratio > 0 但 30d 累计 ratio < 0 → 出现在矛盾股清单。"""
    # 今日流入
    store_of.set_today_money_flow(
        "600519", [_flow_dict("600519", "茅台", 50_000_000, ts="2026-07-06T10:00:00")]
    )
    # 历史 30d 累计流出（负）
    store_of.set_money_flow_history(
        "600519",
        "2026-06-01",
        [_flow_dict("600519", "茅台", -200_000_000, ts="2026-06-01T15:00:00")],
    )
    pool = CustomPool(["600519"])
    market_caps = {"600519": ("茅台", Decimal("100000000000"))}
    out = tmp_path / "r.md"
    FlowReport(service).generate(pool, output=out, market_caps=market_caps)
    content = out.read_text(encoding="utf-8")
    assert "矛盾股" in content
    assert "茅台" in content
