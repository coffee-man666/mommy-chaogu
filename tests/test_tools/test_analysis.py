from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from mommy_chaogu.agent.tools import ToolContext, analysis
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money, MoneyFlow


def _flow(code: str, ratio: str | None) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=f"股票{code}",
        timestamp=datetime(2026, 7, 1, 15),
        main_net=Money.from_yuan("100"),
        small_net=Money.from_yuan("0"),
        medium_net=Money.from_yuan("0"),
        large_net=Money.from_yuan("0"),
        super_large_net=Money.from_yuan("0"),
        main_net_ratio=Decimal(ratio) if ratio is not None else None,
    )


def _bar(code: str, day: int, close: str, volume: int, change: str = "0") -> Bar:
    return Bar(
        code=code,
        name=f"股票{code}",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 7, 1) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=volume,
        turnover=Money.from_yuan("100"),
        change_pct=Decimal(change),
    )


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_screen_inflow_converts_percent_to_bp_sorts_and_caps() -> None:
    adapter = MagicMock()
    adapter.get_today_money_flow.side_effect = lambda code: [_flow(code, "2.5" if code == "600000" else "0.4")]
    result = _payload(
        analysis._handle_screen_inflow_stocks(
            ToolContext(adapter=adapter), {"codes": ["000001", "600000"], "threshold_bp": 50}
        )
    )
    assert result["count"] == result["total"] == 1
    assert result["results"][0]["code"] == "600000"
    assert result["results"][0]["ratio_bp"] == "250.0"


def test_screen_inflow_preclips_to_twenty() -> None:
    adapter = MagicMock()
    adapter.get_today_money_flow.side_effect = lambda code: [_flow(code, "1")]
    codes = [f"{index:06d}" for index in range(25)]
    result = _payload(analysis._handle_screen_inflow_stocks(ToolContext(adapter=adapter), {"codes": codes}))
    assert result["count"] == 20
    assert result["total"] == 25


def test_screen_inflow_falls_back_to_circulating_cap_when_ratio_missing() -> None:
    adapter = MagicMock()
    adapter.get_today_money_flow.return_value = [_flow("600519", None)]
    quote = MagicMock()
    quote.circulating_market_cap = Money.from_yuan("10000")
    adapter.get_quote.return_value = quote
    result = _payload(
        analysis._handle_screen_inflow_stocks(
            ToolContext(adapter=adapter), {"codes": ["600519"], "threshold_bp": 50}
        )
    )
    assert result["results"][0]["ratio_bp"] == "100.00"
    adapter.get_quote.assert_called_once_with("600519")


def test_empty_input_has_contract() -> None:
    result = _payload(analysis._handle_screen_inflow_stocks(ToolContext(adapter=MagicMock()), {"codes": []}))
    assert result == {"results": [], "count": 0, "total": 0}


def test_zero_threshold_is_not_replaced_by_default() -> None:
    adapter = MagicMock()
    adapter.get_today_money_flow.return_value = [_flow("600519", "0")]
    result = _payload(
        analysis._handle_screen_inflow_stocks(
            ToolContext(adapter=adapter), {"codes": ["600519"], "threshold_bp": 0}
        )
    )
    assert result["count"] == 1


def test_volume_breakout_uses_completed_bar() -> None:
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", index, "100", 100) for index in range(5)] + [
        _bar("600519", 5, "103", 200, "3")
    ]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "volume_breakout"}
        )
    )
    assert result["results"][0]["volume_ratio"] == "2"


def test_ma_golden_cross_is_detected_recently() -> None:
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(20)] + [
        _bar("600519", 20, "90", 100),
        _bar("600519", 21, "120", 100),
    ]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "ma_golden_cross"}
        )
    )
    assert result["count"] == 1
    assert result["results"][0]["signal"] == "ma_golden_cross"
