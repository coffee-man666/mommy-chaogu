"""MassiveAdapter: Massive / Polygon REST API 美股行情数据源。

薄包装 MassiveClient，将 JSON 响应映射到业务模型 (Quote / Bar)。
MassiveClient 负责 HTTP + 分页，MassiveAdapter 负责 Protocol 实现。

设计要点：
- 仅处理美股代码（字母开头如 AAPL/MSFT），A 股代码直接返回 None/[]
- 无 API key 时所有方法返回空值，不影响 FallbackAdapter 链中的其他源
- 异常不抛出，失败返回 None/[]
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from mommy_chaogu.market_data.massive_client import MassiveClient
from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    MarketType,
    Money,
    Quote,
    QuoteType,
)

_log = logging.getLogger(__name__)

# interval → (multiplier, timespan) 映射，Polygon aggs 端点用
_INTERVAL_MAP: dict[BarInterval, tuple[int, str]] = {
    BarInterval.M1: (1, "minute"),
    BarInterval.M5: (5, "minute"),
    BarInterval.M15: (15, "minute"),
    BarInterval.M30: (30, "minute"),
    BarInterval.M60: (1, "hour"),
    BarInterval.D1: (1, "day"),
    BarInterval.W1: (1, "week"),
    BarInterval.M: (1, "month"),
}


# ---------- 内部工具 ----------


def _is_us_code(code: str) -> bool:
    """检测是否为美股代码：字母开头（AAPL / MSFT / BRK.B 等）。"""
    return bool(code) and code[0].isalpha()


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


def _ts_from_ms(ms: Any) -> datetime | None:
    """Unix 毫秒时间戳 → datetime（UTC，带 tzinfo）。"""
    if ms is None:
        return None
    try:
        val = int(ms)
    except (ValueError, TypeError):
        return None
    return datetime.fromtimestamp(val / 1000, tz=UTC)


class MassiveAdapter:
    """Massive / Polygon REST API 美股行情数据源。

    特点：
    - 仅处理美股代码（字母开头），A 股代码快速返回 None/[]
    - 无 API key 时所有方法返回空值，health_check 返回 False
    - 支持：实时报价（snapshot）、K线（aggs）
    - 不支持：盘口（需 Developer+）、Tick（需 Developer+）、资金流/板块（A 股特有）
    """

    name = "massive"

    def __init__(self, api_key: str | None = None, timeout: float = 15.0) -> None:
        self._client = MassiveClient(api_key=api_key, timeout=timeout)
        self._enabled = self._client.enabled

    # ---------- 内部：JSON → 业务模型 ----------

    def _snapshot_to_quote(
        self,
        snap: dict[str, Any],
        name: str | None = None,
    ) -> Quote | None:
        """单个 snapshot 结果 → Quote dataclass。"""
        results = snap.get("results") or snap  # 兼容 {results: {...}} 和直接 {...}
        if not results or not isinstance(results, dict):
            return None

        ticker = str(results.get("ticker") or "")
        if not ticker:
            return None

        day = results.get("day") or {}
        prev_day = results.get("prevDay") or {}

        price = _dec(day.get("c"))
        if price is None or price <= 0:
            return None

        open_p = _dec(day.get("o")) or Decimal("0")
        high = _dec(day.get("h")) or Decimal("0")
        low = _dec(day.get("l")) or Decimal("0")
        prev_close = _dec(prev_day.get("c")) or Decimal("0")
        volume = _int(day.get("v"))

        change = price - prev_close if prev_close > 0 else Decimal("0")
        if prev_close > 0:
            change_pct = (change / prev_close * Decimal("100")).quantize(Decimal("0.01"))
        else:
            change_pct = Decimal("0")

        vwap = _dec(day.get("vw"))
        if vwap and vwap > 0:
            turnover = Money(vwap * Decimal(volume), "USD")
        else:
            turnover = Money(Decimal("0"), "USD")

        market_cap = _dec(results.get("market_cap"))
        ts = _ts_from_ms(results.get("updated")) or datetime.now(tz=UTC)
        raw_name = results.get("name")
        company_name = name or (str(raw_name) if raw_name else "")

        return Quote(
            code=ticker,
            name=company_name or ticker,
            market=MarketType.US,
            quote_type=QuoteType.STOCK,
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
            total_market_cap=Money(market_cap, "USD") if market_cap is not None else None,
            circulating_market_cap=None,
            timestamp=ts,
        )

    def _agg_to_bars(
        self,
        data: dict[str, Any],
        code: str,
        interval: BarInterval,
        adjustment: AdjustmentType,
    ) -> list[Bar]:
        """Polygon aggregates 响应 → list[Bar]。"""
        results = data.get("results")
        if not results or not isinstance(results, list):
            return []

        bars: list[Bar] = []
        for row in results:
            ts = _ts_from_ms(row.get("t"))
            if ts is None:
                continue
            close = _dec(row.get("c"))
            if close is None:
                continue
            open_p = _dec(row.get("o")) or Decimal("0")
            vwap = _dec(row.get("vw"))
            vol = _int(row.get("v"))
            if vwap and vwap > 0:
                turnover = Money(vwap * Decimal(vol), "USD")
            else:
                turnover = Money(Decimal("0"), "USD")
            bars.append(
                Bar(
                    code=code,
                    name=code,
                    interval=interval,
                    adjustment=adjustment,
                    timestamp=ts,
                    open=open_p,
                    high=_dec(row.get("h")) or Decimal("0"),
                    low=_dec(row.get("l")) or Decimal("0"),
                    close=close,
                    volume=vol,
                    turnover=turnover,
                )
            )

        bars.sort(key=lambda b: b.timestamp)
        return bars

    def _quote_from_prev_close(
        self,
        code: str,
        prev_data: dict[str, Any],
        details: dict[str, Any] | None,
    ) -> Quote | None:
        """从 previous_close + ticker_details 组装 Quote（Basic tier fallback）。

        previous_close 响应：
        {
          "results": [{"T":"AAPL","v":75000000,"o":309.58,"h":311.8,"l":302.56,"c":303.42,...}]
        }
        """
        results = prev_data.get("results")
        if not results or not isinstance(results, list) or not results:
            return None
        row = results[0]
        close = _dec(row.get("c"))
        if close is None:
            return None

        name = code
        market_cap = None
        if details and "results" in details:
            d = details["results"]
            name = str(d.get("name") or code)
            market_cap = _dec(d.get("market_cap"))

        open_p = _dec(row.get("o")) or Decimal("0")
        high = _dec(row.get("h")) or Decimal("0")
        low = _dec(row.get("l")) or Decimal("0")
        volume = _int(row.get("v"))
        vwap = _dec(row.get("vw"))
        if vwap and vwap > 0:
            turnover = Money(vwap * Decimal(volume), "USD")
        else:
            turnover = Money(Decimal("0"), "USD")

        ts = _ts_from_ms(row.get("t")) or datetime.now(tz=UTC)

        # previous_close 没有前日收盘，用 close 作为 price 和 prev_close
        return Quote(
            code=code,
            name=name,
            market=MarketType.US,
            quote_type=QuoteType.STOCK,
            price=close,
            open=open_p,
            high=high,
            low=low,
            prev_close=close,
            change=Decimal("0"),
            change_pct=Decimal("0"),
            volume=volume,
            turnover=turnover,
            turnover_rate=None,
            volume_ratio=None,
            pe_dynamic=None,
            total_market_cap=Money(market_cap, "USD") if market_cap is not None else None,
            circulating_market_cap=None,
            timestamp=ts,
        )

    # ---------- MarketDataAdapter Protocol ----------

    def get_quote(self, code: str) -> Quote | None:
        if not self._enabled or not _is_us_code(code):
            return None
        code = code.upper()

        # 优先用 snapshot（Starter+ tier）
        snap = self._client.get_snapshot(code)
        if snap is not None:
            quote = self._snapshot_to_quote(snap)
            if quote is not None:
                # snapshot 没带名称（name == ticker）→ 查 ticker details 补全
                if quote.name == quote.code:
                    details = self._client.get_ticker_details(code)
                    resolved_name = code
                    if details and "results" in details:
                        resolved_name = str(details["results"].get("name") or code)
                    quote = Quote(
                        code=quote.code,
                        name=resolved_name,
                        market=quote.market,
                        quote_type=quote.quote_type,
                        price=quote.price,
                        open=quote.open,
                        high=quote.high,
                        low=quote.low,
                        prev_close=quote.prev_close,
                        change=quote.change,
                        change_pct=quote.change_pct,
                        volume=quote.volume,
                        turnover=quote.turnover,
                        turnover_rate=quote.turnover_rate,
                        volume_ratio=quote.volume_ratio,
                        pe_dynamic=quote.pe_dynamic,
                        total_market_cap=quote.total_market_cap,
                        circulating_market_cap=quote.circulating_market_cap,
                        timestamp=quote.timestamp,
                    )
                return quote

        # Basic tier fallback: previous_close + ticker_details
        prev_data = self._client.get_previous_close(code)
        if prev_data is None:
            return None
        details = self._client.get_ticker_details(code)
        return self._quote_from_prev_close(code, prev_data, details)

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        if not self._enabled:
            return []
        us_codes = [c.upper() for c in codes if _is_us_code(c)]
        seen: set[str] = set()
        us_codes = [c for c in us_codes if not (c in seen or seen.add(c))]
        if not us_codes:
            return []

        out: list[Quote] = []

        # 优先尝试 batch snapshot（Starter+ tier）
        got_from_snapshot: set[str] = set()
        for i in range(0, len(us_codes), 250):
            batch = us_codes[i : i + 250]
            data = self._client.get_snapshots_batch(batch)
            if data is None:
                continue
            results = data.get("results")
            if not results or not isinstance(results, list):
                continue
            for snap in results:
                quote = self._snapshot_to_quote(snap)
                if quote is not None:
                    out.append(quote)
                    got_from_snapshot.add(quote.code)

        # Basic tier fallback: 对 snapshot 没拿到的代码逐个查 previous_close
        missing = [c for c in us_codes if c not in got_from_snapshot]
        for code in missing:
            prev_data = self._client.get_previous_close(code)
            if prev_data is None:
                continue
            details = self._client.get_ticker_details(code)
            quote = self._quote_from_prev_close(code, prev_data, details)
            if quote is not None:
                out.append(quote)

        return out

    def list_market_quotes(self) -> list[Quote]:
        """美股全市场快照（数千只），暂不实现。"""
        return []

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        if not self._enabled or not _is_us_code(code):
            return []
        code = code.upper()

        mult, timespan = _INTERVAL_MAP.get(interval, (1, "day"))

        end_d = end or date.today()
        if start is None:
            if interval == BarInterval.D1:
                years = max(1, (limit or 500) // 250 + 1)
                start_d = end_d - timedelta(days=years * 366)
            elif interval == BarInterval.W1:
                start_d = end_d - timedelta(weeks=max(52, (limit or 200) + 4))
            elif interval == BarInterval.M:
                start_d = end_d - timedelta(days=max(24, (limit or 60) + 2) * 31)
            else:
                days = max(5, (limit or 240) // 240 + 5)
                start_d = end_d - timedelta(days=days)
        else:
            start_d = start

        adjusted = adjustment != AdjustmentType.NONE
        data = self._client.get_aggs(
            ticker=code,
            multiplier=mult,
            timespan=timespan,
            from_=start_d.isoformat(),
            to=end_d.isoformat(),
            adjusted=adjusted,
            sort="asc",
            limit=min(limit or 50000, 50000),
        )
        if data is None:
            return []

        bars = self._agg_to_bars(data, code, interval, adjustment)
        if limit is not None and len(bars) > limit:
            bars = bars[-limit:]
        return bars

    def get_ticks(self, code, limit=None):
        """美股 Tick 需 Developer+ 套餐，暂不支持。"""
        return []

    def get_order_book(self, code: str):
        """美股 NBBO 需 Advanced+ 套餐，暂不支持。"""
        return None

    def get_today_money_flow(self, code):
        """资金流是 A 股特有概念，美股无对应数据。"""
        return []

    def get_history_money_flow(self, code, days=30):
        return []

    def get_belonging_boards(self, code):
        """板块是 A 股特有概念，美股无对应数据。"""
        return []

    def health_check(self) -> bool:
        """检查 Massive API 是否可用。"""
        if not self._enabled:
            return False
        data = self._client.get_market_status()
        return data is not None and "market" in (data or {})

    # ---------- 非 Protocol 扩展方法（给 agent tools 调用） ----------

    def get_ticker_details(self, code: str) -> dict[str, Any] | None:
        """公司详情（名称/CIK/FIGI/行业/市值/描述）。"""
        if not self._enabled or not _is_us_code(code):
            return None
        return self._client.get_ticker_details(code)

    def get_dividends(self, code: str, limit: int = 50) -> list[dict[str, Any]]:
        """分红历史。"""
        if not self._enabled or not _is_us_code(code):
            return []
        data = self._client.get_dividends(code, limit=limit)
        if data is None:
            return []
        return data.get("results", [])  # type: ignore[return-value]

    def get_splits(self, code: str, limit: int = 50) -> list[dict[str, Any]]:
        """拆股历史。"""
        if not self._enabled or not _is_us_code(code):
            return []
        data = self._client.get_splits(code, limit=limit)
        if data is None:
            return []
        return data.get("results", [])  # type: ignore[return-value]

    def get_short_interest(self, code: str) -> list[dict[str, Any]]:
        """空头持仓（FINRA 双周数据）。"""
        if not self._enabled or not _is_us_code(code):
            return []
        data = self._client.get_short_interest(code)
        if data is None:
            return []
        return data.get("results", [])  # type: ignore[return-value]

    def get_float(self, code: str) -> dict[str, Any] | None:
        """流通股数。"""
        if not self._enabled or not _is_us_code(code):
            return None
        data = self._client.get_float(code)
        if data is None:
            return None
        results = data.get("results")
        # Polygon returns results as a list of dicts
        if isinstance(results, list) and results:
            return results[0]  # type: ignore[no-any-return]
        if isinstance(results, dict):
            return results
        return None

    def get_news(self, code: str, limit: int = 10) -> list[dict[str, Any]]:
        """个股新闻。"""
        if not self._enabled or not _is_us_code(code):
            return []
        data = self._client.get_news(code, limit=limit)
        if data is None:
            return []
        return data.get("results", [])  # type: ignore[return-value]

    def get_technical_indicator(
        self,
        code: str,
        indicator: str,
        timespan: str = "day",
        window: int = 50,
        series_type: str = "close",
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """技术指标（SMA / EMA / RSI / MACD）。"""
        if not self._enabled or not _is_us_code(code):
            return []
        indicator = indicator.lower()
        if indicator == "macd":
            data = self._client.get_macd(code, timespan=timespan, limit=limit)
        elif indicator == "sma":
            data = self._client.get_sma(code, timespan=timespan, window=window, series_type=series_type, limit=limit)
        elif indicator == "ema":
            data = self._client.get_ema(code, timespan=timespan, window=window, series_type=series_type, limit=limit)
        elif indicator == "rsi":
            data = self._client.get_rsi(code, timespan=timespan, window=window, series_type=series_type, limit=limit)
        else:
            return []
        if data is None:
            return []
        # Polygon SMA/EMA/RSI: {"results": {"values": [...]}}
        # Polygon MACD: {"results": {"values": [...]}}
        # But some indicators return flat list: {"results": [{"timestamp":..,"value":..}]}
        results = data.get("results")
        if isinstance(results, dict):
            vals = results.get("values", [])
            if isinstance(vals, list):
                return vals  # type: ignore[return-value]
        if isinstance(results, list):
            return results  # type: ignore[return-value]
        return []

    def get_market_status(self) -> dict[str, Any] | None:
        """当前美股市场状态。"""
        return self._client.get_market_status()

    def get_gainers_losers(self, direction: str = "gainers") -> list[dict[str, Any]]:
        """涨跌幅 TOP20。"""
        if not self._enabled:
            return []
        data = self._client.get_gainers_losers(direction)
        if data is None:
            return []
        return data.get("tickers", [])  # type: ignore[return-value]
