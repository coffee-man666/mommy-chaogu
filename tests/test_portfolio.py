from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.backtest.metrics import drawdown_fraction
from mommy_chaogu.portfolio.analysis import PortfolioAnalyzer
from mommy_chaogu.portfolio.store import (
    PortfolioError,
    PortfolioStore,
    PositionNotFoundError,
)


@pytest.fixture
def store(tmp_path: Path):
    with PortfolioStore(tmp_path / "portfolio.db") as value:
        yield value


def test_position_crud_adjustments_and_summary(store: PortfolioStore) -> None:
    position = store.add_position("600519", None, Decimal("100"), 100, note="core")
    assert store.update_position_name("600519", "贵州茅台") == 1
    store.add_adjustment(position.id, "buy", Decimal("120"), 20)
    store.add_adjustment(position.id, "sell", Decimal("130"), 10)
    store.add_adjustment(position.id, "dividend", Decimal("2"), 110)

    loaded = store.get_position(position.id)
    assert loaded.name == "贵州茅台"
    assert loaded.shares == 110
    assert len(store.list_adjustments(position.id)) == 3
    avg_cost, shares = store.cost_basis(loaded)
    assert shares == 110
    assert avg_cost == Decimal("101.3333")

    summary = store.summary({"600519": Decimal("125")})
    assert summary["n_positions"] == 1
    assert summary["total_market_value"] == Decimal("13750")
    assert summary["total_unrealized_pnl"] == Decimal("2603.3370")

    store.remove_position(position.id)
    assert store.list_positions() == []


def test_portfolio_validation_and_missing_rows(store: PortfolioStore) -> None:
    with pytest.raises(PositionNotFoundError):
        store.get_position(404)
    with pytest.raises(PositionNotFoundError):
        store.remove_position(404)
    with pytest.raises(PositionNotFoundError):
        store.add_adjustment(404, "buy", Decimal("1"), 1)
    with pytest.raises(PortfolioError, match="action"):
        store.add_adjustment(1, "hold", Decimal("1"), 1)
    with pytest.raises(PortfolioError, match="正数"):
        store.add_adjustment(1, "buy", Decimal("1"), 0)


def test_summary_without_prices_and_closed_position(store: PortfolioStore) -> None:
    position = store.add_position("000001", "平安银行", Decimal("10"), 10)
    store.add_adjustment(position.id, "sell", Decimal("11"), 20)
    loaded = store.get_position(position.id)
    assert store.cost_basis(loaded) == (Decimal("0"), 0)
    summary = store.summary({})
    assert summary["total_market_value"] is None
    assert summary["total_unrealized_pnl"] is None


def test_analyzer_sector_correlation_and_risk(store: PortfolioStore) -> None:
    store.add_position("AAA", "Alpha", Decimal("10"), 100)
    store.add_position("BBB", "Beta", Decimal("20"), 50)
    adapter = MagicMock()
    adapter.get_quotes.return_value = [
        SimpleNamespace(code="AAA", price=Decimal("12")),
        SimpleNamespace(code="BBB", price=Decimal("18")),
    ]
    adapter.get_belonging_boards.side_effect = lambda code: [
        SimpleNamespace(name="科技" if code == "AAA" else "金融")
    ]
    cache = MagicMock()
    dates4 = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]

    def _bars(code: str, *_args: object) -> list[dict]:
        closes = ["10", "11", "10", "12"] if code == "AAA" else ["20", "19", "21", "18"]
        return [{"close": c, "timestamp": f"{d}T15:00:00+08:00"} for d, c in zip(dates4, closes, strict=False)]

    cache.get_bars.side_effect = _bars

    analyzer = PortfolioAnalyzer(store, adapter, cache)
    sectors = analyzer.sector_concentration()
    assert sectors["科技"] == pytest.approx(57.142857)
    assert sectors["金融"] == pytest.approx(42.857143)
    correlation = analyzer.correlation_matrix(days=3)
    assert correlation["AAA"]["AAA"] == 1.0
    assert correlation["AAA"]["BBB"] < 0
    risk = analyzer.risk_metrics(days=3)
    assert risk["max_drawdown_pct"] > 0
    assert risk["volatility_pct"] > 0


