"""market_data.utils.detect_market 单元测试。"""

from __future__ import annotations

import pytest

from mommy_chaogu.market_data.types import MarketType
from mommy_chaogu.market_data.utils import detect_market


class TestDetectMarket:
    """A 股代码 → 市场映射。"""

    @pytest.mark.parametrize(
        "code,expected",
        [
            # 沪 A 主板
            ("600519", MarketType.SH),  # 贵州茅台
            ("601318", MarketType.SH),  # 中国平安
            ("603259", MarketType.SH),  # 药明康德
            ("605358", MarketType.SH),  # 国光连锁
            # 沪 A 科创板
            ("688981", MarketType.SH),  # 中芯国际
            # 深 A 主板
            ("000001", MarketType.SZ),  # 平安银行
            ("000002", MarketType.SZ),  # 万科 A
            ("002594", MarketType.SZ),  # 比亚迪
            # 深 A 创业板
            ("300750", MarketType.SZ),  # 宁德时代
            ("301236", MarketType.SZ),  # 软通动力
            # 北交所（新）— 重点回归
            ("830799", MarketType.BJ),  # 艾融软件
            ("871245", MarketType.BJ),  # 北证 A 股
            ("873001", MarketType.BJ),  # 北证 A 股
            ("920123", MarketType.BJ),  # 北证 A 股
            # 北交所（老三板）
            ("400001", MarketType.BJ),
            ("420001", MarketType.BJ),
            ("430001", MarketType.BJ),
            # 沪基金
            ("510300", MarketType.SH),  # 沪深 300 ETF
            ("511010", MarketType.SH),  # 国债 ETF
        ],
    )
    def test_correct_market_mapping(self, code: str, expected: MarketType) -> None:
        assert detect_market(code) == expected

    @pytest.mark.parametrize(
        "invalid_code",
        [
            "",
            "abc",
            "x",  # 1 字符
            "xxxxx",  # 全字母
            "60A519",  # 混合
        ],
    )
    def test_invalid_code_returns_unknown(self, invalid_code: str) -> None:
        assert detect_market(invalid_code) == MarketType.UNKNOWN

    def test_bj_market_handled_correctly(self) -> None:
        """回归测试：原 efinance/tushare adapter 漏了 83/87/88 开头的北交所股票。"""
        # 这些都是真实的北交所股票
        assert detect_market("830799") == MarketType.BJ  # 艾融软件
        assert detect_market("871245") == MarketType.BJ
        assert detect_market("873001") == MarketType.BJ

    def test_chinext_recognized_as_sz(self) -> None:
        """创业板 (30xxxx) 是深市，不是独立的 MarketType。"""
        assert detect_market("300750") == MarketType.SZ
        assert detect_market("301236") == MarketType.SZ

    def test_star_market_recognized_as_sh(self) -> None:
        """科创板 (688xxx) 是沪市。"""
        assert detect_market("688981") == MarketType.SH

    def test_does_not_crash_on_garbage(self) -> None:
        """鲁棒性测试。"""
        assert detect_market("60A519") == MarketType.UNKNOWN
        # 非字符串类型（None 等）应安全返回 UNKNOWN 而不抛异常
        assert detect_market(None) == MarketType.UNKNOWN  # type: ignore[arg-type]
        assert detect_market(123) == MarketType.UNKNOWN  # type: ignore[arg-type]
