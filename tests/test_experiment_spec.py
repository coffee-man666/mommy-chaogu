"""ExperimentSpec 序列化与校验测试。"""

from __future__ import annotations

import pytest

from mommy_chaogu.experiment.spec import ExperimentSpec


def _golden_payload() -> dict:
    return {
        "spec_version": 1,
        "id": "exp_semicon_false_break_v1",
        "title": "半导体 ETF 均线假跌破",
        "source": {
            "type": "user_viewpoint",
            "text": "半导体 ETF 跌破中期均线后，如果在几个交易日内收复均线并重新进入通道，往往是假跌破。",
        },
        "hypothesis": "收盘价跌破 EMA55/89 云带下沿后 5 个交易日内收复云带上沿并回到回归通道内，"
        "随后 20 个交易日的收益显著优于基准。",
        "market": "US",
        "universe": ["SOXX", "SMH", "QQQ"],
        "frequency": "1d",
        "date_range": {"start": "2016-01-01", "end": "2026-07-31"},
        "data_requirements": ["adjusted_ohlcv"],
        "features": [
            {"type": "ema_cloud", "window": 89, "params": {"fast": 55, "slow": 89}},
            {"type": "linreg_channel", "window": 60, "params": {"k": 2.0}},
        ],
        "entry_rule": {
            "condition": "false_breakdown_reclaim",
            "params": {"cloud_fast": 55, "cloud_slow": 89, "channel_window": 60, "max_days_below": 5},
            "note": "收盘跌破 EMA55/89 云带下沿 → 5 个交易日内收盘重新站上云带上沿，"
            "且收盘回到 60 日回归通道（k=2σ）下轨之上。",
        },
        "exit_rule": {
            "condition": "composite_exit",
            "params": {"hold_days": 20, "stop_loss_pct": 0.08, "take_profit_pct": 0.15},
            "note": "固定持有 20 个交易日，期间触发 8% 止损或 15% 止盈则提前退出。",
        },
        "position_sizing": {"type": "equal_weight"},
        "cost_model": "us_equity_default",
        "validation": {"walk_forward": True, "regime_analysis": True, "benchmark": "SPY"},
        "assumptions": [
            "「中期均线」解释为 EMA55/89 云带：收盘低于云带下沿视为跌破，收盘高于云带上沿视为收复。",
            "「几个交易日」解释为 5 个交易日。",
            "「重新进入通道」解释为收盘价回到 60 日回归通道（k=2σ）下轨之上。",
        ],
    }


class TestGoldenRoundTrip:
    def test_round_trip(self) -> None:
        spec = ExperimentSpec.from_dict(_golden_payload())
        assert ExperimentSpec.from_json(spec.to_json()) == spec

    def test_fields(self) -> None:
        spec = ExperimentSpec.from_dict(_golden_payload())
        assert spec.market == "US"
        assert spec.universe == ["SOXX", "SMH", "QQQ"]
        assert len(spec.assumptions) == 3
        assert spec.validation.benchmark == "SPY"
        assert spec.entry_rule.condition == "false_breakdown_reclaim"
        assert spec.features[0].type == "ema_cloud"
        assert spec.features[1].type == "linreg_channel"


class TestValidation:
    def test_missing_field(self) -> None:
        payload = _golden_payload()
        del payload["hypothesis"]
        with pytest.raises(ValueError, match="缺少字段"):
            ExperimentSpec.from_dict(payload)

    def test_bad_id(self) -> None:
        payload = _golden_payload()
        payload["id"] = "Bad ID!"
        with pytest.raises(ValueError, match="id"):
            ExperimentSpec.from_dict(payload)

    def test_empty_universe(self) -> None:
        payload = _golden_payload()
        payload["universe"] = []
        with pytest.raises(ValueError, match="universe"):
            ExperimentSpec.from_dict(payload)

    def test_unknown_feature(self) -> None:
        payload = _golden_payload()
        payload["features"] = [{"type": "bollinger", "window": 20}]
        with pytest.raises(ValueError, match="type"):
            ExperimentSpec.from_dict(payload)

    def test_unknown_entry_condition(self) -> None:
        payload = _golden_payload()
        payload["entry_rule"]["condition"] = "buy_the_dip"
        with pytest.raises(ValueError, match="condition"):
            ExperimentSpec.from_dict(payload)

    def test_inverted_date_range(self) -> None:
        payload = _golden_payload()
        payload["date_range"] = {"start": "2026-01-01", "end": "2016-01-01"}
        with pytest.raises(ValueError, match="date_range"):
            ExperimentSpec.from_dict(payload)

    def test_only_daily_frequency(self) -> None:
        payload = _golden_payload()
        payload["frequency"] = "1h"
        with pytest.raises(ValueError, match="1d"):
            ExperimentSpec.from_dict(payload)

    def test_universe_normalized_to_upper(self) -> None:
        payload = _golden_payload()
        payload["universe"] = ["soxx", " smh "]
        spec = ExperimentSpec.from_dict(payload)
        assert spec.universe == ["SOXX", "SMH"]
