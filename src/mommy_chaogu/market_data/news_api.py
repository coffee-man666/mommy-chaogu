"""新闻 / 公告 / 龙虎榜数据接口（东财直连）。

补充 agent 工具层缺失的文字信息维度——
行情数据只能告诉你"涨了多少"，新闻/公告/龙虎榜能告诉你"为什么"。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

_log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10


# ============================================================
# 新闻搜索
# ============================================================


def search_news(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    """搜索财经新闻。

    Args:
        keyword: 搜索关键字，如 "创新药"、"半导体政策"、"茅台"
        limit: 最多返回 N 条

    Returns:
        list[dict]: 每条含 title, url, source, date, summary
    """
    try:
        r = requests.get(
            "https://search-api-web.eastmoney.com/search/jsonp",
            params={
                "cb": "jQuery",
                "param": json.dumps(
                    {
                        "uid": "",
                        "keyword": keyword,
                        "type": ["cmsArticleWebOld"],
                        "client": "web",
                        "clientType": "web",
                        "clientVersion": "curr",
                        "param": {
                            "pageIndex": 1,
                            "pageSize": min(limit * 2, 20),
                            "preTag": "",
                            "postTag": "",
                        },
                    }
                ),
            },
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        # JSONP → 提取 JSON
        text = r.text
        match = re.search(r"jQuery\((.*)\)", text)
        if not match:
            return []
        data = json.loads(match.group(1))
        items = (data.get("result") or {}).get("cmsArticleWebOld", {}).get("list", [])

        out: list[dict[str, Any]] = []
        for item in items[:limit]:
            title = item.get("title", "").replace("<em>", "").replace("</em>", "")
            out.append(
                {
                    "title": title,
                    "url": item.get("url", ""),
                    "date": item.get("date", ""),
                    "source": item.get("mediaName", ""),
                    "summary": (item.get("content") or "")[:200],
                }
            )
        return out

    except Exception as e:
        _log.warning("search_news(%s) failed: %s", keyword, e)
        return []


# ============================================================
# 个股公告
# ============================================================


def get_announcements(code: str, limit: int = 10) -> list[dict[str, Any]]:
    """获取个股最新公告列表。

    Args:
        code: 股票代码，如 "600519"
        limit: 最多返回 N 条

    Returns:
        list[dict]: 每条含 title, date, ann_type, url
    """
    try:
        r = requests.get(
            "https://np-anotice-stock.eastmoney.com/api/security/ann",
            params={
                "sr": "-1",
                "page_size": str(limit),
                "page_index": "1",
                "ann_type": "A",
                "stock_list": code,
                "f_node": "0",
                "s_node": "0",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        items = (data.get("data") or {}).get("list", [])

        out: list[dict[str, Any]] = []
        for item in items[:limit]:
            title = item.get("title", "")
            # title 格式: "贵州茅台:关于xxx的公告"
            if ":" in title:
                title = title.split(":", 1)[1]
            art_code = item.get("art_code", "")
            out.append(
                {
                    "title": title,
                    "date": item.get("notice_date", ""),
                    "ann_type": item.get("columns", {}).get("announcement_type_name", ""),
                    "url": f"https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={art_code}"
                    if art_code
                    else "",
                }
            )
        return out

    except Exception as e:
        _log.warning("get_announcements(%s) failed: %s", code, e)
        return []


# ============================================================
# 龙虎榜
# ============================================================


def get_longhuban(date: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """获取龙虎榜数据。

    Args:
        date: 日期 YYYY-MM-DD（默认今天）
        limit: 最多返回 N 条

    Returns:
        list[dict]: 每条含 code, name, date, change_rate, reason, net_buy_amount
    """
    from datetime import datetime

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        r = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_DAILYBILLBOARD_DETAILS",
                "columns": "ALL",
                "source": "WEB",
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "pageSize": str(limit),
                "pageNumber": "1",
                "filter": f"(TRADE_DATE>='{date}')",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            _log.warning("longhuban API returned success=false")
            return []

        raw = (data.get("result") or {}).get("data", [])
        out: list[dict[str, Any]] = []
        for item in raw[:limit]:
            out.append(
                {
                    "code": str(item.get("SECURITY_CODE", "")),
                    "name": str(item.get("SECURITY_NAME_ABBR", "")),
                    "date": str(item.get("TRADE_DATE", ""))[:10],
                    "change_rate": float(item.get("CHANGE_RATE", 0) or 0),
                    "reason": str(item.get("EXPLAIN", "")),
                    "net_buy_amount": float(item.get("NET_AMOUNT", 0) or 0),
                    "rank": int(item.get("RANK", 0) or 0),
                }
            )
        return out

    except Exception as e:
        _log.warning("get_longhuban(%s) failed: %s", date, e)
        return []
