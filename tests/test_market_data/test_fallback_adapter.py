"""FallbackAdapter 单测。

重点覆盖 issue #3：
- list_market_quotes() / get_quotes() 全部 adapter 失败时返回 [] 而非 None
- Monitor.snapshot_now() 不再因 None 崩溃
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter

# ---------- helpers ----------


@dataclass
class _MockAdapter:
    """极简 mock adapter，只实现 _try_call 走的几个方法。"""

    name: str
    # 每个方法的返回值；SENTINEL 表示该方法不存在
    list_market_quotes_ret: Any = "SENTINEL"
    get_quotes_ret: Any = "SENTINEL"
    get_quote_ret: Any = "SENTINEL"
    # 控制是否抛异常
    raise_on: set[str] = field(default_factory=set)

    def list_market_quotes(self):
        if "list_market_quotes" in self.raise_on:
            raise RuntimeError(f"{self.name}: boom")
        return self.list_market_quotes_ret if self.list_market_quotes_ret != "SENTINEL" else None

    def get_quotes(self, codes: list[str]):
        if "get_quotes" in self.raise_on:
            raise RuntimeError(f"{self.name}: boom")
        return self.get_quotes_ret if self.get_quotes_ret != "SENTINEL" else None

    def get_quote(self, code: str):
        if "get_quote" in self.raise_on:
            raise RuntimeError(f"{self.name}: boom")
        return self.get_quote_ret if self.get_quote_ret != "SENTINEL" else None


# ---------- list_market_quotes ----------


class TestListMarketQuotes:
    def test_primary_success(self):
        primary = _MockAdapter("primary", list_market_quotes_ret=["q1", "q2"])
        fb = FallbackAdapter([primary, _MockAdapter("backup")])
        assert fb.list_market_quotes() == ["q1", "q2"]

    def test_fallback_when_primary_returns_empty(self):
        """主源返回 [] → 视为失败 → 走 fallback。"""
        primary = _MockAdapter("primary", list_market_quotes_ret=[])
        backup = _MockAdapter("backup", list_market_quotes_ret=["q1"])
        fb = FallbackAdapter([primary, backup])
        assert fb.list_market_quotes() == ["q1"]

    def test_all_fail_returns_empty_list_not_none(self):
        """issue #3 核心：全部失败时返回 [] 而非 None。"""
        primary = _MockAdapter("primary", list_market_quotes_ret=None)
        backup = _MockAdapter("backup", list_market_quotes_ret=None)
        fb = FallbackAdapter([primary, backup])
        result = fb.list_market_quotes()
        assert result is not None
        assert result == []

    def test_all_raise_returns_empty_list_not_none(self):
        """全部抛异常也返回 []。"""
        primary = _MockAdapter("primary", raise_on={"list_market_quotes"})
        backup = _MockAdapter("backup", raise_on={"list_market_quotes"})
        fb = FallbackAdapter([primary, backup])
        result = fb.list_market_quotes()
        assert result is not None
        assert result == []

    def test_stats_all_fail_counter(self):
        primary = _MockAdapter("primary", list_market_quotes_ret=None)
        fb = FallbackAdapter([primary])
        fb.list_market_quotes()
        assert fb.stats()["__total__"]["all_fail"] == 1


# ---------- get_quotes ----------


class TestGetQuotes:
    def test_primary_success(self):
        primary = _MockAdapter("primary", get_quotes_ret=["q1"])
        fb = FallbackAdapter([primary])
        assert fb.get_quotes(["600519"]) == ["q1"]

    def test_all_fail_returns_empty_list_not_none(self):
        """issue #3：get_quotes 同理。"""
        primary = _MockAdapter("primary", get_quotes_ret=None)
        backup = _MockAdapter("backup", get_quotes_ret=None)
        fb = FallbackAdapter([primary, backup])
        result = fb.get_quotes(["600519"])
        assert result is not None
        assert result == []

    def test_all_raise_returns_empty_list_not_none(self):
        primary = _MockAdapter("primary", raise_on={"get_quotes"})
        fb = FallbackAdapter([primary])
        result = fb.get_quotes(["600519"])
        assert result is not None
        assert result == []


# ---------- get_quote (单股，已有 None 处理，回归保护) ----------


class TestGetQuote:
    def test_all_fail_returns_none(self):
        """单股接口全部失败时仍返回 None（这是预期的——调用方已处理）。"""
        primary = _MockAdapter("primary", get_quote_ret=None)
        fb = FallbackAdapter([primary])
        assert fb.get_quote("600519") is None

    def test_primary_success(self):
        primary = _MockAdapter("primary", get_quote_ret="q1")
        fb = FallbackAdapter([primary])
        assert fb.get_quote("600519") == "q1"
