"""个股基本面数据接口（东财 push2 直连）。

获取 PE / PB / PS / ROE / 毛利率 / 净利率 / 市值 / 所属行业等指标，
补充行情数据无法覆盖的"质地"维度。
"""

from __future__ import annotations

import logging
from typing import Any

import requests

_log = logging.getLogger(__name__)

_STOCK_GET_URL = "http://push2.eastmoney.com/api/qt/stock/get"

# 东财字段 → 基本面指标
# f9: 动态市盈率(PE), f23: 市净率(PB), f37: 市销率(PS),
# f100: 所属行业, f116: 总市值, f117: 流通市值,
# f162: ROE(净资产收益率), f163: 毛利率, f167: 净利率
# f14: 股票名称
_FIELDS = "f9,f23,f37,f100,f116,f117,f162,f163,f167,f14"

_REQUEST_TIMEOUT = 10


def _make_secid(code: str) -> str:
    """根据股票代码生成东财 secid。

    6xx 开头 → 上交所 (1.{code})，其余 → 深交所 (0.{code})。
    """
    if code.startswith("6"):
        return f"1.{code}"
    return f"0.{code}"


def get_fundamentals(code: str) -> dict[str, Any]:
    """获取个股基本面指标。

    Args:
        code: 股票代码，如 "600519"、"000001"

    Returns:
        dict 含 code, name, pe, pb, ps, roe, gross_margin, net_margin,
        total_market_cap, circulating_market_cap, industry。
        请求失败时各指标为 None / 空字符串。
    """
    secid = _make_secid(code)
    try:
        r = requests.get(
            _STOCK_GET_URL,
            params={
                "secid": secid,
                "fields": _FIELDS,
                "fltt": "2",
                "invt": "2",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = (r.json().get("data")) or {}
    except Exception as e:
        _log.warning("get_fundamentals(%s) failed: %s", code, e)
        return {
            "code": code,
            "name": "",
            "pe": None,
            "pb": None,
            "ps": None,
            "roe": None,
            "gross_margin": None,
            "net_margin": None,
            "total_market_cap": None,
            "circulating_market_cap": None,
            "industry": "",
        }

    return {
        "code": code,
        "name": str(data.get("f14") or data.get("name") or ""),
        "pe": _to_float(data.get("f9")),
        "pb": _to_float(data.get("f23")),
        "ps": _to_float(data.get("f37")),
        "roe": _to_float(data.get("f162")),
        "gross_margin": _to_float(data.get("f163")),
        "net_margin": _to_float(data.get("f167")),
        "total_market_cap": _to_float(data.get("f116")),
        "circulating_market_cap": _to_float(data.get("f117")),
        "industry": str(data.get("f100") or ""),
    }


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
