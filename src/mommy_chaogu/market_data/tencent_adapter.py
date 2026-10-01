"""TencentAdapter: 腾讯财经行情数据源（qt.gtimg.cn / ifzq.gtimg.cn）。

为什么用腾讯：
- 腾讯自己的数据源，**不是爬虫**，稳定可靠
- HTTP 接口简单直接，无需 token，无需登录
- push2 东财挂了的时候经常能通
- GBK 编码（要 decode）

接口：
- 实时报价：https://qt.gtimg.cn/q=sh600519,sz000001
  返回 v_sh600519="1~名称~代码~现价~昨收~今开~成交量(手)~外盘~内盘~买卖5档~...~88个字段"
- 5档盘口：买卖各 5 档直接嵌在实时报价里
- 分钟 K 线（阶段六备源）：https://ifzq.gtimg.cn/appstock/app/kline/mkline
  ?param=sh600519,m5,,800 —— 单请求约 800 根（m5 ≈ 17 交易日，m1 ≈ 3-4
  交易日），start 锚点可向前翻页；每根 [时间标签, 开, 收, 高, 低, 量(手), ...]，
  无每根成交额。

仍不支持（返回空 list，业务层用 FallbackAdapter 走东财）：日/周/月 K、
资金流、板块。
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import requests

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    OrderBookLevel,
    Quote,
    QuoteType,
    Tick,
)

_log = logging.getLogger(__name__)

# 腾讯接口返回的墙时间为北京时间
_TZ_BEIJING = ZoneInfo("Asia/Shanghai")


# 腾讯接口前缀映射
_PREFIX_MAP = {
    "6": "sh",  # 上证
    "5": "sh",  # 沪基金
    "9": "sh",  # 上证 B 股
    "0": "sz",  # 深证
    "3": "sz",  # 创业板
    "1": "sz",  # 深基金
    "4": "bj",  # 北证
    "8": "bj",  # 北证 B 股
    "2": "sz",  # 深 B 股
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
    """解析 '20260626161408'（北京墙时间）→ aware UTC datetime。"""
    if not s or len(s) < 14:
        return None
    try:
        dt = datetime.strptime(s, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=_TZ_BEIJING).astimezone(UTC)
    except ValueError:
        return None


# ---------- 分钟 K 线备源（ifzq.gtimg.cn mkline，阶段六）----------

# mkline 周期参数（仅分钟级；日/周/月线仍走东财主源）
_MKLINE_MAP: dict[BarInterval, str] = {
    BarInterval.M1: "m1",
    BarInterval.M5: "m5",
    BarInterval.M15: "m15",
    BarInterval.M30: "m30",
    BarInterval.M60: "m60",
}

_MKLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"

# 单请求根数上限（2026-09-30 实测：m5 请求 800 得 800，全天 48 根、
# 时间标签 0935..1500；m1 ≈ 3-4 交易日存档；m5 存档约 2026-07 起）。
_MKLINE_MAX_COUNT = 800

# start 早于单页覆盖时的向前翻页上限（锚点是排他上界，逐页前移；
# 有界防失控——分钟深度本就只承诺「当日 + 近期」）。
_MKLINE_MAX_PAGES = 4


def _mkline_ts(label: str, minutes: int) -> datetime | None:
    """mkline 时间标签（北京墙时间，**周期末**）→ **周期初** aware UTC。

    腾讯 mkline 标签打在周期末（m5 全天 0935..1500），efinance 分钟 K 打在
    周期初（0930..1455）——这里统一减一个周期，混源约定与 efinance 一致
    （docs/plans/trading-method-landing.md 阶段六任务 2）。
    """
    if not label or len(label) < 12:
        return None
    try:
        end = datetime.strptime(label[:12], "%Y%m%d%H%M").replace(tzinfo=_TZ_BEIJING)
    except ValueError:
        return None
    return (end - timedelta(minutes=minutes)).astimezone(UTC)


class TencentAdapter:
    """腾讯财经行情数据源（qt.gtimg.cn 实时 / ifzq.gtimg.cn 分钟 K）。

    特点：
    - **完全免费**，无需注册，无需 token
    - 单接口一次可拉 80 只股票
    - 稳定（腾讯自己的数据源）
    - 数据字段：现价/涨跌/今开/昨收/最高/最低/成交量/成交额/PE/换手/量比/5档盘口
    - 分钟 K（1m/5m/15m/30m/60m）经 ifzq mkline 备源可得：东财 push2his
      不可达时的分钟级兜底（阶段六）；不复权、无每根成交额
    - **不支持**：日/周/月 K、资金流、板块（这些仍靠 FallbackAdapter 走东财）

    适合做 efinance 的 fallback 兜底。
    """

    name = "tencent"

    URL = "https://qt.gtimg.cn/q={codes}"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://stockapp.finance.qq.com/",
            }
        )
        # 拉新频率控制由缓存层节流窗口统一承担（cache/config.py），本层不做节流

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
                key, content = line.split('="', 1)
                content = content.rstrip(';\n"')
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

        ts = _ts_from_str(f(30)) or datetime.now(UTC)

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
            circulating_market_cap=Money(circulating_cap, "CNY")
            if circulating_cap is not None
            else None,
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
                bids.append(
                    OrderBookLevel(
                        price=bid_price,
                        volume=int(float(bid_vol_str)) if bid_vol_str else 0,
                    )
                )
        # 卖1-5: 价格在 [20, 22, 24, 26, 28]，量在 [21, 23, 25, 27, 29]
        for i in range(5):
            ask_price = _dec(fields[19 + i * 2]) if 19 + i * 2 < len(fields) else None
            ask_vol_str = fields[20 + i * 2] if 20 + i * 2 < len(fields) else ""
            if ask_price and ask_price > 0:
                asks.append(
                    OrderBookLevel(
                        price=ask_price,
                        volume=int(float(ask_vol_str)) if ask_vol_str else 0,
                    )
                )

        if not bids and not asks:
            return None

        # 时间戳与行情解析同一字段（索引 30），之前误读 29（空字段）
        ts = _ts_from_str(fields[30] if len(fields) > 30 else "") or datetime.now(UTC)
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
            batch = codes[i : i + 80]
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

    # ---------- 分钟 K 线（ifzq.gtimg.cn mkline 备源，阶段六）----------

    def _mkline_symbol(self, code: str) -> str:
        """6 位裸代码 → 带市场前缀的腾讯符号（sh600519）；已带前缀原样透传。"""
        if code[:2] in ("sh", "sz", "bj"):
            return code
        prefix = _PREFIX_MAP.get(code[0], "sz") if code else "sz"
        return f"{prefix}{code}"

    def _fetch_mkline_node(self, symbol: str, mk: str, anchor: str, count: int) -> dict[str, Any]:
        """拉一页 mkline，返回该符号的 data 节点（含 mk 序列与 qt 名称）。"""
        url = f"{_MKLINE_URL}?param={symbol},{mk},{anchor},{count}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            _log.warning("tencent mkline fetch(%s) failed: %s", symbol, e)
            return {}
        if not isinstance(payload, dict) or payload.get("code") != 0:
            return {}
        data = payload.get("data")
        if not isinstance(data, dict):
            return {}
        node = data.get(symbol)
        return node if isinstance(node, dict) else {}

    def get_bars(
        self,
        code: str,
        interval: BarInterval | None = None,
        adjustment: AdjustmentType | None = None,
        start: Any = None,
        end: Any = None,
        limit: int | None = None,
        **kw: Any,
    ) -> list[Bar]:
        """分钟 K 线（mkline 备源）。日/周/月线不支持 → 返回 []（东财承担）。

        - ``adjustment``：mkline 无复权参数，数据为不复权，Bar.adjustment
          如实标 ``none``（不复权价）——与东财前复权缓存分键存放，不互窜。
        - 成交量单位手 ×100 → 股；**无每根成交额**，turnover 记 0（VWAP 等
          派生指标只能成交量加权的典型价近似，见 services/intraday_service）。
        - 时间标签从周期末转为周期初（与 efinance 统一，见 _mkline_ts）。
        - ``end`` 直接映射为 mkline 锚点（排他上界）；``start`` 早于单页
          覆盖时以页内最早标签为新锚点向前翻页（上限 _MKLINE_MAX_PAGES）。
        """
        if interval is None:
            return []
        mk = _MKLINE_MAP.get(interval)
        if mk is None:
            return []
        minutes = int(mk[1:])
        symbol = self._mkline_symbol(code)

        start_d = start.date() if isinstance(start, datetime) else start
        end_d = end.date() if isinstance(end, datetime) else end
        anchor = f"{end_d:%Y%m%d}235959" if end_d is not None else ""
        first_count = (
            max(1, min(int(limit), _MKLINE_MAX_COUNT)) if limit is not None else _MKLINE_MAX_COUNT
        )

        rows: list[list[Any]] = []
        seen: set[str] = set()
        for page in range(_MKLINE_MAX_PAGES):
            count = first_count if page == 0 else _MKLINE_MAX_COUNT
            node = self._fetch_mkline_node(symbol, mk, anchor, count)
            raw_rows = node.get(mk)
            if not isinstance(raw_rows, list) or not raw_rows:
                break
            page_rows = [
                r for r in raw_rows if isinstance(r, list) and len(r) >= 6 and str(r[0]) not in seen
            ]
            for r in page_rows:
                seen.add(str(r[0]))
            rows.extend(page_rows)
            oldest = str(page_rows[0][0]) if page_rows else ""
            if not oldest or start_d is None:
                break
            try:
                oldest_d = datetime.strptime(oldest[:8], "%Y%m%d").date()
            except ValueError:
                break
            if oldest_d <= start_d:
                break
            anchor = oldest  # 排他上界：下一页从本页最早一根之前继续

        name = self._mkline_name(node, symbol) if rows else ""
        bars: list[Bar] = []
        for row in sorted(rows, key=lambda r: str(r[0])):
            ts = _mkline_ts(str(row[0]), minutes)
            if ts is None:
                continue
            bar_date = ts.astimezone(_TZ_BEIJING).date()
            if start_d is not None and bar_date < start_d:
                continue
            if end_d is not None and bar_date > end_d:
                continue
            try:
                volume = int(float(row[5]) * 100)  # 手 → 股
            except (TypeError, ValueError):
                volume = 0
            bars.append(
                Bar(
                    code=code,
                    name=name,
                    interval=interval,
                    adjustment=AdjustmentType.NONE,
                    timestamp=ts,
                    open=_dec(str(row[1])) or Decimal("0"),
                    high=_dec(str(row[3])) or Decimal("0"),
                    low=_dec(str(row[4])) or Decimal("0"),
                    close=_dec(str(row[2])) or Decimal("0"),
                    volume=volume,
                    turnover=Money(Decimal("0"), "CNY"),
                    change_pct=None,
                    turnover_rate=None,
                    amplitude=None,
                )
            )
        if limit is not None:
            bars = bars[-limit:]
        return bars

    @staticmethod
    def _mkline_name(node: dict[str, Any], symbol: str) -> str:
        """从 mkline 响应内嵌 qt 块取证券名称（取不到给空串）。"""
        qt = node.get("qt")
        if isinstance(qt, dict):
            fields = qt.get(symbol)
            if isinstance(fields, (list, tuple)) and len(fields) > 1:
                return str(fields[1])
        return ""

    # ---------- 其他不支持的方法（返回空） ----------

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        return []

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        return []

    def get_belonging_boards(self, code: str) -> list[Board]:
        return []

    def health_check(self) -> bool:
        """健康检查：拉一次贵州茅台，能解析就算 OK。"""
        try:
            q = self.get_quote("600519")
            return q is not None and q.price > 0
        except Exception:
            return False
