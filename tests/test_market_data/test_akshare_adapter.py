"""AkShareAdapter 单元测试（不依赖网络）。

通过 monkeypatch ``akshare`` 模块的函数返回固定 DataFrame，
覆盖：spot → Quote 映射、批量、K 线（日/分钟）、健康检查、降级（无 akshare）、异常容错。
"""

from __future__ import annotations

import sys
import types
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from mommy_chaogu.market_data import (
    AkShareAdapter,
    MarketDataAdapter,
    build_default_adapter,
)
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    BarInterval,
    MarketType,
    QuoteType,
)

# ---------- 测试用 fixture ----------


@pytest.fixture
def fake_akshare(monkeypatch: pytest.MonkeyPatch):
    """注入一个假的 akshare 模块，提供 spot/hist/min_em/fund_flow/individual_info
    等函数，各自返回值由测试通过 monkeypatch 设置。"""
    mod = types.ModuleType("akshare")
    mod.stock_zh_a_spot_em = MagicMock(return_value=pd.DataFrame())  # type: ignore[attr-defined]
    mod.stock_zh_a_hist = MagicMock(return_value=pd.DataFrame())  # type: ignore[attr-defined]
    mod.stock_zh_a_hist_min_em = MagicMock(return_value=pd.DataFrame())  # type: ignore[attr-defined]
    mod.stock_individual_fund_flow = MagicMock(return_value=pd.DataFrame())  # type: ignore[attr-defined]
    mod.stock_individual_info_em = MagicMock(return_value=pd.DataFrame())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


def _spot_df_two_rows() -> pd.DataFrame:
    """模拟 stock_zh_a_spot_em 的两行返回（贵州茅台 + 平安银行）。"""
    return pd.DataFrame(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "最新价": 1685.50,
                "涨跌幅": 1.23,
                "涨跌额": 20.45,
                "成交量": 123456,
                "成交额": 2080000000.0,
                "振幅": 2.34,
                "最高": 1699.00,
                "最低": 1668.00,
                "今开": 1675.00,
                "昨收": 1665.05,
                "量比": 0.88,
                "换手率": 0.45,
                "市盈率-动态": 25.6,
                "市净率": 8.9,
                "总市值": 2116000000000.0,
                "流通市值": 2116000000000.0,
            },
            {
                "代码": "000001",
                "名称": "平安银行",
                "最新价": 11.20,
                "涨跌幅": -0.89,
                "涨跌额": -0.10,
                "成交量": 98765432,
                "成交额": 1105000000.0,
                "振幅": 1.56,
                "最高": 11.35,
                "最低": 11.10,
                "今开": 11.30,
                "昨收": 11.30,
                "量比": 1.05,
                "换手率": 0.51,
                "市盈率-动态": 4.32,
                "市净率": 0.51,
                "总市值": 217800000000.0,
                "流通市值": 217800000000.0,
            },
        ]
    )


def _daily_hist_df() -> pd.DataFrame:
    """模拟 stock_zh_a_hist 日线返回（2 天）。"""
    return pd.DataFrame(
        [
            {
                "日期": "2024-01-02",
                "开盘": 100.0,
                "收盘": 102.0,
                "最高": 105.0,
                "最低": 99.0,
                "成交量": 1000,
                "成交额": 100000.0,
                "振幅": 6.0,
                "涨跌幅": 2.0,
                "涨跌额": 2.0,
                "换手率": 0.5,
            },
            {
                "日期": "2024-01-03",
                "开盘": 102.0,
                "收盘": 100.0,
                "最高": 103.0,
                "最低": 97.0,
                "成交量": 1100,
                "成交额": 105000.0,
                "振幅": 5.88,
                "涨跌幅": -1.96,
                "涨跌额": -2.0,
                "换手率": 0.55,
            },
        ]
    )


