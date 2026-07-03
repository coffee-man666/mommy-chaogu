"""get_fundamentals 单测：Mock requests 测试基本面数据接口 + 工具集成。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.market_data.fundamentals_api import get_fundamentals


class TestGetFundamentals:
    @patch("mommy_chaogu.market_data.fundamentals_api.requests.get")
    def test_returns_fundamentals_dict(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "f9": 25.5,
                "f23": 8.2,
                "f37": 10.1,
                "f100": "白酒",
                "f116": 2100000000000,
                "f117": 2100000000000,
                "f162": 30.5,
                "f163": 91.5,
                "f167": 52.3,
                "f14": "贵州茅台",
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_fundamentals("600519")
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"
        assert result["pe"] == 25.5
        assert result["pb"] == 8.2
        assert result["ps"] == 10.1
        assert result["roe"] == 30.5
        assert result["gross_margin"] == 91.5
        assert result["net_margin"] == 52.3
        assert result["total_market_cap"] == 2100000000000.0
        assert result["circulating_market_cap"] == 2100000000000.0
        assert result["industry"] == "白酒"

    @patch("mommy_chaogu.market_data.fundamentals_api.requests.get")
    def test_secid_sh_vs_sz(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"f14": "测试"}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # 6xx → 上交所 (1.{code})
        get_fundamentals("600519")
        assert mock_get.call_args[1]["params"]["secid"] == "1.600519"

        # 0xx → 深交所 (0.{code})
        get_fundamentals("000001")
        assert mock_get.call_args[1]["params"]["secid"] == "0.000001"

    @patch("mommy_chaogu.market_data.fundamentals_api.requests.get")
    def test_returns_nulls_on_failure(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network error")

        result = get_fundamentals("600519")
        assert result["code"] == "600519"
        assert result["pe"] is None
        assert result["name"] == ""
        assert result["industry"] == ""


class TestFundamentalsTool:
    def test_tool_returns_json(self) -> None:
        ctx = ToolContext(adapter=MagicMock())
        registry = ToolRegistry(ctx)

        with patch("mommy_chaogu.market_data.fundamentals_api.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "data": {
                    "f9": 30.0,
                    "f23": 5.0,
                    "f37": 8.0,
                    "f100": "银行",
                    "f116": 300000000000,
                    "f117": 280000000000,
                    "f162": 12.0,
                    "f163": 45.0,
                    "f167": 30.0,
                    "f14": "平安银行",
                }
            }
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = registry.call("get_fundamentals", {"code": "000001"})
            data = json.loads(result)
            assert data["code"] == "000001"
            assert data["name"] == "平安银行"
            assert data["pe"] == 30.0
            assert data["industry"] == "银行"
