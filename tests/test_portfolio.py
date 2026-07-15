from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
    cache.get_bars.side_effect = lambda code, *_: [
        {"close": value}
        for value in (["10", "11", "10", "12"] if code == "AAA" else ["20", "19", "21", "18"])
    ]

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
    assert analyzer._max_drawdown([0.1, -0.2, 0.1]) > 0
