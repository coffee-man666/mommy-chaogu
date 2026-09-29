"""股票名称 → 代码搜索（东财 suggest 优先，新浪 suggest 兜底）。

agent 工具层此前没有任何"名称→代码"解析：get_quote 只收代码，
用户说"看看比亚迪"时 LLM 只能硬传中文名——名称解析完全依赖
efinance get_latest_quote 的隐式副作用，efinance 失败即整链失败
（tencent 兜底按代码首字符猜前缀，对中文名必然失配）。

本模块补上这一层：
- 东财 suggest（searchapi.eastmoney.com）：网页搜索框同款，名称/代码联想，
  中文覆盖最好；
- 新浪 suggest（suggest3.sinajs.cn）：**全拼支持**（"maotai"→贵州茅台），
  东财结果为空或失联时兜底。

两个源都只保留适配链支持的 A 股（6 位数字）+ 美股（纯字母），
港股/期货/债券/板块过滤掉。行情适配链（efinance/tencent/massive/yahoo）
都不具备名称解析能力，故放在 market_data 下与其并列。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

_log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 5

# 东财 MktNum：0/1 = 深A/沪A，105/106/107 = 纳斯达克/纽交所/美交所。
_A_SHARE_MKTS = {"0", "1"}
_US_MKTS = {"105", "106", "107"}

# 新浪 suggest type：11 = A 股（沪深合并），41 = 美股。
_SINA_A_SHARE_TYPE = "11"
_SINA_US_TYPE = "41"

_US_CODE_RE = re.compile(r"^[A-Z]+$")  # 纯字母：排除 AAPL22 这类债券代码
_A_CODE_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class StockSearchHit:
    """单条搜索命中。

    Attributes:
        code: 适配链可直接使用的代码（A 股 6 位数字 / 美股字母）。
        name: 证券名称（中文简名）。
        market: "A股" 或 "US"。
    """

    code: str
    name: str
    market: str


def search_stocks_by_name(query: str, limit: int = 8) -> list[StockSearchHit]:
    """按名称 / 拼音 / 代码片段搜索 A 股 + 美股。

    Args:
        query: 搜索词，如 "比亚迪"、"茅台"、"maotai"、"苹果"。
        limit: 最多返回条数。

    Returns:
        命中列表（名称完全一致优先，其次前缀、包含；同级 A 股优先）。
        两个源都失败返回空列表，不抛异常。
    """
    query = query.strip()
    if not query:
        return []
    hits = _search_eastmoney(query, limit)
    if not hits:
        # 东财不支持全拼（"maotai" 为空）；新浪兜底，顺带覆盖东财失联。
        hits = _search_sina(query, limit)
    return hits[:limit]


def _search_eastmoney(query: str, limit: int) -> list[StockSearchHit]:
    try:
        r = requests.get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={"input": query, "type": "14", "count": str(max(limit * 3, 20))},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        table = r.json().get("QuotationCodeTable") or {}
        data = table.get("Data")
        raw = data if isinstance(data, list) else []
    except Exception as e:
        _log.warning("eastmoney suggest(%s) failed: %s", query, e)
        return []
    hits = [h for item in raw if (h := _em_to_hit(item)) is not None]
    return _rank(hits, query)


def _search_sina(query: str, limit: int) -> list[StockSearchHit]:
    try:
        # 无 Referer 头会被拒；返回体是 GBK 编码的 JS 变量赋值。
        r = requests.get(
            "https://suggest3.sinajs.cn/suggest/",
            params={"type": "", "key": query, "name": "suggestdata"},
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        r.encoding = "gbk"
        body = r.text
    except Exception as e:
        _log.warning("sina suggest(%s) failed: %s", query, e)
        return []
    # var suggestdata="贵州茅台,11,600519,...;...";  → 字段: 名称,type,代码,完整代码,...
    quoted = body.split('"')
    if len(quoted) < 2:
        return []
    hits: list[StockSearchHit] = []
    for item in quoted[1].split(";"):
        fields = item.split(",")
        if len(fields) < 4:
            continue
        h = _sina_to_hit(fields)
        if h is not None:
            hits.append(h)
    return _rank(hits, query)


def _em_to_hit(item: dict[str, Any]) -> StockSearchHit | None:
    """东财原始条目 → StockSearchHit；市场/代码不支持的条目返回 None。"""
    code = str(item.get("Code") or "").strip()
    name = str(item.get("Name") or "").strip()
    mkt = str(item.get("MktNum") or "")
    if not code or not name:
        return None
    if mkt in _A_SHARE_MKTS and _A_CODE_RE.match(code):
        return StockSearchHit(code=code, name=name, market="A股")
    if mkt in _US_MKTS and _US_CODE_RE.match(code):
        return StockSearchHit(code=code, name=name, market="US")
    return None


def _sina_to_hit(fields: list[str]) -> StockSearchHit | None:
    """新浪条目字段（[名称,type,代码,完整代码,...]）→ StockSearchHit。"""
    if len(fields) < 3:
        return None
    name, sec_type, code = fields[0].strip(), fields[1].strip(), fields[2].strip()
    if not name or not code:
        return None
    if sec_type == _SINA_A_SHARE_TYPE and _A_CODE_RE.match(code):
        return StockSearchHit(code=code, name=name, market="A股")
    if sec_type == _SINA_US_TYPE:
        upper = code.upper()
        if _US_CODE_RE.match(upper):
            return StockSearchHit(code=upper, name=name, market="US")
    return None


def _rank(hits: list[StockSearchHit], query: str) -> list[StockSearchHit]:
    """相关性排序：完全一致 < 名称前缀 < 名称包含 < 其他（A 股优先）。"""
    q = query.casefold()

    def key(h: StockSearchHit) -> tuple[int, int]:
        n = h.name.casefold()
        if n == q:
            name_rank = 0
        elif n.startswith(q):
            name_rank = 1
        elif q in n:
            name_rank = 2
        else:
            name_rank = 3
        return name_rank, 0 if h.market == "A股" else 1

    return sorted(hits, key=key)
