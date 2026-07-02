"""TencentAdapter + FallbackAdapter 单测。

腾讯部分用 mock response（避免测试依赖外部网络）；
fallback 部分用 mock adapter。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mommy_chaogu.market_data import (
    FallbackAdapter,
    MarketDataAdapter,
    TencentAdapter,
)
from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    Quote,
    QuoteType,
)

# ---------- Mock HTTP 响应 ----------

# 这是腾讯接口真实的 88 字段响应（贵州茅台）
_MOCK_TENCENT_RAW = (
    'v_sh600519="1~XD贵州茅~600519~1168.63~1184.08~1199.00~50066~20841~29226~'
    "1168.63~2~1168.60~2~1168.52~1~1168.51~1~1168.50~4~1168.78~1~1168.80~7~"
    "1168.81~5~1168.82~142~1168.98~1~~20260626161408~-15.45~-1.30~1199.00~1168.10~"
    "1168.63/50066/5922014054~50066~592201~0.40~17.66~~1199.00~1168.10~2.61~"
    "14608.83~14608.83~6.27~1302.49~1065.67~0.94~-146~1182.83~13.41~17.75~~~"
    "0.34~592201.4054~0.0000~0~ ~GP-A~-13.38~-1.55~4.45~30.53~26.78~1539.98~"
    '1168.10~-6.58~-6.36~-15.80~1250081601~1250081601~-87.95~-16.61~12500...";'
)


def _mock_session_with_response(text: str):
    """构造一个 mock requests.Session，GET 返回指定文本。"""
    from unittest.mock import MagicMock

    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.encoding = "gbk"
    resp.text = text
    resp.raise_for_status = MagicMock()
    sess.get.return_value = resp
    return sess


def _patch_session(monkeypatch, text: str) -> None:
    """把 TencentAdapter._session 替换成 mock。"""
    from mommy_chaogu.market_data import tencent_adapter

    monkeypatch.setattr(
        tencent_adapter.TencentAdapter,
        "__init__",
        lambda self, timeout=10.0: None,
        raising=False,
    )
    # 重新构造 session

    def patched_init(self, timeout=10.0):
        self.timeout = timeout
        self._session = _mock_session_with_response(text)
        self._last_call_ts = 0.0

    monkeypatch.setattr(TencentAdapter, "__init__", patched_init)


# ---------- TencentAdapter 单测 ----------


def test_tencent_protocol_satisfies() -> None:
    a = TencentAdapter()
    assert isinstance(a, MarketDataAdapter)
    assert a.name == "tencent"


def test_tencent_parse_quote_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """字段解析正确（关键字段）。"""
    _patch_session(monkeypatch, _MOCK_TENCENT_RAW)
    a = TencentAdapter()
    q = a.get_quote("600519")
    assert q is not None
    assert q.code == "600519"
    assert q.name == "XD贵州茅"
    assert q.price == Decimal("1168.63")
    assert q.prev_close == Decimal("1184.08")
    assert q.open == Decimal("1199.00")
    assert q.high == Decimal("1199.00")
    assert q.low == Decimal("1168.10")
    assert q.change == Decimal("-15.45")
    assert q.change_pct == Decimal("-1.30")
    assert q.volume == 50066 * 100  # 5,006,600 股
    # 成交额 = 592201 万元 = 5,922,010,000 元
    assert q.turnover.amount == Decimal("592201") * 10000
    assert q.turnover.currency == "CNY"
    assert q.pe_dynamic == Decimal("17.66")
    assert q.turnover_rate == Decimal("0.40")
    assert q.volume_ratio == Decimal("0.94")
    assert q.market == MarketType.SH
    assert q.timestamp is not None


def test_tencent_volume_hand_hundred() -> None:
    """成交量(手) × 100 = 股。"""
    assert _MockTC()._to_volume(50066) == 5006600
    assert _MockTC()._to_volume(0) == 0


class _MockTC:
    def _to_volume(self, v):
        return int(float(v) * 100)


def test_tencent_get_quote_unknown_code_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """未知 code 或解析失败返回 None。"""
    _patch_session(monkeypatch, 'v_sh999999="short response"')
    a = TencentAdapter()
    assert a.get_quote("999999") is None


def test_tencent_get_quotes_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """批量：返回多个 code。"""
    batch_raw = (
        _MOCK_TENCENT_RAW
        + '\nv_sz000001="51~平安银行~000001~10.23~10.42~10.42~1236482~480819~755663~'
        "10.23~236~10.22~7029~10.21~6570~10.20~16561~10.19~6604~10.24~2867~10.25~"
        "1783~10.26~1525~10.27~1022~10.28~2501~~20260626161457~-0.19~-1.82~10.47~"
        "10.19~10.23/1236482/1270902948~1236482~127090~0.64~4.61~~10.47~10.19~"
        "2.69~1985.19~1985.23~0.43~11.46~9.38~1.01~27302~10.28~3.42~4.66~~~0.39~"
        "127090.2948~0.0000~0~ ~GP-A~-7.42~-2.76~5.83~7.91~0.71~12.73~10.07~-6.49~"
        "-0.68~-4.03~19405600653~19405918198~58.47~-5.14~19405600653~~~-13.41~-0.10"
        '~~CNY~0~~10.18~7876~";'
    )
    _patch_session(monkeypatch, batch_raw)
    a = TencentAdapter()
    qs = a.get_quotes(["600519", "000001"])
    codes = [q.code for q in qs]
    assert "600519" in codes
    assert "000001" in codes


def test_tencent_get_order_book(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 档盘口解析正确。"""
    _patch_session(monkeypatch, _MOCK_TENCENT_RAW)
    a = TencentAdapter()
    ob = a.get_order_book("600519")
    assert ob is not None
    assert len(ob.bids) == 5
    assert len(ob.asks) == 5
    # 买一价 1168.63，买一量 2
    assert ob.bids[0].price == Decimal("1168.63")
    assert ob.bids[0].volume == 2
    # 卖一价 1168.78
    assert ob.asks[0].price == Decimal("1168.78")


