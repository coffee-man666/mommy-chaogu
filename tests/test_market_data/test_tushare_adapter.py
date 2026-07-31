"""TushareAdapter 单元测试（不依赖网络/token）。"""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from mommy_chaogu.market_data.tushare_adapter import (
    TushareAdapter,
    apply_adjustment,
    from_tushare_code,
    to_tushare_code,
)
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    MarketType,
    Money,
)

# ---------- 代码转换 ----------


class TestCodeConversion:
    def test_internal_to_tushare_sh(self) -> None:
        assert to_tushare_code("600519") == "600519.SH"

    def test_internal_to_tushare_sz(self) -> None:
        assert to_tushare_code("000001") == "000001.SZ"

    def test_internal_to_tushare_with_explicit_market(self) -> None:
        assert to_tushare_code("600519", MarketType.SH) == "600519.SH"
        assert to_tushare_code("000001", MarketType.SZ) == "000001.SZ"

    def test_already_tushare_format_unchanged(self) -> None:
        assert to_tushare_code("600519.SH") == "600519.SH"
        assert to_tushare_code("000001.SZ") == "000001.SZ"

    def test_tushare_to_internal_with_market(self) -> None:
        code, market = from_tushare_code("600519.SH")
        assert code == "600519"
        assert market == MarketType.SH

    def test_tushare_to_internal_sz(self) -> None:
        code, market = from_tushare_code("000001.SZ")
        assert code == "000001"
        assert market == MarketType.SZ

    def test_roundtrip(self) -> None:
        for original in ["600519", "000001", "300750"]:
            ts_code = to_tushare_code(original)
            recovered, _ = from_tushare_code(ts_code)
            assert recovered == original


# ---------- Adapter 基础行为 ----------


class TestTushareAdapterInit:
    def test_no_token_means_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUSHARE_TOKEN", None)
            adp = TushareAdapter()
            assert adp.is_available is False

    def test_explicit_empty_token_means_unavailable(self) -> None:
        adp = TushareAdapter(token="")
        assert adp.is_available is False

    def test_token_from_env(self) -> None:
        """token 从 TUSHARE_TOKEN 读：mock 掉 pro_api 避免真的去连。"""
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake_token_xxx"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                adp = TushareAdapter()
                # 初始化过程中会调 tushare.set_token + tushare.pro_api
                assert adp._token == "fake_token_xxx"
                # pro_api 被调用过（fake_token 也走通）
                mock_pro.assert_called_once()

    def test_explicit_token_override(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "env_token"}),
            patch("tushare.pro_api"),
        ):
                adp = TushareAdapter(token="explicit_token")
                assert adp._token == "explicit_token"


# ---------- 方法在没有 token 时的退化行为 ----------


class TestTushareAdapterNoToken:
    @pytest.fixture
    def adp(self) -> TushareAdapter:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUSHARE_TOKEN", None)
            return TushareAdapter()

    def test_get_quote_returns_none(self, adp: TushareAdapter) -> None:
        assert adp.get_quote("600519") is None

    def test_get_quotes_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.get_quotes(["600519", "000001"]) == []

    def test_list_market_quotes_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.list_market_quotes() == []

    def test_get_order_book_returns_none(self, adp: TushareAdapter) -> None:
        assert adp.get_order_book("600519") is None

    def test_get_bars_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.get_bars("600519", BarInterval.D1, AdjustmentType.FORWARD) == []

    def test_get_ticks_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.get_ticks("600519") == []

    def test_get_today_money_flow_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.get_today_money_flow("600519") == []

    def test_get_history_money_flow_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.get_history_money_flow("600519", days=30) == []

    def test_get_belonging_boards_returns_empty(self, adp: TushareAdapter) -> None:
        assert adp.get_belonging_boards("600519") == []

    def test_health_check_false(self, adp: TushareAdapter) -> None:
        assert adp.health_check() is False


# ---------- 方法在异常时的健壮性（mock token 但 API 失败）----------


class TestTushareAdapterRobustness:
    """有 token 但 API 抛错时，所有方法应该静默返回 None/空，不抛异常。"""

    @pytest.fixture
    def adp(self) -> TushareAdapter:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                # 让 pro_api 返回一个 mock，所有 query 抛异常
                mock_pro.return_value.query.side_effect = Exception("API down")
                return TushareAdapter()

    def test_quote_handles_exception(self, adp: TushareAdapter) -> None:
        assert adp.get_quote("600519") is None

    def test_bars_handles_exception(self, adp: TushareAdapter) -> None:
        assert adp.get_bars("600519", BarInterval.D1) == []

    def test_money_flow_handles_exception(self, adp: TushareAdapter) -> None:
        assert adp.get_history_money_flow("600519") == []

    def test_health_check_handles_exception(self, adp: TushareAdapter) -> None:
        assert adp.health_check() is False


