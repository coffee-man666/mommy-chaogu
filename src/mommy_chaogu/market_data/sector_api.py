"""板块成分股行情（东财 push2 直连）。

rankings.py 拉的是板块自身的涨跌幅排行，
本模块拉的是某个板块内部的成分股行情。

使用场景：
    - agent 问"创新药板块成分股有哪些"
    - Web 路由 /api/market/sector-stocks
"""
from __future__ import annotations

import logging
from typing import Any

import requests

_log = logging.getLogger(__name__)

_CLIST_URL = "http://push2.eastmoney.com/api/qt/clist/get"

# 涨跌幅、成交额、主力净流入、换手率、量比、PE、总市值
_DEFAULT_FIELDS = (
    "f12,f14,f2,f3,f4,f5,f6,f7,f8,f10,f9,f20,f116,f62"
)


def fetch_sector_stocks(
    board_code: str,
    sort_by: str = "change_pct",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """获取板块成分股行情。

    Args:
        board_code: 东财板块代码，如 "BK1106"（创新药）、"BK0475"（半导体）
        sort_by: 排序字段，支持 change_pct / main_net / turnover / amount
        limit: 最多返回 N 只

    Returns:
        list[dict]，每个 dict 包含：
        - code, name, price, change_pct, change, volume, amount,
        - turnover_rate, volume_ratio, pe, total_market_cap, main_net
    """
    fid_map = {
        "change_pct": "f3",
        "main_net": "f62",
        "turnover": "f8",
        "amount": "f6",
    }
    fid = fid_map.get(sort_by, "f3")

    fs = f"b:{board_code}"
    items: list[dict[str, Any]] = []

    for pn in (1, 2):
        try:
            r = requests.get(
                _CLIST_URL,
                params={
                    "pn": str(pn),
                    "pz": "100",
                    "po": "1",
                    "np": "1",
                    "fltt": "2",
                    "invt": "2",
                    "fs": fs,
                    "fields": _DEFAULT_FIELDS,
                    "fid": fid,
                },
                timeout=10,
            ).json()
        except Exception as e:
            _log.warning("fetch_sector_stocks %s page %d failed: %s", board_code, pn, e)
            break

        data = (r.get("data") or {}).get("diff") or []
        total = (r.get("data") or {}).get("total", 0)
        if not data:
            break

        for d in data:
            code = d.get("f12")
            name = d.get("f14")
            if not code:
                continue
            items.append({
                "code": str(code),
                "name": str(name),
                "price": _to_float(d.get("f2")),
                "change_pct": _to_float(d.get("f3")),
                "change": _to_float(d.get("f4")),
                "volume": int(d.get("f5", 0) or 0),
                "amount": float(d.get("f6", 0) or 0),
                "turnover_rate": _to_float(d.get("f8")),
                "volume_ratio": _to_float(d.get("f10")),
                "pe": _to_float(d.get("f9")),
                "total_market_cap": float(d.get("f20", 0) or 0),
                "main_net": float(d.get("f62", 0) or 0),
            })

        if len(items) >= limit or len(items) >= total:
            break

    return items[:limit]


def search_sector(keyword: str) -> list[dict[str, str]]:
    """搜索板块代码（用东财搜索接口）。

    Returns:
        [{"code": "BK1106", "name": "创新药", "secid": "90.BK1106"}, ...]
    """
    try:
        r = requests.get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={"input": keyword, "type": "14", "count": "10"},
            timeout=8,
        ).json()
    except Exception as e:
        _log.warning("search_sector %s failed: %s", keyword, e)
        return []

    out: list[dict[str, str]] = []
    for item in (r.get("QuotationCodeTable") or {}).get("Data") or []:
        if item.get("SecurityType") == "9":  # 板块
            out.append({
                "code": str(item["Code"]),
                "name": str(item["Name"]),
                "secid": str(item["QuoteID"]),
            })
    return out


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0