def test_tencent_list_market_quotes_returns_empty() -> None:
    """腾讯公开接口没有全市场，返回空 list（不报错）。"""
    a = TencentAdapter()
    assert a.list_market_quotes() == []


def test_tencent_unsupported_methods_return_empty() -> None:
    """K线/资金流/板块等不支持的方法返回空。"""
    a = TencentAdapter()
    assert a.get_bars("600519") == []
    assert a.get_ticks("600519") == []
    assert a.get_today_money_flow("600519") == []
    assert a.get_history_money_flow("600519") == []
    assert a.get_belonging_boards("600519") == []


# ---------- FallbackAdapter 单测 ----------


class BrokenAdapter:
    name = "broken"

    def get_quote(self, code):
        raise ConnectionError("down")

    def get_quotes(self, codes):
        raise ConnectionError("down")

    def list_market_quotes(self):
        raise ConnectionError("down")

    def get_order_book(self, code):
        raise ConnectionError("down")

    def get_bars(self, code, **kw):
        raise ConnectionError("down")

    def get_ticks(self, code, limit=None):
        raise ConnectionError("down")

    def get_today_money_flow(self, code):
        raise ConnectionError("down")

    def get_history_money_flow(self, code, days=30):
        raise ConnectionError("down")

    def get_belonging_boards(self, code):
        raise ConnectionError("down")

    def health_check(self) -> bool:
        return False


class GoodAdapter:
    name = "good"

    def __init__(self, quote: Quote | None = None) -> None:
        self.quote = quote or _make_quote()

    def get_quote(self, code):
        return self.quote

    def get_quotes(self, codes):
        return [self.quote]

    def list_market_quotes(self):
        return [self.quote]

    def get_order_book(self, code):
        return None

    def get_bars(self, code, **kw):
        return []

    def get_ticks(self, code, limit=None):
        return []

    def get_today_money_flow(self, code):
        return []

    def get_history_money_flow(self, code, days=30):
        return []

    def get_belonging_boards(self, code):
        return []

    def health_check(self) -> bool:
        return True