# ---------- 复权参数传递 ----------


class TestTushareBarsAdjustment:
    """验证 get_bars 正确传透复权参数给 pro_bar。

    pro_bar 是从 tushare.pro.data_pro 导入的顶层函数，
    我们 mock 它来检查传入的 adj 参数。
    """

    @pytest.fixture
    def adp_with_token(self) -> TushareAdapter:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.query.side_effect = Exception("not used")
                return TushareAdapter()

    def test_forward_adjustment_passes_qfq(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            # 模拟 pro_bar 返回空 DataFrame
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame()

            adp_with_token.get_bars("600519", BarInterval.D1, AdjustmentType.FORWARD)
            assert mock_pro_bar.called
            call_kwargs = mock_pro_bar.call_args.kwargs
            assert call_kwargs.get("adj") == "qfq"

    def test_backward_adjustment_passes_hfq(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame()

            adp_with_token.get_bars("600519", BarInterval.D1, AdjustmentType.BACKWARD)
            call_kwargs = mock_pro_bar.call_args.kwargs
            assert call_kwargs.get("adj") == "hfq"

    def test_no_adjustment_passes_none(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame()

            adp_with_token.get_bars("600519", BarInterval.D1, AdjustmentType.NONE)
            call_kwargs = mock_pro_bar.call_args.kwargs
            assert call_kwargs.get("adj") is None

    def test_d1_interval_passes_d_freq(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame()

            adp_with_token.get_bars("600519", BarInterval.D1)
            call_kwargs = mock_pro_bar.call_args.kwargs
            assert call_kwargs.get("freq") == "D"

    def test_m5_interval_passes_5min_freq(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame()

            adp_with_token.get_bars("600519", BarInterval.M5)
            call_kwargs = mock_pro_bar.call_args.kwargs
            assert call_kwargs.get("freq") == "5min"

    def test_pro_bar_exception_returns_empty(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            mock_pro_bar.side_effect = Exception("API timeout")
            result = adp_with_token.get_bars("600519")
            assert result == []


# ---------- 复权工具函数 apply_adjustment ----------


def _make_bars(prices: list[tuple[str, str, str, str, str]]) -> list[Bar]:
    """生成测试用 K 线。prices: [(date, open, high, low, close), ...]"""
    from datetime import datetime
    from decimal import Decimal

    return [
        Bar(
            code="600519",
            name="贵州茅台",
            interval=BarInterval.D1,
            adjustment=AdjustmentType.NONE,
            timestamp=datetime.strptime(d, "%Y-%m-%d"),
            open=Decimal(o),
            high=Decimal(h),
            low=Decimal(low_p),
            close=Decimal(c),
            volume=1000,
            turnover=Money(Decimal("1000000"), "CNY"),
        )
        for d, o, h, low_p, c in prices
    ]


class TestApplyAdjustment:
    """验证前/后复权算法。

    复权逻辑:
        前复权:  adj = raw * (latest / current)  → 最新价不变
        后复权:  adj = raw * (earliest / current)  → 最早价不变
    """

    def test_no_adjustment_returns_unchanged(self) -> None:
        bars = _make_bars([("2024-01-02", "100", "105", "99", "102")])
        result = apply_adjustment(bars, pd.DataFrame(), AdjustmentType.NONE)
        assert result is bars or result == bars

    def test_empty_bars_returns_empty(self) -> None:
        result = apply_adjustment([], pd.DataFrame(), AdjustmentType.FORWARD)
        assert result == []

    def test_empty_factors_returns_bars_unchanged(self) -> None:
        bars = _make_bars([("2024-01-02", "100", "105", "99", "102")])
        result = apply_adjustment(bars, pd.DataFrame(), AdjustmentType.FORWARD)
        assert len(result) == 1
        assert result[0].close == bars[0].close

    def test_forward_adjustment_keeps_latest_price(self) -> None:
        """前复权：最新一天的收盘价应该等于原始收盘价。"""
        # 3 天 K 线，价格不变
        bars = _make_bars([
            ("2024-01-02", "100", "105", "99", "102"),
            ("2024-01-03", "102", "107", "101", "105"),
            ("2024-01-04", "105", "110", "104", "108"),
        ])
        # 复权因子：1/2 = 1.0, 1/3 = 1.0, 1/4 = 1.0 (未除权)
        factors = pd.DataFrame({
            "trade_date": ["20240102", "20240103", "20240104"],
            "adj_factor": [1.0, 1.0, 1.0],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        # 因子全 1.0，比例 = 1.0 / 1.0 = 1.0 → 价不变
        assert result[2].close == bars[2].close  # 108
        # 调整标记
        assert result[2].adjustment == AdjustmentType.FORWARD

    def test_forward_adjustment_handles_dividend(self) -> None:
        """前复权：发生除权后，历史价会下调。"""
        # 2 天 K 线：第一天除权前，第二天除权后
        bars = _make_bars([
            ("2024-01-02", "100", "105", "99", "102"),  # 除权前
            ("2024-01-03", "98", "103", "97", "100"),    # 除权后
        ])
        # 复权因子：除权日因子变小（说明除权了）
        # 2024-01-02: adj_factor = 2.0 (基准)
        # 2024-01-03: adj_factor = 1.0 (除权后)
        factors = pd.DataFrame({
            "trade_date": ["20240102", "20240103"],
            "adj_factor": [2.0, 1.0],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        # 前复权: ratio = latest_factor / current_factor
        #   2024-01-02: ratio = 1.0 / 2.0 = 0.5  → 价减半
        #   2024-01-03: ratio = 1.0 / 1.0 = 1.0  → 价不变
        assert result[1].close == 100  # 最新价不变
        assert result[0].close == 51    # 历史价减半 (102 * 0.5)
        # OHLC 都要调整
        assert result[0].open == 50    # 100 * 0.5
        assert result[0].high == Decimal("52.5")  # 105 * 0.5

    def test_backward_adjustment_keeps_earliest_price(self) -> None:
        """后复权：最早一天的收盘价应该等于原始收盘价。"""
        bars = _make_bars([
            ("2024-01-02", "100", "105", "99", "102"),
            ("2024-01-03", "98", "103", "97", "100"),
        ])
        factors = pd.DataFrame({
            "trade_date": ["20240102", "20240103"],
            "adj_factor": [2.0, 1.0],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.BACKWARD)
        # 后复权: ratio = earliest_factor / current_factor
        #   2024-01-02: ratio = 2.0 / 2.0 = 1.0  → 价不变
        #   2024-01-03: ratio = 2.0 / 1.0 = 2.0  → 价倍增
        assert result[0].close == 102  # 最早价不变
        assert result[1].close == 200  # 100 * 2.0

    def test_ohlc_all_adjusted_consistently(self) -> None:
        """前复权后，OHLC 之间的相对关系（high >= close 等）保持。"""
        bars = _make_bars([("2024-01-02", "100", "105", "99", "102")])
        factors = pd.DataFrame({
            "trade_date": ["20240102"],
            "adj_factor": [0.5],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        assert result[0].high >= result[0].low
        assert result[0].high >= result[0].close
        assert result[0].low <= result[0].close
        assert result[0].open >= result[0].low
        assert result[0].open <= result[0].high

    def test_volume_not_adjusted(self) -> None:
        """成交量不复权（除权除息不影响量）。"""
        bars = _make_bars([("2024-01-02", "100", "105", "99", "102")])
        bars[0] = Bar(
            code=bars[0].code, name=bars[0].name, interval=bars[0].interval,
            adjustment=bars[0].adjustment, timestamp=bars[0].timestamp,
            open=bars[0].open, high=bars[0].high, low=bars[0].low, close=bars[0].close,
            volume=12345,  # 原始成交量
            turnover=Money(Decimal("67890"), "CNY"),
        )
        factors = pd.DataFrame({
            "trade_date": ["20240102"],
            "adj_factor": [0.5],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        assert result[0].volume == 12345  # 成交量不变

    def test_missing_factor_for_date_keeps_bar_unchanged(self) -> None:
        """中间某个 bar 找不到因子：只跳过那根，其他正常调整。"""
        bars = _make_bars([
            ("2024-01-02", "100", "105", "99", "102"),
            ("2024-01-03", "200", "210", "198", "204"),  # 没因子
            ("2024-01-04", "98", "103", "97", "100"),
        ])
        # 给了 2024-01-02 和 2024-01-04 的因子，2024-01-03 缺失
        factors = pd.DataFrame({
            "trade_date": ["20240102", "20240104"],
            "adj_factor": [2.0, 1.0],  # 最新因子 = 1.0
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        # 第 1 根：2024-01-02, factor=2.0, ratio = 1.0/2.0 = 0.5 → close 减半
        assert result[0].close == 51  # 102 * 0.5
        # 第 2 根：2024-01-03 找不到因子 → 跳过调整，保持原值
        assert result[1].close == 204
        # 第 3 根：2024-01-04, factor=1.0, ratio = 1.0/1.0 = 1.0 → 不变
        assert result[2].close == 100

    def test_missing_anchor_factor_returns_unchanged(self) -> None:
        """如果最新/最旧那根 bar 找不到因子（锚点丢失），安全返回原始 bars。"""
        # 缺 2024-01-04 的因子（最新 bar 锚点）
        bars = _make_bars([
            ("2024-01-02", "100", "105", "99", "102"),
            ("2024-01-03", "98", "103", "97", "100"),
            ("2024-01-04", "200", "210", "198", "204"),
        ])
        factors = pd.DataFrame({
            "trade_date": ["20240102", "20240103"],  # 缺 2024-01-04
            "adj_factor": [2.0, 1.0],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        # 锚点丢失 → 全部保持原值
        assert result[0].close == 102
        assert result[1].close == 100
        assert result[2].close == 204

    def test_accepts_timestamp_dates(self) -> None:
        """trade_date 可以是 Timestamp / date，不一定必须是字符串。"""
        bars = _make_bars([("2024-01-02", "100", "105", "99", "102")])
        factors = pd.DataFrame({
            "trade_date": [pd.Timestamp("2024-01-02")],
            "adj_factor": [1.0],
        })
        result = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        assert result[0].close == 102  # factor=1.0 不变

    def test_does_not_mutate_input_bars(self) -> None:
        """重要：原 bars 列表不能被修改（Bar 是 frozen dataclass，自然满足）。"""
        bars = _make_bars([("2024-01-02", "100", "105", "99", "102")])
        original_close = bars[0].close
        factors = pd.DataFrame({
            "trade_date": ["20240102"],
            "adj_factor": [0.5],
        })
        _ = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
        # 原 bar 不变
        assert bars[0].close == original_close


# ---------- fetch_and_adjust 便捷方法 ----------


class TestFetchAndAdjust:
    @pytest.fixture
    def adp_with_token(self) -> TushareAdapter:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.query.side_effect = Exception("not used")
                return TushareAdapter()

    def test_returns_empty_when_no_token(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUSHARE_TOKEN", None)
            adp = TushareAdapter()
            result = adp.fetch_and_adjust("600519")
            assert result == []

    def test_returns_empty_when_get_bars_empty(self, adp_with_token: TushareAdapter) -> None:
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame()
            result = adp_with_token.fetch_and_adjust("600519")
            assert result == []

    def test_applies_adjustment_on_success(self, adp_with_token: TushareAdapter) -> None:
        """完整流程：拉 K 线 + 拉因子 + 应用复权。"""
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            # 模拟 pro_bar 返回 2 根 K 线
            mock_pro_bar.return_value = pd.DataFrame({
                "trade_date": ["20240102", "20240103"],
                "open": [100.0, 98.0],
                "high": [105.0, 103.0],
                "low": [99.0, 97.0],
                "close": [102.0, 100.0],
                "vol": [1000, 1100],
                "amount": [100000.0, 105000.0],
            })
            # mock adj_factor
            adp_with_token._pro.adj_factor = MagicMock(return_value=pd.DataFrame({
                "trade_date": ["20240102", "20240103"],
                "adj_factor": [2.0, 1.0],
            }))
            result = adp_with_token.fetch_and_adjust(
                "600519", mode=AdjustmentType.FORWARD
            )
            assert len(result) == 2
            # 前复权：最新价（result[1]）= 100 不变；历史价（result[0]）减半
            assert result[1].close == 100
            assert result[0].close == 51  # 102 * 0.5

    def test_returns_bars_when_adj_factor_fails(self, adp_with_token: TushareAdapter) -> None:
        """adj_factor 失败时降级返回原始 K 线（不抛异常）。"""
        with patch("tushare.pro.data_pro.pro_bar") as mock_pro_bar:
            import pandas as pd
            mock_pro_bar.return_value = pd.DataFrame({
                "trade_date": ["20240102"],
                "open": [100.0], "high": [105.0], "low": [99.0], "close": [102.0],
                "vol": [1000], "amount": [100000.0],
            })
            adp_with_token._pro.adj_factor = MagicMock(side_effect=Exception("API down"))
            result = adp_with_token.fetch_and_adjust("600519")
            assert len(result) == 1
            assert result[0].close == 102  # 原始价


# ---------- 财务数据接口 ----------


class TestTushareFinancials:
    @pytest.fixture
    def adp_no_token(self) -> TushareAdapter:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TUSHARE_TOKEN", None)
            return TushareAdapter()

    @pytest.fixture
    def adp_with_token(self) -> TushareAdapter:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                return TushareAdapter(), mock_pro

    def test_financial_indicator_no_token(self, adp_no_token: TushareAdapter) -> None:
        assert adp_no_token.get_financial_indicator("600519") == []

    def test_financial_indicator_with_token(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.fina_indicator.return_value = pd.DataFrame({
                    "ts_code": ["600519.SH"],
                    "end_date": ["20240930"],
                    "roe": [25.5],
                    "gross_profit_margin": [91.2],
                })
                adp = TushareAdapter()
                result = adp.get_financial_indicator("600519", period="20240930")
                assert len(result) == 1
                assert result[0]["roe"] == 25.5
                # 参数传递验证
                call_kwargs = mock_pro.return_value.fina_indicator.call_args.kwargs
                assert call_kwargs["ts_code"] == "600519.SH"
                assert call_kwargs["period"] == "20240930"

    def test_financial_indicator_handles_exception(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.fina_indicator.side_effect = Exception("API down")
                adp = TushareAdapter()
                result = adp.get_financial_indicator("600519")
                assert result == []

    def test_dividend_history(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.dividend.return_value = pd.DataFrame({
                    "ts_code": ["600519.SH"] * 3,
                    "end_date": ["20231231", "20221231", "20211231"],
                    "cash_div": [30.88, 21.91, 19.29],
                })
                adp = TushareAdapter()
                result = adp.get_dividend_history("600519", limit=3)
                assert len(result) == 3
                assert result[0]["cash_div"] == 30.88
                call_kwargs = mock_pro.return_value.dividend.call_args.kwargs
                assert call_kwargs["ts_code"] == "600519.SH"
                assert call_kwargs["limit"] == 3

    def test_dividend_history_empty(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.dividend.return_value = pd.DataFrame()
                adp = TushareAdapter()
                result = adp.get_dividend_history("600519")
                assert result == []

    def test_income_statement(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.income.return_value = pd.DataFrame({
                    "ts_code": ["600519.SH"],
                    "end_date": ["20240930"],
                    "total_revenue": [120000000000.0],
                    "n_income": [50000000000.0],
                })
                adp = TushareAdapter()
                result = adp.get_income_statement("600519")
                assert len(result) == 1
                assert result[0]["n_income"] == 50000000000.0

    def test_balance_sheet(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.balancesheet.return_value = pd.DataFrame({
                    "ts_code": ["600519.SH"],
                    "end_date": ["20240930"],
                    "total_assets": [200000000000.0],
                })
                adp = TushareAdapter()
                result = adp.get_balance_sheet("600519")
                assert len(result) == 1
                assert result[0]["total_assets"] == 200000000000.0

    def test_cash_flow(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.cashflow.return_value = pd.DataFrame({
                    "ts_code": ["600519.SH"],
                    "end_date": ["20240930"],
                    "n_cashflow_act": [30000000000.0],
                })
                adp = TushareAdapter()
                result = adp.get_cash_flow("600519")
                assert len(result) == 1
                assert result[0]["n_cashflow_act"] == 30000000000.0

    def test_list_all_stocks(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.stock_basic.return_value = pd.DataFrame({
                    "ts_code": ["600519.SH", "000001.SZ"],
                    "name": ["贵州茅台", "平安银行"],
                    "industry": ["白酒", "银行"],
                })
                adp = TushareAdapter()
                result = adp.list_all_stocks()
                assert len(result) == 2
                assert result[0]["name"] == "贵州茅台"

    def test_list_all_stocks_with_status(self) -> None:
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.stock_basic.return_value = pd.DataFrame()
                adp = TushareAdapter()
                adp.list_all_stocks(list_status="D")
                call_kwargs = mock_pro.return_value.stock_basic.call_args.kwargs
                assert call_kwargs["list_status"] == "D"

    def test_period_param_optional(self) -> None:
        """period 不传时不应出现在 kwargs（让 Tushare 走默认=最新期）。"""
        with (
            patch.dict(os.environ, {"TUSHARE_TOKEN": "fake"}),
            patch("tushare.pro_api") as mock_pro,
        ):
                mock_pro.return_value.fina_indicator.return_value = pd.DataFrame()
                adp = TushareAdapter()
                adp.get_financial_indicator("600519")  # 不传 period
                call_kwargs = mock_pro.return_value.fina_indicator.call_args.kwargs
                assert "period" not in call_kwargs
