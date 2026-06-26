"""TencentAdapter: 腾讯财经行情数据源（qt.gtimg.cn）。

为什么用腾讯：
- 腾讯自己的数据源，**不是爬虫**，稳定可靠
- HTTP 接口简单直接，无需 token，无需登录
- push2 东财挂了的时候经常能通
- GBK 编码（要 decode）

接口：
- 实时报价：https://qt.gtimg.cn/q=sh600519,sz000001
  返回 v_sh600519="1~名称~代码~现价~昨收~今开~成交量(手)~外盘~内盘~买卖5档~...~88个字段"
- 5档盘口：买卖各 5 档直接嵌在实时报价里

K线/资金流/历史数据：腾讯公开接口没有 → 用父类默认实现返回空 list。
业务层用 FallbackAdapter 自动从东财拉这些数据。
"""
from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import requests

from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    OrderBook,
    OrderBookLevel,
    Quote,
    QuoteType,
)

_log = logging.getLogger(__name__)


# 腾讯接口前缀映射
_PREFIX_MAP = {
    "6": "sh",   # 上证
    "5": "sh",   # 沪基金
    "9": "sh",   # 上证 B 股
    "0": "sz",   # 深证
    "3": "sz",   # 创业板
    "1": "sz",   # 深基金
    "4": "bj",   # 北证
    "8": "bj",   # 北证 B 股
    "2": "sz",   # 深 B 股
}


def _detect_market(code: str) -> MarketType:
    if code.startswith(("60", "68", "9", "11", "13")):
        return MarketType.SH
    if code.startswith(("00", "30", "20")):
        return MarketType.SZ
    if code.startswith(("4", "8")):
        return MarketType.BJ
    return MarketType.UNKNOWN


def _detect_quote_type(code: str) -> QuoteType:
    """股票 / 基金 / 指数 粗略判断（腾讯都能拉）。"""
    if code.startswith(("15", "16", "18", "50", "51")):
        return QuoteType.FUND
    if code.startswith(("0", "399")):
        return QuoteType.INDEX
    return QuoteType.STOCK


def _dec(v: str | None) -> Decimal | None:
    """安全转 Decimal。"""
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _ts_from_str(s: str) -> datetime | None:
    """解析 '20260626161408' → datetime。"""
    if not s or len(s) < 14:
        return None
    try:
        dt = datetime.strptime(s, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=UTC).astimezone()
    except ValueError:
        return None