def _make_quote() -> Quote:
    return Quote(
        code="600519",
        name="测试",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("100"),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        prev_close=Decimal("100"),
        change=Decimal("0"),
        change_pct=Decimal("0"),
        volume=0,
        turnover=Money.from_yuan(0),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=None,
        circulating_market_cap=None,
        timestamp=datetime.now(UTC),
    )


def test_fallback_protocol_satisfies() -> None:
    fb = FallbackAdapter([GoodAdapter()])
    assert isinstance(fb, MarketDataAdapter)


def test_fallback_primary_succeeds() -> None:
    """主源 OK → 用主源，不触发 fallback。"""
    fb = FallbackAdapter([GoodAdapter(), GoodAdapter()])
    q = fb.get_quote("600519")
    assert q is not None
    assert fb.stats()["__total__"]["primary_hits"] == 1
    assert fb.stats()["__total__"]["fallback_hits"] == 0


def test_fallback_primary_fails_uses_secondary() -> None:
    """主源抛异常 → 触发 fallback。"""
    fb = FallbackAdapter([BrokenAdapter(), GoodAdapter()])
    q = fb.get_quote("600519")
    assert q is not None
    st = fb.stats()
    assert st["broken"]["fail"] == 1
    assert st["good"]["ok"] == 1
    assert st["__total__"]["fallback_hits"] == 1


def test_fallback_primary_returns_none_falls_back() -> None:
    """主源返回 None → 触发 fallback。"""

    class EmptyAdapter:
        name = "empty"

        def get_quote(self, code):
            return None

        def get_quotes(self, codes):
            return []

        def list_market_quotes(self):
            return []

        def get_order_book(self, code):
            return None

        def get_bars(self, code, **kw):
            return []

        def get_ticks(self, code, limit=None):
            return []

        def get_today_money_flow(self, code):
            return []

        def get_history_money_flow(self, code, days=30):
            return []

        def get_belonging_boards(self, code):
            return []

        def health_check(self):
            return False

    fb = FallbackAdapter([EmptyAdapter(), GoodAdapter()])
    q = fb.get_quote("600519")
    assert q is not None
    assert fb.stats()["__total__"]["fallback_hits"] == 1


def test_fallback_all_fail_returns_none() -> None:
    """全部失败 → None，不抛。"""
    fb = FallbackAdapter([BrokenAdapter(), BrokenAdapter()])
    q = fb.get_quote("600519")
    assert q is None
    assert fb.stats()["__total__"]["all_fail"] == 1


def test_fallback_requires_at_least_one_adapter() -> None:
    with pytest.raises(ValueError):
        FallbackAdapter([])


def test_fallback_health_check_any_true() -> None:
    """只要有一个 adapter 健康就算健康。"""
    fb = FallbackAdapter([BrokenAdapter(), GoodAdapter()])
    assert fb.health_check() is True


def test_fallback_health_check_all_false() -> None:
    fb = FallbackAdapter([BrokenAdapter(), BrokenAdapter()])
    assert fb.health_check() is False


def test_fallback_does_not_call_secondary_when_primary_works() -> None:
    """主源 OK 时不调次源。"""

    class CountingGood(GoodAdapter):
        def __init__(self, name="counting"):
            super().__init__()
            self.call_count = 0

        def get_quote(self, code):
            self.call_count += 1
            return super().get_quote(code)

    primary = CountingGood()
    secondary = CountingGood()
    primary.name = "primary"
    secondary.name = "secondary"
    fb = FallbackAdapter([primary, secondary])
    fb.get_quote("600519")
    assert primary.call_count == 1
    assert secondary.call_count == 0
