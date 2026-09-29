"""stock_search 单测：双源解析 + 排序 + 兜底逻辑（mock HTTP，不碰网络）。"""

from __future__ import annotations

from typing import Any

import pytest

from mommy_chaogu.market_data import stock_search
from mommy_chaogu.market_data.stock_search import StockSearchHit, search_stocks_by_name

# ---------- 测试辅助：构造 mock 源 ----------

_BYD_EM_HITS = [StockSearchHit(code="002594", name="比亚迪", market="A股")]


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    em: list[StockSearchHit] | None = None,
    sina: list[StockSearchHit] | None = None,
) -> tuple[list[str], list[str]]:
    """替换东财/新浪两个搜索函数；返回各自的调用记录。"""
    em_calls: list[str] = []
    sina_calls: list[str] = []

    def em_side(q: str, limit: int) -> list[StockSearchHit]:
        em_calls.append(q)
        return em or []

    def sina_side(q: str, limit: int) -> list[StockSearchHit]:
        sina_calls.append(q)
        return sina or []

    monkeypatch.setattr(stock_search, "_search_eastmoney", em_side)
    monkeypatch.setattr(stock_search, "_search_sina", sina_side)
    return em_calls, sina_calls


# ---------- 搜索主流程 ----------


class TestSearchStocksByName:
    def test_eastmoney_hit_skips_sina(self, monkeypatch: pytest.MonkeyPatch) -> None:
        em_calls, sina_calls = _patch_sources(monkeypatch, em=_BYD_EM_HITS)
        hits = search_stocks_by_name("比亚迪")
        assert [h.code for h in hits] == ["002594"]
        assert em_calls == ["比亚迪"]
        assert sina_calls == []  # 东财命中不再打新浪

    def test_empty_query_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        em_calls, sina_calls = _patch_sources(monkeypatch)
        assert search_stocks_by_name("  ") == []
        assert em_calls == [] and sina_calls == []

    def test_sina_fallback_on_empty_em(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """拼音场景：东财不识别（返回空），新浪兜底。"""
        sina_hits = [
            StockSearchHit(code="600519", name="贵州茅台", market="A股"),
            StockSearchHit(code="605208", name="永茂泰", market="A股"),
        ]
        _, sina_calls = _patch_sources(monkeypatch, em=[], sina=sina_hits)
        hits = search_stocks_by_name("maotai")
        assert sina_calls == ["maotai"]
        assert hits[0].code == "600519"  # 新浪 API 相关性顺序保留

    def test_sina_fallback_on_em_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(q: str, limit: int) -> list[StockSearchHit]:
            raise RuntimeError("network down")

        monkeypatch.setattr(stock_search, "_search_eastmoney", boom)
        _, sina_calls = _patch_sources(monkeypatch, sina=_BYD_EM_HITS)
        assert search_stocks_by_name("比亚迪") == _BYD_EM_HITS
        assert sina_calls == ["比亚迪"]

    def test_both_fail_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_sources(monkeypatch, em=[], sina=[])
        assert search_stocks_by_name("不存在的") == []

    def test_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        em = [
            StockSearchHit(code="002594", name="比亚迪", market="A股"),
            StockSearchHit(code="600519", name="贵州茅台", market="A股"),
            StockSearchHit(code="000858", name="五粮液", market="A股"),
        ]
        _patch_sources(monkeypatch, em=em)
        assert len(search_stocks_by_name("酒", limit=2)) == 2


# ---------- 排序 ----------


class TestRank:
    def test_exact_beats_prefix_and_contains(self) -> None:
        hits = [
            StockSearchHit(code="300750", name="宁德时代供应商", market="A股"),
            StockSearchHit(code="002132", name="宁德时代概念", market="A股"),
            StockSearchHit(code="300124", name="宁德时代", market="A股"),
        ]
        assert stock_search._rank(hits, "宁德时代")[0].code == "300124"

    def test_prefix_beats_contains(self) -> None:
        hits = [
            StockSearchHit(code="300750", name="宁德时代供应商", market="A股"),
            StockSearchHit(code="300124", name="宁德时代", market="A股"),
        ]
        assert stock_search._rank(hits, "宁德时代")[0].code == "300124"

    def test_exact_us_beats_prefix_a_share(self) -> None:
        hits = [
            StockSearchHit(code="601988", name="苹果供应链", market="A股"),
            StockSearchHit(code="AAPL", name="苹果", market="US"),
        ]
        assert stock_search._rank(hits, "苹果")[0].code == "AAPL"

    def test_same_rank_a_share_first(self) -> None:
        hits = [
            StockSearchHit(code="AAPL", name="苹果公司", market="US"),
            StockSearchHit(code="601988", name="苹果供应链", market="A股"),
        ]
        assert stock_search._rank(hits, "苹果")[0].code == "601988"


# ---------- 源解析 ----------


def _em_item(code: str, name: str, mkt: str) -> dict[str, Any]:
    return {"Code": code, "Name": name, "MktNum": mkt}


class TestEastmoneyParsing:
    def test_filters_unsupported_markets(self) -> None:
        # 港股(116)/期货(130)/板块(90)/粉单(153) 全部过滤
        for item in [
            _em_item("00700", "腾讯控股", "116"),
            _em_item("BYDH7", "比亚迪股份期货", "130"),
            _em_item("BK0644", "比亚迪概念", "90"),
            _em_item("BYDDY", "比亚迪(ADR)", "153"),
        ]:
            assert stock_search._em_to_hit(item) is None

    def test_a_share_and_us(self) -> None:
        assert stock_search._em_to_hit(_em_item("002594", "比亚迪", "0")) == (
            StockSearchHit("002594", "比亚迪", "A股")
        )
        assert stock_search._em_to_hit(_em_item("AAPL", "苹果", "105")) == (
            StockSearchHit("AAPL", "苹果", "US")
        )

    def test_bond_like_codes_filtered(self) -> None:
        # AAPL22 这类债券代码（字母+数字）不是合法美股代码
        assert stock_search._em_to_hit(_em_item("AAPL22", "Apple Notes", "105")) is None

    def test_bad_a_share_code(self) -> None:
        assert stock_search._em_to_hit(_em_item("594", "比亚迪", "0")) is None

    def test_missing_fields(self) -> None:
        assert stock_search._em_to_hit({"Code": "", "Name": "x", "MktNum": "0"}) is None
        assert stock_search._em_to_hit({"Code": "600519", "Name": "", "MktNum": "0"}) is None


class TestSinaParsing:
    # 字段顺序: [名称, type, 代码, 完整代码, ...]
    def test_a_share(self) -> None:
        fields = ["贵州茅台", "11", "600519", "sh600519", "贵州茅台", "", "贵州茅台"]
        assert stock_search._sina_to_hit(fields) == StockSearchHit("600519", "贵州茅台", "A股")

    def test_us_uppercased(self) -> None:
        fields = ["苹果", "41", "aapl", "aapl", "苹果", "", "苹果"]
        assert stock_search._sina_to_hit(fields) == StockSearchHit("AAPL", "苹果", "US")

    def test_hk_and_short_fields_filtered(self) -> None:
        assert stock_search._sina_to_hit(["比亚迪股份", "31", "01211", "01211"]) is None
        assert stock_search._sina_to_hit(["比亚迪", "11"]) is None