def _min_hist_df() -> pd.DataFrame:
    """模拟 stock_zh_a_hist_min_em 分钟线返回（2 根）。"""
    return pd.DataFrame(
        [
            {
                "时间": "2024-01-03 09:31:00",
                "开盘": 102.0,
                "收盘": 102.5,
                "最高": 103.0,
                "最低": 101.8,
                "成交量": 500,
                "成交额": 50000.0,
                "振幅": 0.0,
                "涨跌幅": 0.5,
                "涨跌额": 0.5,
            },
            {
                "时间": "2024-01-03 09:32:00",
                "开盘": 102.5,
                "收盘": 103.0,
                "最高": 103.2,
                "最低": 102.3,
                "成交量": 600,
                "成交额": 62000.0,
                "振幅": 0.0,
                "涨跌幅": 0.49,
                "涨跌额": 0.5,
            },
        ]
    )


def _fund_flow_df() -> pd.DataFrame:
    """模拟 stock_individual_fund_flow 返回（2 天，升序：最早在前，与真实 akshare 一致）。

    字段名严格按 akshare 源码 stock_fund_em.py:52-68；
    日期列是 date 对象（源码第 86 行 .dt.date）。日期相对今天，保证 days 过滤可测。
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    today = _date.today()
    d_recent = today - _td(days=1)
    d_older = today - _td(days=10)
    return pd.DataFrame(
        [
            {
                "日期": d_older,
                "收盘价": 102.0,
                "涨跌幅": 2.0,
                "主力净流入-净额": 3000000.0,
                "主力净流入-净占比": 7.5,
                "超大单净流入-净额": 2000000.0,
                "超大单净流入-净占比": 5.0,
                "大单净流入-净额": 1000000.0,
                "大单净流入-净占比": 2.5,
                "中单净流入-净额": -800000.0,
                "中单净流入-净占比": -2.0,
                "小单净流入-净额": -2200000.0,
                "小单净流入-净占比": -5.5,
            },
            {
                "日期": d_recent,
                "收盘价": 100.0,
                "涨跌幅": -1.96,
                "主力净流入-净额": -2000000.0,
                "主力净流入-净占比": -5.2,
                "超大单净流入-净额": -1000000.0,
                "超大单净流入-净占比": -2.6,
                "大单净流入-净额": -1000000.0,
                "大单净流入-净占比": -2.6,
                "中单净流入-净额": 500000.0,
                "中单净流入-净占比": 1.3,
                "小单净流入-净额": 1500000.0,
                "小单净流入-净占比": 3.9,
            },
        ]
    )


# ---------- Protocol 满足性 ----------


def test_akshare_satisfies_protocol() -> None:
    a = AkShareAdapter()
    assert isinstance(a, MarketDataAdapter)
    assert a.name == "akshare"


# ---------- spot → Quote ----------


def test_get_quote_parses_spot(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = _spot_df_two_rows()
    a = AkShareAdapter()
    q = a.get_quote("600519")
    assert q is not None
    assert q.code == "600519"
    assert q.name == "贵州茅台"
    assert q.price == Decimal("1685.50")
    assert q.open == Decimal("1675.00")
    assert q.high == Decimal("1699.00")
    assert q.low == Decimal("1668.00")
    assert q.prev_close == Decimal("1665.05")
    assert q.change == Decimal("20.45")
    assert q.change_pct == Decimal("1.23")
    assert q.volume == 123456
    assert q.turnover.amount == Decimal("2080000000.0")
    assert q.turnover.currency == "CNY"
    assert q.turnover_rate == Decimal("0.45")
    assert q.volume_ratio == Decimal("0.88")
    assert q.pe_dynamic == Decimal("25.6")
    assert q.total_market_cap is not None
    assert q.total_market_cap.amount == Decimal("2116000000000.0")
    assert q.market == MarketType.SH
    assert q.quote_type == QuoteType.STOCK
    assert q.timestamp is not None


def test_get_quote_unknown_code_returns_none(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = _spot_df_two_rows()
    a = AkShareAdapter()
    assert a.get_quote("999999") is None


def test_get_quote_spot_empty_returns_none(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.get_quote("600519") is None


def test_get_quote_spot_exception_returns_none(fake_akshare) -> None:
    """akshare API 抛错时静默返回 None（不传染 fallback 链）。"""
    fake_akshare.stock_zh_a_spot_em.side_effect = RuntimeError("network down")
    a = AkShareAdapter()
    assert a.get_quote("600519") is None


def test_get_quote_row_missing_code_returns_none(fake_akshare) -> None:
    """行里没有 '代码' 字段时返回 None。"""
    fake_akshare.stock_zh_a_spot_em.return_value = pd.DataFrame([{"名称": "X"}])
    a = AkShareAdapter()
    assert a.get_quote("600519") is None


# ---------- 批量 get_quotes ----------


def test_get_quotes_filters_by_codes(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = _spot_df_two_rows()
    a = AkShareAdapter()
    qs = a.get_quotes(["600519", "000001"])
    codes = {q.code for q in qs}
    assert codes == {"600519", "000001"}


def test_get_quotes_unknown_codes_return_empty(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = _spot_df_two_rows()
    a = AkShareAdapter()
    assert a.get_quotes(["999999", "888888"]) == []


def test_get_quotes_empty_input_returns_empty(fake_akshare) -> None:
    a = AkShareAdapter()
    assert a.get_quotes([]) == []


def test_get_quotes_spot_empty_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.get_quotes(["600519"]) == []


# ---------- list_market_quotes ----------


def test_list_market_quotes_returns_all(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = _spot_df_two_rows()
    a = AkShareAdapter()
    quotes = a.list_market_quotes()
    assert len(quotes) == 2
    assert {q.code for q in quotes} == {"600519", "000001"}


def test_list_market_quotes_empty_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.list_market_quotes() == []


def test_list_market_quotes_exception_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_zh_a_spot_em.side_effect = Exception("API down")
    a = AkShareAdapter()
    assert a.list_market_quotes() == []


# ---------- K 线 ----------


def test_get_daily_bars_parses_hist(fake_akshare) -> None:
    fake_akshare.stock_zh_a_hist.return_value = _daily_hist_df()
    a = AkShareAdapter()
    bars = a.get_bars("600519", BarInterval.D1, AdjustmentType.FORWARD)
    assert len(bars) == 2
    b0 = bars[0]
    assert b0.code == "600519"
    assert b0.interval == BarInterval.D1
    assert b0.adjustment == AdjustmentType.FORWARD
    assert b0.open == Decimal("100.0")
    assert b0.close == Decimal("102.0")
    assert b0.high == Decimal("105.0")
    assert b0.low == Decimal("99.0")
    assert b0.volume == 1000
    assert b0.turnover.amount == Decimal("100000.0")
    assert b0.change_pct == Decimal("2.0")
    assert b0.turnover_rate == Decimal("0.5")
    # 时间按升序
    assert bars[0].timestamp < bars[1].timestamp


def test_get_bars_passes_adjustment_param(fake_akshare) -> None:
    """qfq / hfq / "" 正确传给 akshare。"""
    fake_akshare.stock_zh_a_hist.return_value = pd.DataFrame()
    a = AkShareAdapter()

    a.get_bars("600519", BarInterval.D1, AdjustmentType.FORWARD)
    assert fake_akshare.stock_zh_a_hist.call_args.kwargs["adjust"] == "qfq"

    a.get_bars("600519", BarInterval.D1, AdjustmentType.BACKWARD)
    assert fake_akshare.stock_zh_a_hist.call_args.kwargs["adjust"] == "hfq"

    a.get_bars("600519", BarInterval.D1, AdjustmentType.NONE)
    assert fake_akshare.stock_zh_a_hist.call_args.kwargs["adjust"] == ""


def test_get_bars_passes_daily_period(fake_akshare) -> None:
    fake_akshare.stock_zh_a_hist.return_value = pd.DataFrame()
    a = AkShareAdapter()
    a.get_bars("600519", BarInterval.W1)
    assert fake_akshare.stock_zh_a_hist.call_args.kwargs["period"] == "weekly"
    a.get_bars("600519", BarInterval.M)
    assert fake_akshare.stock_zh_a_hist.call_args.kwargs["period"] == "monthly"


def test_get_min_bars_uses_min_em_endpoint(fake_akshare) -> None:
    """分钟线走 stock_zh_a_hist_min_em，不走 stock_zh_a_hist。"""
    fake_akshare.stock_zh_a_hist_min_em.return_value = _min_hist_df()
    a = AkShareAdapter()
    bars = a.get_bars("600519", BarInterval.M5, AdjustmentType.FORWARD)
    assert len(bars) == 2
    assert bars[0].interval == BarInterval.M5
    # 分钟接口被调用，日接口不被调用
    assert fake_akshare.stock_zh_a_hist_min_em.called
    assert not fake_akshare.stock_zh_a_hist.called
    # period 传字符串 "5"
    assert fake_akshare.stock_zh_a_hist_min_em.call_args.kwargs["period"] == "5"


def test_get_bars_exception_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_zh_a_hist.side_effect = RuntimeError("API timeout")
    a = AkShareAdapter()
    assert a.get_bars("600519", BarInterval.D1) == []


def test_get_bars_empty_df_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_zh_a_hist.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.get_bars("600519", BarInterval.D1) == []


def test_get_bars_respects_limit(fake_akshare) -> None:
    """limit 截断最后 N 根。"""
    fake_akshare.stock_zh_a_hist.return_value = _daily_hist_df()
    a = AkShareAdapter()
    bars = a.get_bars("600519", BarInterval.D1, limit=1)
    assert len(bars) == 1
    # 取最后一根
    assert bars[0].close == Decimal("100.0")


def test_get_bars_respects_date_range(fake_akshare) -> None:
    """start/end 过滤生效。"""
    fake_akshare.stock_zh_a_hist.return_value = _daily_hist_df()
    a = AkShareAdapter()
    bars = a.get_bars(
        "600519",
        BarInterval.D1,
        start=date(2024, 1, 3),
        end=date(2024, 1, 3),
    )
    assert len(bars) == 1
    assert bars[0].timestamp.date() == date(2024, 1, 3)


# ---------- 健康检查 ----------


def test_health_check_ok(fake_akshare) -> None:
    fake_akshare.stock_individual_info_em.return_value = pd.DataFrame(
        [{"item": "股票简称", "value": "贵州茅台"}]
    )
    a = AkShareAdapter()
    assert a.health_check() is True


def test_health_check_empty_is_false(fake_akshare) -> None:
    fake_akshare.stock_individual_info_em.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.health_check() is False


def test_health_check_exception_is_false(fake_akshare) -> None:
    fake_akshare.stock_individual_info_em.side_effect = Exception("down")
    a = AkShareAdapter()
    assert a.health_check() is False


# ---------- 资金流 ----------


def test_get_today_money_flow_returns_latest(fake_akshare) -> None:
    """当日资金流：取日期最大那行（today-1），不管 fixture 里它排在第几位。"""
    fake_akshare.stock_individual_fund_flow.return_value = _fund_flow_df()
    a = AkShareAdapter()
    flows = a.get_today_money_flow("600519")
    assert len(flows) == 1
    f = flows[0]
    assert f.code == "600519"
    assert f.main_net.amount == Decimal("-2000000.0")
    assert f.super_large_net.amount == Decimal("-1000000.0")
    assert f.large_net.amount == Decimal("-1000000.0")
    assert f.medium_net.amount == Decimal("500000.0")
    assert f.small_net.amount == Decimal("1500000.0")
    assert f.main_net_ratio == Decimal("-5.2")
    # 日期最大那行是 today-1
    from datetime import date as _date
    from datetime import timedelta as _td

    assert f.timestamp.date() == _date.today() - _td(days=1)


def test_get_today_money_flow_returns_max_date_regardless_of_input_order(
    fake_akshare,
) -> None:
    """回归保护：fixture 是升序（最早在前，真实 akshare 顺序），第一行是 today-10。
    get_today_money_flow 必须取日期最大那行（today-1），而不是 iloc[0]。
    """
    fake_akshare.stock_individual_fund_flow.return_value = _fund_flow_df()
    a = AkShareAdapter()
    flows = a.get_today_money_flow("600519")
    assert len(flows) == 1
    from datetime import date as _date
    from datetime import timedelta as _td

    # 取最大日期 today-1，而非第一行 today-10
    assert flows[0].timestamp.date() == _date.today() - _td(days=1)
    assert flows[0].timestamp.date() != _date.today() - _td(days=10)


def test_get_today_money_flow_passes_market_suffix(fake_akshare) -> None:
    """sh/sz/bj 后缀根据代码头正确传给接口。"""
    fake_akshare.stock_individual_fund_flow.return_value = pd.DataFrame()
    a = AkShareAdapter()
    a.get_today_money_flow("600519")  # SH
    assert fake_akshare.stock_individual_fund_flow.call_args.kwargs["market"] == "sh"
    assert fake_akshare.stock_individual_fund_flow.call_args.kwargs["stock"] == "600519"

    a.get_today_money_flow("000001")  # SZ
    assert fake_akshare.stock_individual_fund_flow.call_args.kwargs["market"] == "sz"

    a.get_today_money_flow("920001")  # BJ
    assert fake_akshare.stock_individual_fund_flow.call_args.kwargs["market"] == "bj"


def test_get_today_money_flow_empty_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_individual_fund_flow.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.get_today_money_flow("600519") == []


def test_get_today_money_flow_exception_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_individual_fund_flow.side_effect = RuntimeError("API down")
    a = AkShareAdapter()
    assert a.get_today_money_flow("600519") == []


def test_get_history_money_flow_returns_all(fake_akshare) -> None:
    """历史资金流：days=30 覆盖两条（1 天 + 10 天都 ≤ 30）。"""
    fake_akshare.stock_individual_fund_flow.return_value = _fund_flow_df()
    a = AkShareAdapter()
    flows = a.get_history_money_flow("600519", days=30)
    assert len(flows) == 2


def test_get_history_money_flow_days_filter(fake_akshare) -> None:
    """days=5 只保留近 5 天（10 天前那条被过滤）。"""
    fake_akshare.stock_individual_fund_flow.return_value = _fund_flow_df()
    a = AkShareAdapter()
    flows = a.get_history_money_flow("600519", days=5)
    assert len(flows) == 1
    from datetime import date as _date
    from datetime import timedelta as _td

    assert flows[0].timestamp.date() == _date.today() - _td(days=1)


def test_get_history_money_flow_exception_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_individual_fund_flow.side_effect = Exception("network")
    a = AkShareAdapter()
    assert a.get_history_money_flow("600519") == []


def test_get_history_money_flow_empty_df_returns_empty(fake_akshare) -> None:
    fake_akshare.stock_individual_fund_flow.return_value = pd.DataFrame()
    a = AkShareAdapter()
    assert a.get_history_money_flow("600519") == []


# ---------- 仍不实现的方法（返回空，留给 fallback 链）----------


def test_unimplemented_methods_return_empty(fake_akshare) -> None:
    """盘口/逐笔/板块反查 akshare 不实现，留给 efinance。"""
    a = AkShareAdapter()
    assert a.get_order_book("600519") is None
    assert a.get_ticks("600519") == []
    assert a.get_belonging_boards("600519") == []


# ---------- 降级：akshare 未安装 ----------


def test_degrades_when_akshare_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """没装 akshare 时所有方法返回 None/空，不抛 ImportError。"""
    # 模拟 import akshare 失败
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "akshare":
            raise ImportError("No module named 'akshare'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # 从 sys.modules 清掉（如果之前 fake_akshare 注入过）
    monkeypatch.delitem(sys.modules, "akshare", raising=False)

    a = AkShareAdapter()
    assert a.get_quote("600519") is None
    assert a.get_quotes(["600519"]) == []
    assert a.list_market_quotes() == []
    assert a.get_bars("600519", BarInterval.D1) == []
    assert a.health_check() is False


# ---------- build_default_adapter 工厂 ----------


def test_build_default_adapter_includes_akshare_when_available(
    fake_akshare, monkeypatch: pytest.MonkeyPatch
) -> None:
    """akshare 可用时，工厂把它加进 fallback 链。"""
    adapter = build_default_adapter()
    assert "akshare" in adapter.name


def test_build_default_adapter_skips_akshare_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """akshare 不可用时，工厂跳过它（链里只有 efinance + tencent）。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "akshare":
            raise ImportError("No module named 'akshare'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "akshare", raising=False)

    adapter = build_default_adapter()
    assert "akshare" not in adapter.name
    assert "efinance" in adapter.name
    assert "tencent" in adapter.name
