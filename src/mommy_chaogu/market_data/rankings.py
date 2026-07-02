"""市场排行数据服务。

直接从东方财富接口拉取：
- 大盘指数（上证/深证/创业板/沪深300）
- 板块涨跌幅排行
- 个股涨跌幅榜

不污染 Adapter 层（这些不是标准行情数据），路由层直接调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests

_log = logging.getLogger(__name__)

# 大盘核心指数（secid, 名称, 代码）
INDEX_LIST: list[tuple[str, str, str]] = [
    ("1.000001", "上证指数", "sh000001"),
    ("0.399001", "深证成指", "sz399001"),
    ("0.399006", "创业板指", "sz399006"),
    ("1.000300", "沪深300", "sh000300"),
    ("1.000688", "科创50", "sh000688"),
    ("1.000016", "上证50", "sh000016"),
]

# 东财板块 fs 参数
# m:90+t:2 是行业板块（申万），m:90+t:1 是概念板块
SECTOR_FS = "m:90+t:2"


@dataclass(frozen=True)
class IndexQuote:
    code: str
    name: str
    secid: str
    price: Decimal
    change_pct: Decimal
    prev_close: Decimal


def fetch_indexes() -> list[IndexQuote]:
    """拉取大盘核心指数。"""
    out: list[IndexQuote] = []
    url = "http://push2.eastmoney.com/api/qt/stock/get"
    for secid, name, code in INDEX_LIST:
        try:
            r = requests.get(
                url,
                params={
                    "secid": secid,
                    "fields": "f43,f60,f170",
                    "invt": "2",
                    "fltt": "2",
                },
                timeout=5,
            ).json()
            data = r.get("data") or {}
            price = _to_dec(data.get("f43"))
            prev = _to_dec(data.get("f60"))
            pct = _to_dec(data.get("f170"))
            if price is None or pct is None:
                continue
            out.append(
                IndexQuote(
                    code=code,
                    name=name,
                    secid=secid,
                    price=price,
                    change_pct=pct,
                    prev_close=prev or Decimal("0"),
                )
            )
        except Exception as e:
            _log.warning("fetch index %s failed: %s", secid, e)
            continue
    return out


def fetch_sector_ranking(limit: int = 30) -> list[dict[str, Any]]:
    """板块涨幅榜（申万行业 + 概念）。"""
    items: list[dict[str, Any]] = []
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    for fs in [SECTOR_FS, "m:90+t:1"]:
        try:
            r = requests.get(
                url,
                params={
                    "pn": "1",
                    "pz": str(limit * 2),
                    "po": "1",
                    "np": "1",
                    "fltt": "2",
                    "invt": "2",
                    "fs": fs,
                    "fields": "f12,f14,f3,f2,f20",
                    "fid": "f3",
                },
                timeout=8,
            ).json()
        except Exception as e:
            _log.warning("fetch sectors failed: %s", e)
            continue
        data = (r.get("data") or {}).get("diff") or []
        for d in data:
            code = d.get("f12")
            name = d.get("f14")
            pct = d.get("f3")
            if not code or pct is None:
                continue
            # 去重（同 code 同 name 只保留第一个）
            if any(i["code"] == code for i in items):
                continue
            items.append(
                {
                    "code": code,
                    "name": name,
                    "change_pct": Decimal(str(pct)),
                    "price": _to_dec(d.get("f2")),
                }
            )
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break

    # 按涨幅排序
    items.sort(key=lambda x: float(x["change_pct"]), reverse=True)
    return items[:limit]


def _to_dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None