def test_analyzer_correlation_aligns_by_date_not_index(store: PortfolioStore) -> None:
    """交易日历错开（停牌/数据缺口）时，相关性按日期交集对齐。

    构造：公共日期上 BBB 收益恰好是 AAA 的 2 倍（完美正相关），
    但两边各有一天对方没有的"噪声日"。按数组索引对齐会得到 <1 的值。
    """
    store.add_position("AAA", "Alpha", Decimal("10"), 100)
    store.add_position("BBB", "Beta", Decimal("20"), 50)
    adapter = MagicMock()
    cache = MagicMock()

    def _bars(code: str, *_args: object) -> list[dict]:
        if code == "AAA":
            # d1→d2: +10%，d2→d3: +20%，d3→d4: -10%
            schedule = [("2026-06-01", "100"), ("2026-06-02", "110"), ("2026-06-03", "132"), ("2026-06-04", "118.8")]
        else:
            # BBB 停牌 d1；公共日 d3/d4 的收益是 AAA 同日收益的 2 倍；d5 是噪声日
            schedule = [("2026-06-02", "100"), ("2026-06-03", "140"), ("2026-06-04", "112"), ("2026-06-05", "130")]
        return [{"close": c, "timestamp": f"{d}T15:00:00+08:00"} for d, c in schedule]

    cache.get_bars.side_effect = _bars

    analyzer = PortfolioAnalyzer(store, adapter, cache)
    correlation = analyzer.correlation_matrix(days=10)
    # 公共日 d3/d4：(0.2, -0.1) 与 (0.4, -0.2) 完美线性 → 1.0
    assert correlation["AAA"]["BBB"] == 1.0
    assert correlation["BBB"]["AAA"] == 1.0


def test_analyzer_risk_metrics_aligns_by_date(store: PortfolioStore) -> None:
    """组合日收益按日期对齐：停牌日记 0（价格冻结），而不是按索引错位拼接。"""
    store.add_position("AAA", "Alpha", Decimal("10"), 100)
    store.add_position("BBB", "Beta", Decimal("20"), 50)
    adapter = MagicMock()  # 无报价 → 均权
    cache = MagicMock()

    def _bars(code: str, *_args: object) -> list[dict]:
        if code == "AAA":
            # 日收益：d2 +10%，d3 +20%，d4 -10%
            schedule = [("2026-06-01", "100"), ("2026-06-02", "110"), ("2026-06-03", "132"), ("2026-06-04", "118.8")]
        else:
            # BBB 停牌 d2：只有 d3/d4 两笔收益（均为 0）
            schedule = [("2026-06-01", "100"), ("2026-06-03", "100"), ("2026-06-04", "100")]
        return [{"close": c, "timestamp": f"{d}T15:00:00+08:00"} for d, c in schedule]

    cache.get_bars.side_effect = _bars

    analyzer = PortfolioAnalyzer(store, adapter, cache)
    risk = analyzer.risk_metrics(days=10)
    # 按日期对齐的组合日收益（均权）：d2 0.05、d3 0.10、d4 -0.05
    # 净值 1 → 1.05 → 1.155 → 1.09725，最大回撤 = 0.05775/1.155 = 5.0%
    assert risk["max_drawdown_pct"] == pytest.approx(5.0, abs=0.01)


def test_analyzer_empty_and_math_boundaries(store: PortfolioStore) -> None:
    analyzer = PortfolioAnalyzer(store)
    assert analyzer.sector_concentration() == {}
    assert analyzer.correlation_matrix() == {}
    assert analyzer.risk_metrics() == {
        "max_drawdown_pct": 0.0,
        "volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
    }
    assert analyzer._pearson([1.0], [1.0]) == 0
    assert analyzer._pearson([1.0, 1.0], [2.0, 2.0]) == 0
    assert drawdown_fraction(analyzer._cumulative_equity([0.1, -0.2, 0.1])) > 0
