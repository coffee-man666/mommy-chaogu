"""个股基本面数据接口（东财 push2 直连）。

获取 PE / PB / PS / ROE / 毛利率 / 净利率 / 市值 / 所属行业等指标，
补充行情数据无法覆盖的"质地"维度。数值字段一律 Decimal（含市值金额），
工具层序列化时再转 float。
"""

from __future__ import annotations

import logging
from decimal import Decimal
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


def _empty_fundamentals(code: str, reason: str) -> dict[str, Any]:
    """构造"取数失败"的载荷。

    关键点：必须带 ``ok: False`` + ``error``。早先这里只返回各字段为 None 的
    空壳，下游（LLM / check_earnings_catalyst）无法区分"这家公司的 ROE 就是拿不到"
    和"数据源挂了"，会把工具失败当成事实读。agent-start.md 明确要求
    "事实、工具结果和模型推断保持可区分"——这个标记是兑现该契约的最小单位。
    """
    return {
        "ok": False,
        "error": reason,
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


def get_fundamentals(code: str) -> dict[str, Any]:
    """获取个股基本面指标。

    Args:
        code: 股票代码，如 "600519"、"000001"

    Returns:
        成功时 dict 含 ``ok: True`` 及 code, name, pe, pb, ps, roe, gross_margin,
        net_margin, total_market_cap, circulating_market_cap, industry。
        失败时返回 ``_empty_fundamentals``：``ok=False`` + ``error`` 说明原因，
        其余字段为 None / 空字符串。调用方**必须**检查 ``ok``，不得把 None
        当成"该公司没有该指标"。
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
        return _empty_fundamentals(code, f"基本面数据源不可用：{e}")

    if not data:
        _log.warning("get_fundamentals(%s) returned empty data block", code)
        return _empty_fundamentals(code, "基本面数据源返回空数据")

    return {
        "ok": True,
        "code": code,
        "name": str(data.get("f14") or data.get("name") or ""),
        "pe": _to_dec(data.get("f9")),
        "pb": _to_dec(data.get("f23")),
        "ps": _to_dec(data.get("f37")),
        "roe": _to_dec(data.get("f162")),
        "gross_margin": _to_dec(data.get("f163")),
        "net_margin": _to_dec(data.get("f167")),
        "total_market_cap": _to_dec(data.get("f116")),
        "circulating_market_cap": _to_dec(data.get("f117")),
        "industry": str(data.get("f100") or ""),
    }


def _to_dec(v: Any) -> Decimal | None:
    """安全转 Decimal（金额/比率统一 Decimal，失败返回 None）。"""
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None
