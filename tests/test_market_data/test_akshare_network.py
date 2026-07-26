"""AkShareAdapter 真实联网冒烟测试。

目的：现有 36 个 AkShare 测试全是 mock，从不真正打 akshare API，所以
akshare 改了中文列名（``市盈率-动态`` / ``主力净流入-净额`` 等）时单测照样
绿——这正是之前 Tushare 集成补丁里凭空捏造字段名、上线才发现坏的根因。
本文件直接打东财后端，把 adapter 依赖的列名假设钉死在真实 API 上。

测试运行需要联网（push2his.eastmoney.com）。默认被 ``pytest -m "not network"``
跳过；要真正跑：``uv run --extra dev pytest -m network tests/test_market_data/test_akshare_network.py``。
"""

from __future__ import annotations

import pytest

from mommy_chaogu.market_data import (
    AdjustmentType,
    AkShareAdapter,
    BarInterval,
    Money,
)


@pytest.fixture(scope="module")
def adp() -> AkShareAdapter:
    return AkShareAdapter()


# ---------- 实时报价：PE/PB/市值 列名 ----------


@pytest.mark.network
def test_network_get_quote_real_fields(adp: AkShareAdapter) -> None:
    """Guard: ``stock_zh_a_spot_em`` 的 PE/PB/市值中文列名映射。

    akshare 相对 efinance 的核心增量就是实时快照里给全 PE/PB/总市值/流通市值/
    换手率/量比。如果 akshare 把 ``市盈率-动态`` / ``总市值`` 等列名改了，
    ``_spot_row_to_quote`` 会静默拿不到值（``row.get`` 返回 None），这里通过
    断言 ``pe_dynamic`` / ``total_market_cap`` 非空把它钉死在真实 API 上。
    用 600519（贵州茅台）——大盘蓝筹，PE/市值永远有值。
    """
    q = adp.get_quote("600519")
    assert q is not None, "get_quote 返回 None，可能 spot 接口整体挂了"
    assert q.code == "600519"
    assert q.price > 0, "最新价应为正"
    assert q.pe_dynamic is not None, "市盈率-动态 列名映射失败或字段缺失"
    assert q.total_market_cap is not None, "总市值 列名映射失败或字段缺失"
    assert q.total_market_cap.amount > 0


# ---------- K 线：OHLC/量/额 列名 + 数据合理性 ----------


@pytest.mark.network
def test_network_get_bars_daily_real_ohlc(adp: AkShareAdapter) -> None:
    """Guard: ``stock_zh_a_hist`` 的 K 线中文列名映射 + 数值合理性。

    依赖的列名：``开盘 / 收盘 / 最高 / 最低 / 成交量 / 成交额 / 日期``。
    ``stock_zh_a_hist`` 是 akshare 的 KeyError 重灾区（akfamily/akshare 一堆
    issue），列名版本飘移会直接 KeyError 拿到空列表。这里用前复权日线、
    limit=5，断言每根 bar 的 OHLC/量额都合理。
    """
    bars = adp.get_bars(
        "600519",
        BarInterval.D1,
        AdjustmentType.FORWARD,
        limit=5,
    )
    assert bars, "get_bars 返回空，可能 stock_zh_a_hist 列名变了或接口失败"
    for b in bars:
        assert b.high >= b.low, f"{b.timestamp}: high({b.high}) < low({b.low})"
        assert b.low <= b.close <= b.high, (
            f"{b.timestamp}: close({b.close}) 不在 [{b.low}, {b.high}] 内"
        )
        assert b.open > 0, f"{b.timestamp}: open={b.open} 非正"
        assert b.volume >= 0, f"{b.timestamp}: volume={b.volume} 为负"
        assert b.turnover.amount > 0, (
            f"{b.timestamp}: 成交额={b.turnover.amount} 非正（成交额 列名映射失败?）"
        )


# ---------- 资金流：主力/超大/大/中/小单 列名（最关键）----------


@pytest.mark.network
def test_network_history_money_flow_real_fields(adp: AkShareAdapter) -> None:
    """Guard: ``stock_individual_fund_flow`` 的资金流中文列名映射。

    **这是本文件存在的核心原因。** 之前 Tushare 集成补丁里凭空捏造了资金流
    字段名、上线直接坏掉，根因就是没有任何联网测试去对真实列名。akshare 的
    资金流接口列名是中文且易飘：``主力净流入-净额 / 超大单净流入-净额 /
    大单净流入-净额 / 中单净流入-净额 / 小单净流入-净额``。这里断言：
    1. 返回非空（接口没整列 KeyError）；
    2. 各档位都是 ``Money`` 对象（列名没改名导致拿到 None→默认 0 也能过，
       所以进一步要求至少有一行 ``main_net`` 真实非零，确认不是全默认值）。
    用 days=10 给接口一点回旋余地。
    """
    flows = adp.get_history_money_flow("600519", days=10)
    assert flows, "get_history_money_flow 返回空，资金流接口列名可能已变"

    for f in flows:
        assert isinstance(f.main_net, Money)
        assert isinstance(f.super_large_net, Money)
        assert isinstance(f.large_net, Money)
        assert isinstance(f.medium_net, Money)
        assert isinstance(f.small_net, Money)

    # 至少一行主力净流入真实非零——否则列名改名后全拿 None→默认 0 也能蒙混。
    assert any(f.main_net.amount != 0 for f in flows), (
        "所有行 main_net 都是 0，主力净流入-净额 列名映射几乎肯定坏了"
    )


# ---------- 健康检查 ----------


@pytest.mark.network
def test_network_health_check(adp: AkShareAdapter) -> None:
    """Guard: health_check 能拉到一行 spot 即视为可用。

    health_check 是 fallback 链判定 akshare 启停的依据，必须真实打通
    ``stock_zh_a_spot_em`` 才返回 True。
    """
    assert adp.health_check() is True
