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
    adapter.get_today_money_flow.side_effect = lambda code: [
        _flow(code, "2.5" if code == "600000" else "0.4")
    ]
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
    result = _payload(
        analysis._handle_screen_inflow_stocks(ToolContext(adapter=adapter), {"codes": codes})
    )
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
    result = _payload(
        analysis._handle_screen_inflow_stocks(ToolContext(adapter=MagicMock()), {"codes": []})
    )
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


def test_volume_breakout_hit_record_marks_hit_true() -> None:
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", index, "100", 100) for index in range(5)] + [
        _bar("600519", 5, "103", 200, "3")
    ]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "volume_breakout"}
        )
    )
    assert result["results"][0]["hit"] is True
    assert result["count"] == 1


def test_high_20_breakout_hit() -> None:
    """前 20 根高点 100（high=close），第 21 根收盘 105 → 突破命中。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(20)] + [
        _bar("600519", 20, "105", 100, "5")
    ]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "high_20_breakout"}
        )
    )
    assert result["count"] == 1
    record = result["results"][0]
    assert record["signal"] == "high_20_breakout"
    assert record["hit"] is True
    assert record["close"] == "105"
    evidence = result["evidence"][0]
    assert evidence["hit"] is True
    assert evidence["high_20"] == "100"
    assert evidence["ma20"] == "100.25"
    assert evidence["bars_used"] == 21


def test_high_20_breakout_miss_still_outputs_basis() -> None:
    """未突破也输出依据：20 日高点、最新完成 K 收盘、依据根数。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(20)] + [
        _bar("600519", 20, "99", 100, "-1")
    ]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "high_20_breakout"}
        )
    )
    assert result["count"] == 0
    assert result["results"] == []
    assert result["evidence"][0]["hit"] is False
    assert result["evidence"][0]["high_20"] == "100"
    assert result["evidence"][0]["close"] == "99"
    assert result["evidence"][0]["bars_used"] == 21


def test_price_above_ma20_hit_and_miss() -> None:
    """收盘 105 > MA20=100.25 命中；收盘 100 不严格高于 MA20=100 未命中。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(19)] + [
        _bar("600519", 19, "105", 100, "5")
    ]
    hit = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "price_above_ma20"}
        )
    )
    assert hit["count"] == 1
    assert hit["results"][0]["hit"] is True
    assert hit["evidence"][0]["ma20"] == "100.25"
    assert hit["evidence"][0]["close"] == "105"

    adapter2 = MagicMock()
    adapter2.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(20)]
    miss = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter2), {"codes": ["600519"], "signal": "price_above_ma20"}
        )
    )
    assert miss["count"] == 0
    assert miss["evidence"][0]["hit"] is False
    assert miss["evidence"][0]["ma20"] == "100"
    assert miss["evidence"][0]["close"] == "100"
    assert miss["evidence"][0]["bars_used"] == 20


def test_insufficient_bars_gives_null_basis_not_false_hit() -> None:
    """完成 K 不足 20/21 根时依据字段为 None、不命中——不用缺数据凑信号。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(15)]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "high_20_breakout"}
        )
    )
    assert result["count"] == 0
    assert result["evidence"][0] == {
        "code": "600519",
        "name": "股票600519",
        "signal": "high_20_breakout",
        "hit": False,
        "close": "100",
        "high_20": None,
        "ma20": None,
        "bars_used": 15,
    }


def test_no_bars_leaves_zero_bar_evidence_record() -> None:
    """行情拉不到（空 K 线）也输出 bars_used=0 的依据记录，不产出假信号。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = []
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "price_above_ma20"}
        )
    )
    assert result["count"] == 0
    assert result["evidence"][0]["code"] == "600519"
    assert result["evidence"][0]["hit"] is False
    assert result["evidence"][0]["close"] is None
    assert result["evidence"][0]["bars_used"] == 0


def test_count_stays_hit_count_and_evidence_is_capped() -> None:
    """count 保持命中数；evidence 独立字段且按 top20 截断（有界契约）。"""
    adapter = MagicMock()
    # 25 只全部未突破（第 21 根收盘 99 < 前 20 根高点 100）。
    adapter.get_bars.side_effect = lambda code, **_: (
        [_bar(code, i, "100", 100) for i in range(20)] + [_bar(code, 20, "99", 100, "-1")]
    )
    codes = [f"{index:06d}" for index in range(25)]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": codes, "signal": "high_20_breakout"}
        )
    )
    assert result["count"] == 0
    assert result["total"] == 0
    assert len(result["evidence"]) == 20
    assert all(item["hit"] is False for item in result["evidence"])


def test_payload_carries_unverified_adjustment_note() -> None:
    """复权语义未核验的既定边界：输出带「未复权口径」标注。"""
    adapter = MagicMock()
    adapter.get_bars.return_value = [_bar("600519", i, "100", 100) for i in range(21)]
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=adapter), {"codes": ["600519"], "signal": "high_20_breakout"}
        )
    )
    assert "未复权" in result["note"]


def test_invalid_signal_error_lists_all_enums() -> None:
    result = _payload(
        analysis._handle_check_kline_signal(
            ToolContext(adapter=MagicMock()), {"codes": ["600519"], "signal": "nope"}
        )
    )
    assert "high_20_breakout" in result["error"]
    assert "price_above_ma20" in result["error"]
