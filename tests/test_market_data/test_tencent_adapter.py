"""TencentAdapter + FallbackAdapter 单测。

腾讯部分用 mock response（避免测试依赖外部网络）；
fallback 部分用 mock adapter。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from mommy_chaogu.market_data import (
    FallbackAdapter,
    MarketDataAdapter,
    TencentAdapter,
)
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    BarInterval,
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


# ---------- 分钟 K 线（ifzq.gtimg.cn mkline 备源，阶段六）----------


def _mkline_payload(rows: list, symbol: str = "sh600519", name: str = "贵州茅台") -> dict:
    """构造与真实 mkline 响应同形的 payload（2026-09-30 实抓样例裁剪）。"""
    return {
        "code": 0,
        "msg": "",
        "data": {
            symbol: {
                "qt": {symbol: ["1", name, "600519"]},
                "market": [],
                "m5": rows,
            }
        },
    }


# 真实响应每行形如 [时间标签(周期末), 开, 收, 高, 低, 量(手), {}, 额外]
_MKLINE_ROWS = [
    ["202609300935", "100.00", "101.00", "101.50", "99.50", "120.00", {}, "0.50"],
    ["202609300940", "101.00", "102.00", "102.50", "100.50", "80.00", {}, "0.44"],
    ["202609300945", "101.50", "101.20", "101.80", "101.00", "60.00", {}, "0.33"],
    ["202609301500", "102.00", "103.00", "103.50", "101.50", "40.00", {}, "0.22"],
]


def _mkline_adapter(payloads: list):
    """构造 session 被 mock 的 TencentAdapter（.get 依次返回 payloads）。"""
    from unittest.mock import MagicMock

    a = TencentAdapter()
    sess = MagicMock()
    responses = []
    for p in payloads:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = lambda payload=p: payload
        responses.append(resp)
    if len(responses) == 1:
        sess.get.return_value = responses[0]  # 单响应可重复服务多次调用
    else:
        sess.get.side_effect = responses
    a._session = sess
    return a, sess


def test_tencent_get_bars_m5_period_start_labels() -> None:
    """时间标签从周期末转周期初（与 efinance 统一）：0935→09:30、1500→14:55（北京）。"""
    a, _ = _mkline_adapter([_mkline_payload(_MKLINE_ROWS)])
    bars = a.get_bars("600519", interval=BarInterval.M5)
    assert len(bars) == 4
    first, last = bars[0], bars[-1]
    assert first.timestamp == datetime(2026, 9, 30, 1, 30, tzinfo=UTC)  # 09:30 北京
    assert last.timestamp == datetime(2026, 9, 30, 6, 55, tzinfo=UTC)  # 14:55 北京
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


def test_tencent_get_bars_m5_field_mapping() -> None:
    """字段映射 [时间,开,收,高,低,量(手)]；量×100→股；不复权；无成交额。"""
    a, _ = _mkline_adapter([_mkline_payload(_MKLINE_ROWS)])
    bars = a.get_bars("600519", interval=BarInterval.M5)
    b0 = bars[0]
    assert b0.code == "600519"
    assert b0.name == "贵州茅台"
    assert b0.open == Decimal("100.00")
    assert b0.close == Decimal("101.00")
    assert b0.high == Decimal("101.50")
    assert b0.low == Decimal("99.50")
    assert b0.volume == 12000  # 120.00 手 × 100
    assert b0.turnover.amount == Decimal("0")  # mkline 无每根成交额
    assert b0.adjustment == AdjustmentType.NONE  # 数据为不复权，如实标注
    assert b0.interval == BarInterval.M5


def test_tencent_get_bars_daily_and_none_still_empty() -> None:
    """日/周/月线与未指定周期仍返回 []（东财主源承担）。"""
    a, _ = _mkline_adapter([_mkline_payload(_MKLINE_ROWS)])
    assert a.get_bars("600519") == []
    assert a.get_bars("600519", interval=BarInterval.D1) == []
    assert a.get_bars("600519", interval=BarInterval.W1) == []


def test_tencent_get_bars_start_end_filter_and_limit() -> None:
    """start/end 按北京日期闭区间过滤；limit 截尾。"""
    a, _ = _mkline_adapter([_mkline_payload(_MKLINE_ROWS)])
    bars = a.get_bars(
        "600519", interval=BarInterval.M5, start=date(2026, 9, 30), end=date(2026, 9, 30)
    )
    assert len(bars) == 4
    assert a.get_bars("600519", interval=BarInterval.M5, end=date(2026, 9, 29)) == []
    limited = a.get_bars("600519", interval=BarInterval.M5, limit=2)
    assert len(limited) == 2
    assert limited[-1].close == Decimal("103.00")


def test_tencent_get_bars_pages_back_via_anchor() -> None:
    """start 早于单页覆盖 → 以页内最早标签为锚（排他上界）向前翻页。"""
    page1 = _mkline_payload(
        [
            ["202609150935", "99.00", "99.50", "99.80", "98.80", "30.00", {}, "0.1"],
            ["202609301500", "102.00", "103.00", "103.50", "101.50", "40.00", {}, "0.2"],
        ]
    )
    page2 = _mkline_payload(
        [["202609100935", "98.00", "98.50", "98.80", "97.80", "20.00", {}, "0.1"]]
    )
    a, sess = _mkline_adapter([page1, page2])

    bars = a.get_bars("600519", interval=BarInterval.M5, start=date(2026, 9, 10))
    assert len(bars) == 3
    assert bars[0].timestamp == datetime(2026, 9, 10, 1, 30, tzinfo=UTC)
    urls = [c.args[0] for c in sess.get.call_args_list]
    assert urls[0] == "https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sh600519,m5,,800"
    # 第二页锚点 = 第一页最早标签（排他上界：返回其之前的 K 线）
    assert urls[1] == (
        "https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sh600519,m5,202609150935,800"
    )


def test_tencent_get_bars_paging_bounded() -> None:
    """翻页有上限（防失控）：始终翻不到 start 时最多 _MKLINE_MAX_PAGES 页。"""
    from mommy_chaogu.market_data import tencent_adapter as ta

    payloads = [
        _mkline_payload(
            [[f"2026{m:02d}150935", "99.00", "99.50", "99.80", "98.80", "30.00", {}, "0.1"]]
        )
        for m in range(1, 10)
    ]
    a, sess = _mkline_adapter(payloads)
    a.get_bars("600519", interval=BarInterval.M5, start=date(2020, 1, 1))
    assert len(sess.get.call_args_list) == ta._MKLINE_MAX_PAGES


def test_tencent_get_bars_fetch_error_returns_empty() -> None:
    """网络/解析失败 → []，不抛。"""
    from unittest.mock import MagicMock

    a = TencentAdapter()
    sess = MagicMock()
    sess.get.side_effect = ConnectionError("boom")
    a._session = sess
    assert a.get_bars("600519", interval=BarInterval.M5) == []


def test_tencent_get_bars_bad_payload_returns_empty() -> None:
    """code != 0 / 结构异常 → []。"""
    a, _ = _mkline_adapter([{"code": -1, "msg": "fail", "data": {}}])
    assert a.get_bars("600519", interval=BarInterval.M5) == []


def test_tencent_get_bars_prefixed_index_symbol() -> None:
    """已带市场前缀的代码（如指数 sh000001）原样透传给 mkline。"""
    payload = _mkline_payload(
        [["202609301500", "3200.00", "3210.00", "3215.00", "3195.00", "900.00", {}, "0.5"]],
        symbol="sh000001",
        name="上证指数",
    )
    a, sess = _mkline_adapter([payload])
    bars = a.get_bars("sh000001", interval=BarInterval.M5)
    assert len(bars) == 1
    assert bars[0].name == "上证指数"
    assert "param=sh000001,m5" in sess.get.call_args_list[0].args[0]


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
