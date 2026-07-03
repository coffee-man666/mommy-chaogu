"""news_api 单测：Mock requests 测试三个数据接口。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from mommy_chaogu.market_data.news_api import (
    get_announcements,
    get_longhuban,
    search_news,
)


class TestSearchNews:
    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_news_list(self, mock_get: MagicMock) -> None:
        # 东财 JSONP 格式
        jsonp_data = {
            "result": {
                "cmsArticleWebOld": {
                    "list": [
                        {
                            "title": "创新药板块大涨",
                            "url": "https://example.com/1",
                            "date": "2026-07-01",
                            "mediaName": "财联社",
                            "content": "创新药板块今日爆发...",
                        },
                    ]
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.text = f"jQuery({json.dumps(jsonp_data)})"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        items = search_news("创新药", limit=5)
        assert len(items) >= 1
        assert "创新药" in items[0]["title"]
        assert items[0]["source"] == "财联社"

    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_empty_on_failure(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network error")
        items = search_news("test")
        assert items == []

    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_strips_em_tags(self, mock_get: MagicMock) -> None:
        jsonp_data = {
            "result": {
                "cmsArticleWebOld": {
                    "list": [
                        {
                            "title": "<em>创新药</em>大涨",
                            "url": "",
                            "date": "",
                            "mediaName": "",
                            "content": "",
                        },
                    ]
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.text = f"jQuery({json.dumps(jsonp_data)})"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        items = search_news("创新药")
        assert "<em>" not in items[0]["title"]


class TestGetAnnouncements:
    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_announcement_list(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "list": [
                    {
                        "title": "贵州茅台:关于xxx的公告",
                        "notice_date": "2026-06-22",
                        "art_code": "123456",
                        "columns": {"announcement_type_name": "公告"},
                    },
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        items = get_announcements("600519", limit=5)
        assert len(items) >= 1
        # title should strip the "贵州茅台:" prefix
        assert items[0]["title"] == "关于xxx的公告"
        assert items[0]["date"] == "2026-06-22"

    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_empty_on_failure(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network error")
        assert get_announcements("600519") == []


class TestGetLonghuban:
    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_longhuban_list(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "success": True,
            "result": {
                "data": [
                    {
                        "SECURITY_CODE": "600519",
                        "SECURITY_NAME_ABBR": "贵州茅台",
                        "TRADE_DATE": "2026-07-01",
                        "CHANGE_RATE": 3.25,
                        "EXPLAIN": "日涨幅偏离值达7%",
                        "NET_AMOUNT": 500000000,
                        "RANK": 1,
                    },
                ]
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        items = get_longhuban(date="2026-07-01", limit=5)
        assert len(items) >= 1
        assert items[0]["code"] == "600519"
        assert items[0]["name"] == "贵州茅台"
        assert items[0]["change_rate"] == 3.25

    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_empty_on_failure(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network error")
        assert get_longhuban() == []

    @patch("mommy_chaogu.market_data.news_api.requests.get")
    def test_returns_empty_on_success_false(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": False}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        assert get_longhuban() == []