class TencentAdapter:
    """腾讯财经行情数据源（qt.gtimg.cn）。

    特点：
    - **完全免费**，无需注册，无需 token
    - 单接口一次可拉 80 只股票
    - 稳定（腾讯自己的数据源）
    - 数据字段：现价/涨跌/今开/昨收/最高/最低/成交量/成交额/PE/换手/量比/5档盘口
    - **不支持**：K线、资金流、板块（腾讯公开接口没这些）

    适合做 efinance 的 fallback 兜底。
    """

    name = "tencent"

    URL = "https://qt.gtimg.cn/q={codes}"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://stockapp.finance.qq.com/",
        })
        self._last_call_ts: float = 0.0  # 简单节流，避免打爆腾讯

    # ---------- 内部：HTTP 请求 ----------

    def _fetch_raw(self, codes: list[str]) -> dict[str, list[str]]:
        """拉一批代码的原始 88 字段数据，返回 {code: fields}。"""
        if not codes:
            return {}

        # 构造 URL：sh600519,sz000001,...
        prefixes = [_PREFIX_MAP.get(c[0], "sz") for c in codes]
        url_codes = ",".join(f"{p}{c}" for p, c in zip(prefixes, codes, strict=False))
        url = self.URL.format(codes=url_codes)

        try:
            resp = self._session.get(url, timeout=self.timeout)
            resp.encoding = "gbk"
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            _log.warning("tencent fetch failed: %s", e)
            return {}

        result: dict[str, list[str]] = {}
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            try:
                key, content = line.split("=\"", 1)
                content = content.rstrip(";\n\"")
            except ValueError:
                continue
            # key 格式: v_sh600519
            if not key.startswith("v_"):
                continue
            var_part = key[2:]  # "sh600519"，如 sh600519
            code = var_part[2:]
            fields = content.split("~")
            if len(fields) < 50:
                # 字段不足，可能是基金或指数，尝试当作 fallback
                continue
            result[code] = fields
        return result

    # ---------- 内部：解析 ----------

    def _parse_quote(self, code: str, fields: list[str]) -> Quote:
        """88 字段 → Quote dataclass。

        字段位置（按腾讯 v_sh 接口）：
          1:   未知
          2:   名称
          3:   代码
          4:   现价
          5:   昨收
          6:   今开
          7:   成交量(手)
          8:   外盘(手)
          9:   内盘(手)
          10-29: 买卖5档（买1价, 买1量, ... 卖1价, 卖1量, ...）
          30:  时间戳 (YYYYMMDDHHMMSS)
          31:  涨跌额
          32:  涨跌幅 %
          33:  最高
          34:  最低
          35:  "现价/成交量(手)/成交额(元)" 复合字段
          36:  成交量(手) 重复
          37:  成交额(万元)
          38:  换手率 %
          39:  PE
          40:  "" 空
          41:  最高 重复
          42:  最低 重复
          43:  振幅 %
          44:  流通市值(亿)
          45:  总市值(亿)
          46:  PB
          47:  涨停价
          48:  跌停价
          49:  量比
        """
        def f(idx: int) -> str:
            return fields[idx] if idx < len(fields) else ""

        name = f(1)
        price = _dec(f(3)) or Decimal("0")
        prev_close = _dec(f(4)) or Decimal("0")
        open_p = _dec(f(5)) or Decimal("0")
        high = _dec(f(33)) or Decimal("0")
        low = _dec(f(34)) or Decimal("0")
        change = _dec(f(31)) or Decimal("0")
        change_pct = _dec(f(32)) or Decimal("0")

        # 成交量(手) * 100 = 股
        try:
            volume = int(float(f(6)) * 100)
        except (ValueError, TypeError):
            volume = 0

        # 成交额：字段 37 是万元，转元
        turnover_yuan = _dec(f(37))
        turnover = Money((turnover_yuan or Decimal("0")) * 10000, "CNY")

        turnover_rate = _dec(f(38))
        pe = _dec(f(39))

        # 市值字段 44/45 是亿，转元
        circulating_cap = _dec(f(44))
        if circulating_cap is not None:
            circulating_cap = circulating_cap * Decimal("100000000")
        total_cap = _dec(f(45))
        if total_cap is not None:
            total_cap = total_cap * Decimal("100000000")

        volume_ratio = _dec(f(49))

        ts = _ts_from_str(f(30)) or datetime.now()

        return Quote(
            code=code,
            name=name,
            market=_detect_market(code),
            quote_type=_detect_quote_type(code),
            price=price,
            open=open_p,
            high=high,
            low=low,
            prev_close=prev_close,
            change=change,
            change_pct=change_pct,
            volume=volume,
            turnover=turnover,
            turnover_rate=turnover_rate,
            volume_ratio=volume_ratio,
            pe_dynamic=pe,
            total_market_cap=Money(total_cap, "CNY") if total_cap is not None else None,
            circulating_market_cap=Money(circulating_cap, "CNY") if circulating_cap is not None else None,
            timestamp=ts,
            quote_id=None,
        )

    def _parse_order_book(self, code: str, fields: list[str]) -> OrderBook | None:
        """买卖5档（直接嵌在 fields 里）。"""
        bids: list[OrderBookLevel] = []
        asks: list[OrderBookLevel] = []
        # 买1-5: 价格在 [10, 12, 14, 16, 18]，量在 [11, 13, 15, 17, 19]
        for i in range(5):
            bid_price = _dec(fields[9 + i * 2]) if 9 + i * 2 < len(fields) else None
            bid_vol_str = fields[10 + i * 2] if 10 + i * 2 < len(fields) else ""
            if bid_price and bid_price > 0:
                bids.append(OrderBookLevel(
                    price=bid_price,
                    volume=int(float(bid_vol_str)) if bid_vol_str else 0,
                ))
        # 卖1-5: 价格在 [20, 22, 24, 26, 28]，量在 [21, 23, 25, 27, 29]
        for i in range(5):
            ask_price = _dec(fields[19 + i * 2]) if 19 + i * 2 < len(fields) else None
            ask_vol_str = fields[20 + i * 2] if 20 + i * 2 < len(fields) else ""
            if ask_price and ask_price > 0:
                asks.append(OrderBookLevel(
                    price=ask_price,
                    volume=int(float(ask_vol_str)) if ask_vol_str else 0,
                ))

        if not bids and not asks:
            return None

        ts = _ts_from_str(fields[29] if len(fields) > 29 else "") or datetime.now()
        return OrderBook(
            code=code,
            name=fields[1] if len(fields) > 1 else "",
            timestamp=ts,
            bids=tuple(bids),
            asks=tuple(asks),
            last_price=_dec(fields[3]) if len(fields) > 3 else None,
        )

    # ---------- MarketDataAdapter 实现 ----------

    def get_quote(self, code: str) -> Quote | None:
        results = self._fetch_raw([code])
        fields = results.get(code)
        if fields is None:
            return None
        try:
            return self._parse_quote(code, fields)
        except Exception as e:
            _log.warning("tencent parse_quote(%s) failed: %s", code, e)
            return None

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量拉取（一次最多 80 只）。"""
        out: list[Quote] = []
        # 分批（腾讯单次最多 80）
        for i in range(0, len(codes), 80):
            batch = codes[i:i + 80]
            results = self._fetch_raw(batch)
            for code in batch:
                fields = results.get(code)
                if fields is None:
                    continue
                with contextlib.suppress(Exception):
                    out.append(self._parse_quote(code, fields))
        return out

    def list_market_quotes(self) -> list[Quote]:
        """腾讯公开接口没有"全市场"，返回空 list。

        业务层应该配合 EfinanceAdapter（用 list_market_quotes），
        或者用 FallbackAdapter 让 EfinanceAdapter 优先。
        """
        return []

    def get_order_book(self, code: str) -> OrderBook | None:
        results = self._fetch_raw([code])
        fields = results.get(code)
        if fields is None:
            return None
        with contextlib.suppress(Exception):
            return self._parse_order_book(code, fields)
        return None

    # ---------- 不支持的方法（返回空 / 抛 NotImplementedError） ----------

    def get_bars(self, code, interval=None, adjustment=None, **kw):
        return []

    def get_ticks(self, code, limit=None):
        return []

    def get_today_money_flow(self, code):
        return []

    def get_history_money_flow(self, code, days=30):
        return []

    def get_belonging_boards(self, code):
        return []

    def health_check(self) -> bool:
        """健康检查：拉一次贵州茅台，能解析就算 OK。"""
        try:
            q = self.get_quote("600519")
            return q is not None and q.price > 0
        except Exception:
            return False
