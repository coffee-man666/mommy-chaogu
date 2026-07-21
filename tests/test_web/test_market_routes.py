"""/api/market 路由单测 + _ranking 纯逻辑测试。

覆盖 web/routes/market.py：
- GET /api/market/indexes — 大盘指数（mock fetch_indexes）
- GET /api/market/sectors — 板块排行（mock fetch_sector_ranking）
- GET /api/market/gainers — 涨幅榜（mock adapter.list_market_quotes）
- GET /api/market/losers — 跌幅榜
- _ranking() 纯逻辑：ST 过滤 / 涨跌幅异常过滤 / 代码长度过滤 / 排序 / limit / 异常容错
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.market_data.rankings import IndexQuote
from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType
from mommy_chaogu.web.routes.market import _ranking

# ---------- helpers ----------


def _make_quote(
    code: str = "600519",
    name: str = "贵州茅台",
    change_pct: str = "1.85",
    market: MarketType = MarketType.SH,
) -> Quote:
    price = Decimal("1680.00")
    pct = Decimal(change_pct)
    return Quote(
        code=code,
        name=name,
        market=market,
        quote_type=QuoteType.STOCK,
        price=price,
        open=Decimal("1660"),
        high=Decimal("1690"),
        low=Decimal("1655"),
        prev_close=price - (pct * price / 100).quantize(Decimal("0.01")),
        change=(pct * price / 100).quantize(Decimal("0.01")),
        change_pct=pct,
        volume=12345678,
        turnover=Money(Decimal("2000000000"), "CNY"),
        turnover_rate=Decimal("0.98"),
        volume_ratio=Decimal("1.23"),
        pe_dynamic=Decimal("25.6"),
        total_market_cap=Money(Decimal("2100000000000"), "CNY"),
        circulating_market_cap=Money(Decimal("2100000000000"), "CNY"),
        timestamp=__import__("datetime").datetime(2026, 7, 1, 15, 0, 0),
    )


class _BrokenQuote:
    """getattr 会抛异常的假对象，用于测试 _ranking 的异常容错分支。"""

    name = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))


# ---------- GET /api/market/indexes ----------


class TestGetIndexes:
    def test_returns_indexes(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.market.fetch_indexes",
            lambda: [
                IndexQuote(
                    code="sh000001",
                    name="上证指数",
                    secid="1.000001",
                    price=Decimal("3200.5"),
                    change_pct=Decimal("0.85"),
                    prev_close=Decimal("3173.4"),
                )
            ],
        )
        resp = client.get("/api/market/indexes")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["code"] == "sh000001"
        assert body[0]["name"] == "上证指数"
        # Decimal → str（Pydantic SectorOut/IndexOut 模型）
        assert body[0]["price"] == "3200.5"
        assert body[0]["change_pct"] == "0.85"

    def test_empty_indexes(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("mommy_chaogu.web.routes.market.fetch_indexes", lambda: [])
        resp = client.get("/api/market/indexes")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------- GET /api/market/sectors ----------


class TestGetSectors:
    def test_returns_sectors(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.market.fetch_sector_ranking",
            lambda limit=30: [
                {
                    "code": "BK0475",
                    "name": "半导体",
                    "change_pct": Decimal("3.5"),
                    "price": Decimal("1000"),
                }
            ],
        )
        resp = client.get("/api/market/sectors?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["code"] == "BK0475"
        assert body[0]["name"] == "半导体"
        assert body[0]["change_pct"] == "3.5"
        # Decimal → str
        assert body[0]["price"] == "1000"

    def test_missing_price_defaults_zero(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "mommy_chaogu.web.routes.market.fetch_sector_ranking",
            lambda limit=30: [
                {
                    "code": "BK0475",
                    "name": "半导体",
                    "change_pct": Decimal("3.5"),
                    # 没有 price 字段
                }
            ],
        )
        resp = client.get("/api/market/sectors")
        body = resp.json()
        # price 缺失 → Decimal("0") → str "0"
        assert body[0]["price"] == "0"


# ---------- GET /api/market/gainers + losers ----------


class TestGainersLosers:
    def test_gainers_sorted_desc(
        self,
        client: TestClient,
        mock_adapter: MagicMock,
    ) -> None:
        mock_adapter.list_market_quotes.return_value = [
            _make_quote("600519", "贵州茅台", "1.85"),
            _make_quote("000858", "五粮液", "3.20", market=MarketType.SZ),
        ]
        resp = client.get("/api/market/gainers?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # 涨幅高的排前面
        assert body[0]["code"] == "000858"
        assert body[0]["change_pct"] == "3.2"
        assert body[1]["code"] == "600519"

    def test_losers_sorted_asc(
        self,
        client: TestClient,
        mock_adapter: MagicMock,
    ) -> None:
        mock_adapter.list_market_quotes.return_value = [
            _make_quote("600519", "贵州茅台", "-1.50"),
            _make_quote("000858", "五粮液", "-3.20", market=MarketType.SZ),
        ]
        resp = client.get("/api/market/losers?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        # 跌幅大的排前面（reverse=False 意味着升序，但跌幅更负的在前）
        assert body[0]["code"] == "000858"
        assert body[0]["change_pct"] == "-3.2"

    def test_limit_param(
        self,
        client: TestClient,
        mock_adapter: MagicMock,
    ) -> None:
        mock_adapter.list_market_quotes.return_value = [
            _make_quote(f"60000{i}", f"股{i}", str(float(i))) for i in range(5)
        ]
        resp = client.get("/api/market/gainers?limit=3")
        body = resp.json()
        assert len(body) == 3


# ---------- _ranking 纯逻辑 ----------


class TestRankingFiltering:
    def test_filters_st_stocks(self) -> None:
        quotes = [
            _make_quote("600001", "正常股", "2.0"),
            _make_quote("600002", "ST 某股", "5.0"),
            _make_quote("600003", "某某退", "1.0"),
            _make_quote("600004", "N 新股", "8.0"),
        ]
        result = _ranking(quotes, top="up", limit=10)
        codes = [r["code"] for r in result]
        assert codes == ["600001"]
        assert result[0]["name"] == "正常股"

    def test_filters_abnormal_change_pct(self) -> None:
        """涨跌幅 > 11% 过滤（新上市股）。"""
        quotes = [
            _make_quote("600001", "正常", "5.0"),
            _make_quote("600002", "新股A", "15.0"),  # > 11 过滤
            _make_quote("600003", "新股B", "-20.0"),  # < -11 过滤
        ]
        result = _ranking(quotes, top="up", limit=10)
        assert [r["code"] for r in result] == ["600001"]

    def test_filters_bad_code_length(self) -> None:
        quotes = [
            _make_quote("600001", "正常", "2.0"),
            _make_quote("123", "短码", "2.0"),  # 长度 != 6 过滤
            _make_quote("", "空码", "2.0"),  # 空过滤
        ]
        result = _ranking(quotes, top="up", limit=10)
        assert [r["code"] for r in result] == ["600001"]

    def test_sort_up_vs_down(self) -> None:
        quotes = [
            _make_quote("600001", "A", "2.0"),
            _make_quote("600002", "B", "5.0"),
            _make_quote("600003", "C", "-3.0"),
        ]
        up = _ranking(quotes, top="up", limit=10)
        assert [r["code"] for r in up] == ["600002", "600001", "600003"]

        down = _ranking(quotes, top="down", limit=10)
        assert [r["code"] for r in down] == ["600003", "600001", "600002"]

    def test_limit_truncation(self) -> None:
        quotes = [_make_quote(f"60000{i}", f"股{i}", str(float(i))) for i in range(5)]
        result = _ranking(quotes, top="up", limit=2)
        assert len(result) == 2
        # 取涨幅最高的两条
        assert result[0]["code"] == "600004"
        assert result[1]["code"] == "600003"

    def test_exception_in_quote_skipped(self) -> None:
        """quote 对象抛异常时跳过（不崩溃）。"""
        quotes: list[Any] = [_BrokenQuote(), _make_quote("600001", "正常", "2.0")]
        result = _ranking(quotes, top="up", limit=10)
        assert len(result) == 1
        assert result[0]["code"] == "600001"

    def test_output_fields(self) -> None:
        q = _make_quote("600519", "贵州茅台", "1.85")
        result = _ranking([q], top="up", limit=10)
        item = result[0]
        assert item["code"] == "600519"
        assert item["name"] == "贵州茅台"
        assert item["price"] == "1680.00"
        assert item["change_pct"] == "1.85"
        assert item["volume"] == 12345678
        assert item["market"] == "SH"
        # turnover 字段：q.turnover.amount
        assert item["turnover"] == str(q.turnover.amount)
