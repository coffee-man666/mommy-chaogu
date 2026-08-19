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


@dataclass
class _Item:
    code: str


@dataclass
class _ByCodeAdapter:
    """按 code 应答的 mock：只返回自己认识的代码（模拟 Massive 只认美股）。"""

    name: str
    by_code: dict[str, _Item]
    seen_codes: list[list[str]] = field(default_factory=list)

    def get_quotes(self, codes: list[str]):
        self.seen_codes.append(list(codes))
        return [self.by_code[c] for c in codes if c in self.by_code]


class TestGetQuotes:
    def test_primary_success(self):
        primary = _MockAdapter("primary", get_quotes_ret=[_Item("600519")])
        fb = FallbackAdapter([primary])
        assert [q.code for q in fb.get_quotes(["600519"])] == ["600519"]

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

    def test_partial_primary_fills_gap_from_next_adapter(self):
        """混合市场批量：主源只返回美股，缺失的 A 股必须落到下一个源补齐。"""
        aapl = _Item("AAPL")
        wuliangye = _Item("000858")
        primary = _ByCodeAdapter("massive", {"AAPL": aapl})
        backup = _ByCodeAdapter("efinance", {"600519": _Item("600519"), "000858": wuliangye})
        fb = FallbackAdapter([primary, backup])
        result = fb.get_quotes(["600519", "AAPL", "000858"])
        assert [q.code for q in result] == ["600519", "AAPL", "000858"]
        # 第二个源只收到缺口，不重复请求已成功的 AAPL
        assert backup.seen_codes == [["600519", "000858"]]

    def test_uncoverable_code_does_not_block_others(self):
        """没人认识的 code 直接缺失，不影响其他 code 的结果。"""
        primary = _ByCodeAdapter("massive", {"AAPL": _Item("AAPL")})
        backup = _ByCodeAdapter("efinance", {})
        fb = FallbackAdapter([primary, backup])
        result = fb.get_quotes(["AAPL", "999999"])
        assert [q.code for q in result] == ["AAPL"]

    def test_all_partial_fail_returns_empty(self):
        """两个源都只返回空 → 语义与全失败一致（[]，all_fail +1）。"""
        primary = _ByCodeAdapter("massive", {})
        backup = _ByCodeAdapter("efinance", {})
        fb = FallbackAdapter([primary, backup])
        result = fb.get_quotes(["600519"])
        assert result == []
        assert fb.stats()["__total__"]["all_fail"] == 1

    def test_adapter_missing_batch_method_is_skipped(self):
        """链上某源未实现批量方法时不得抛 AttributeError，应跳过并继续补齐。"""
        backup = _ByCodeAdapter("efinance", {"600519": _Item("600519"), "AAPL": _Item("AAPL")})

        class _NoBatch:
            name = "no_batch"

        fb = FallbackAdapter([_NoBatch(), backup])  # type: ignore[list-item]
        result = fb.get_quotes(["600519", "AAPL"])
        assert [q.code for q in result] == ["600519", "AAPL"]
        assert fb.stats()["no_batch"]["fail"] == 1

    def test_all_adapters_missing_batch_method_returns_empty(self):
        """所有源都缺批量方法 → []（all_fail +1），与全失败语义一致。"""

        class _NoBatch:
            name = "no_batch"

        fb = FallbackAdapter([_NoBatch()])  # type: ignore[list-item]
        assert fb.get_quotes(["600519"]) == []
        assert fb.stats()["__total__"]["all_fail"] == 1

    def test_full_coverage_primary_counts_primary_hit(self):
        primary = _ByCodeAdapter("massive", {"600519": _Item("600519"), "AAPL": _Item("AAPL")})
        fb = FallbackAdapter([primary])
        fb.get_quotes(["600519", "AAPL"])
        total = fb.stats()["__total__"]
        assert total["primary_hits"] == 1
        assert total["partial_hits"] == 0

    def test_partial_primary_counts_partial_hit_not_primary_hit(self):
        """主源部分覆盖时计 partial_hits 而非 primary_hits，缺口补齐计 fallback_hits。"""
        primary = _ByCodeAdapter("massive", {"AAPL": _Item("AAPL")})
        backup = _ByCodeAdapter("efinance", {"600519": _Item("600519")})
        fb = FallbackAdapter([primary, backup])
        result = fb.get_quotes(["600519", "AAPL"])
        assert [q.code for q in result] == ["600519", "AAPL"]
        total = fb.stats()["__total__"]
        assert total["primary_hits"] == 0
        assert total["partial_hits"] == 1
        assert total["fallback_hits"] == 1


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

    def test_adapter_missing_method_is_skipped(self):
        """单股路径同理：源未实现该方法时跳过，不得抛 AttributeError。"""
        backup = _MockAdapter("backup", get_quote_ret="q2")

        class _NoQuote:
            name = "no_quote"

        fb = FallbackAdapter([_NoQuote(), backup])  # type: ignore[list-item]
        assert fb.get_quote("600519") == "q2"
        assert fb.stats()["no_quote"]["fail"] == 1
