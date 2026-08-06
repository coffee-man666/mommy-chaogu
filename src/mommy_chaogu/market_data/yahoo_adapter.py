"""YahooAdapter: Yahoo Finance chart API 美股行情数据源（备用）。

薄包装 YahooClient，将 JSON 响应映射到业务模型 (Quote / Bar)。

设计要点：
- 仅处理美股代码：`^` 前缀（指数/利率/VIX，如 ^GSPC / ^VIX / ^TNX）或字母开头（个股）
- A 股代码快速返回 None/[]（零网络开销），不影响 fallback 链继续走 Efinance/Tencent
- 无需 API key；异常不抛出，失败返回 None/[]
- 定位：Massive 的备用源，补齐 Massive 缺失的指数/利率/VIX 数据
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    Quote,
    QuoteType,
    Tick,
)
from mommy_chaogu.market_data.yahoo_client import YahooClient

_log = logging.getLogger(__name__)

# BarInterval → Yahoo chart interval 参数
_INTERVAL_MAP: dict[BarInterval, str] = {
    BarInterval.M1: "1m",
    BarInterval.M5: "5m",
    BarInterval.M15: "15m",
    BarInterval.M30: "30m",
    BarInterval.M60: "1h",
    BarInterval.D1: "1d",
    BarInterval.W1: "1wk",
    BarInterval.M: "1mo",
}

# BarInterval → Yahoo chart range 参数（受 Yahoo 限制：1m 仅支持 1d/5d，分钟线最远 60d）
_RANGE_MAP: dict[BarInterval, str] = {
    BarInterval.M1: "1d",
    BarInterval.M5: "5d",
    BarInterval.M15: "1mo",
    BarInterval.M30: "1mo",
    BarInterval.M60: "1mo",
    BarInterval.D1: "2y",
    BarInterval.W1: "5y",
    BarInterval.M: "10y",
}


def _is_us_ticker(code: str) -> bool:
    """检测是否为美股代码：`^` 前缀（指数/利率/VIX）或字母开头（个股）。"""
    return bool(code) and (code.startswith("^") or code[0].isalpha())


def _dec(v: Any) -> Decimal | None:
    """安全转 Decimal。"""
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int(v: Any) -> int:
    """安全转 int。"""
    if v is None:
        return 0
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0


def _ts_from_epoch(ts: Any) -> datetime | None:
    """Unix 秒时间戳 → datetime（UTC，带 tzinfo）。"""
    if ts is None:
        return None
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _get_at(d: dict[str, Any], key: str, i: int) -> Any:
    """从数组型字段取第 i 个元素；非 list 或缺位返回 None。"""
    val = d.get(key)
    if isinstance(val, list) and i < len(val):
        return val[i]
    return None


class YahooAdapter:
    """Yahoo Finance 美股行情数据源（备用）。

    特点：
    - 仅处理美股代码（`^` 前缀或字母开头），A 股代码快速返回 None/[]
    - 无需 API key；任何异常返回 None/[]，不抛异常
    - 支持：实时报价、K 线（含复权）
    - 不支持：盘口 / Tick / 资金流 / 板块（美股无对应概念或未实现）
    """

    name = "yahoo"

    def __init__(self, timeout: float = 15.0, client: YahooClient | None = None) -> None:
        self._client = client or YahooClient(timeout=timeout)

    # ---------- 内部：JSON → 业务模型 ----------

    @staticmethod
    def _meta(data: dict[str, Any] | None) -> dict[str, Any] | None:
        """chart 响应 → meta dict；无有效 result 返回 None。"""
        if not data:
            return None
        results = (data.get("chart") or {}).get("result")
        if not isinstance(results, list) or not results:
            return None
        meta = results[0].get("meta")
        return meta if isinstance(meta, dict) else None

    @staticmethod
    def _bars(data: dict[str, Any] | None, *, adjusted: bool = True) -> list[dict[str, Any]]:
        """chart 响应 → OHLCV 行 [{t, o, h, l, c, v}]，跳过 close 缺失的行。

        adjusted=True 时用 indicators.adjclose 覆盖 close（复权）。
        """
        if not data:
            return []
        results = (data.get("chart") or {}).get("result")
        if not isinstance(results, list) or not results:
            return []
        result = results[0]
        timestamps = result.get("timestamp")
        if not isinstance(timestamps, list):
            return []
        indicators = result.get("indicators") or {}
        quotes = indicators.get("quote")
        if not isinstance(quotes, list) or not quotes:
            return []
        quote0 = quotes[0] or {}

        adj: dict[str, Any] | None = None
        if adjusted:
            adj_list = indicators.get("adjclose")
            if isinstance(adj_list, list) and adj_list:
                adj = adj_list[0] or {}

        rows: list[dict[str, Any]] = []
        for i, ts in enumerate(timestamps):
            close = _get_at(quote0, "close", i)
            if close is None:
                continue
            row: dict[str, Any] = {
                "t": ts,
                "o": _get_at(quote0, "open", i),
                "h": _get_at(quote0, "high", i),
                "l": _get_at(quote0, "low", i),
                "c": close,
                "v": _get_at(quote0, "volume", i) or 0,
            }
            if adj is not None:
                adjclose = _get_at(adj, "adjclose", i)
                if adjclose is not None:
                    row["c"] = adjclose
            rows.append(row)
        rows.sort(key=lambda r: r["t"])
        return rows

    # ---------- MarketDataAdapter Protocol ----------

    def get_quote(self, code: str) -> Quote | None:
        """拉取单只美股/指数当前实时报价。失败/无数据返回 None。"""
        if not _is_us_ticker(code):
            return None
        code = code.upper()
        data = self._client.get_chart(code, range="5d", interval="1d")
        meta = self._meta(data)
        if meta is None:
            return None
        price = _dec(meta.get("regularMarketPrice"))
        if price is None or price <= 0:
            return None

        bars = self._bars(data, adjusted=False)
        last = bars[-1] if bars else None
        if last is not None and len(bars) >= 2:
            prev_close = _dec(bars[-2]["c"])
        else:
            prev_close = _dec(meta.get("previousClose"))
        if prev_close is None or prev_close <= 0:
            prev_close = price

        if last is not None:
            open_p = _dec(last["o"]) or Decimal("0")
            high = _dec(last["h"]) or Decimal("0")
            low = _dec(last["l"]) or Decimal("0")
        else:
            open_p = high = low = Decimal("0")
        volume = _int(last["v"]) if last else _int(meta.get("regularMarketVolume"))

        change = price - prev_close if prev_close > 0 else Decimal("0")
        change_pct = Decimal("0")
        if prev_close > 0:
            change_pct = (change / prev_close * Decimal("100")).quantize(Decimal("0.01"))

        close_for_turnover = _dec(last["c"]) if last else price
        if volume > 0 and close_for_turnover is not None:
            turnover = Money(close_for_turnover * Decimal(volume), "USD")
        else:
            turnover = Money(Decimal("0"), "USD")

        raw_name = meta.get("longName") or meta.get("shortName")
        name = str(raw_name) if raw_name else code
        instrument = str(meta.get("instrumentType") or "")
        quote_type = QuoteType.INDEX if instrument.upper() == "INDEX" else QuoteType.STOCK
        ts = _ts_from_epoch(meta.get("regularMarketTime")) or datetime.now(tz=UTC)

        return Quote(
            code=code,
            name=name,
            market=MarketType.US,
            quote_type=quote_type,
            price=price,
            open=open_p,
            high=high,
            low=low,
            prev_close=prev_close,
            change=change,
            change_pct=change_pct,
            volume=volume,
            turnover=turnover,
            turnover_rate=None,
            volume_ratio=None,
            pe_dynamic=None,
            total_market_cap=None,
            circulating_market_cap=None,
            timestamp=ts,
        )

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量拉取美股/指数报价，按 code 去重，失败自动跳过。"""
        us_codes: list[str] = []
        seen: set[str] = set()
        for code in codes:
            code = code.upper()
            if _is_us_ticker(code) and code not in seen:
                seen.add(code)
                us_codes.append(code)
        out: list[Quote] = []
        for code in us_codes:
            quote = self.get_quote(code)
            if quote is not None:
                out.append(quote)
        return out

    def list_market_quotes(self) -> list[Quote]:
        """美股全市场快照，Yahoo chart 不提供，暂不实现。"""
        return []

    def get_order_book(self, code: str) -> OrderBook | None:
        """美股盘口，Yahoo chart 不提供。"""
        return None

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """拉取 K 线。start/end 为闭区间（按自然日），limit 截断取最后 N 根。"""
        if not _is_us_ticker(code):
            return []
        code = code.upper()
        yinterval = _INTERVAL_MAP.get(interval, "1d")
        yrng = _RANGE_MAP.get(interval, "1y")
        data = self._client.get_chart(code, range=yrng, interval=yinterval)
        rows = self._bars(data, adjusted=adjustment != AdjustmentType.NONE)
        if not rows:
            return []

        if start is not None:
            start_ts = _day_start_epoch(start)
            rows = [r for r in rows if r["t"] >= start_ts]
        if end is not None:
            end_ts = _day_end_epoch(end)
            rows = [r for r in rows if r["t"] <= end_ts]

        bars: list[Bar] = []
        for row in rows:
            close = _dec(row["c"])
            if close is None:
                continue
            ts = _ts_from_epoch(row["t"])
            if ts is None:
                continue
            volume = _int(row["v"])
            if volume > 0:
                turnover = Money(close * Decimal(volume), "USD")
            else:
                turnover = Money(Decimal("0"), "USD")
            bars.append(
                Bar(
                    code=code,
                    name=code,
                    interval=interval,
                    adjustment=adjustment,
                    timestamp=ts,
                    open=_dec(row["o"]) or Decimal("0"),
                    high=_dec(row["h"]) or Decimal("0"),
                    low=_dec(row["l"]) or Decimal("0"),
                    close=close,
                    volume=volume,
                    turnover=turnover,
                )
            )
        if limit is not None and len(bars) > limit:
            bars = bars[-limit:]
        return bars

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        """美股 Tick 需付费源，暂不支持。"""
        return []

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        """资金流是 A 股特有概念，美股无对应数据。"""
        return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        return []

    def get_belonging_boards(self, code: str) -> list[Board]:
        """板块是 A 股特有概念，美股无对应数据。"""
        return []

    def health_check(self) -> bool:
        """检查 Yahoo chart API 是否可用。"""
        return self._client.get_chart("^GSPC", range="1d", interval="1d") is not None


def _day_start_epoch(d: date) -> int:
    """日期 → UTC 当日 0 点的时间戳（秒）。"""
    return int(datetime.combine(d, datetime.min.time(), tzinfo=UTC).timestamp())


def _day_end_epoch(d: date) -> int:
    """日期 → UTC 当日 24 点的时间戳（秒）。"""
    return int(datetime.combine(d, datetime.max.time(), tzinfo=UTC).timestamp())
