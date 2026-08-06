"""Massive / Polygon REST API 客户端。

纯 HTTP 客户端，不做业务模型映射。每个方法返回原始 JSON (dict/list) 或 None。
覆盖所有 Basic+ 免费 tier 端点（约 21 个方法）。

参考文档：/Users/hanyan/Cursor/_context/massive_source_of_truth.md
- Base URL: https://api.massive.com（兼容 https://api.polygon.io）
- 认证：Bearer token header
- 分页：cursor-based，response.next_url 指向下一页
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

_log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.massive.com"
DEFAULT_TIMEOUT = 15.0


def _resolve_api_key(api_key: str | None) -> str | None:
    """读取 API key：参数 > MASSIVE_API_KEY > POLYGON_API_KEY。"""
    if api_key:
        return api_key
    return os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")


class MassiveClient:
    """Massive / Polygon REST API 客户端。

    用法：
        client = MassiveClient()               # 从环境变量读 key
        client = MassiveClient(api_key="xxx")  # 显式传 key
        snap = client.get_snapshot("AAPL")      # → dict | None
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._key = _resolve_api_key(api_key)
        self.enabled = bool(self._key)
        self._session = requests.Session()
        if self.enabled:
            self._session.headers.update(
                {
                    "Authorization": f"Bearer {self._key}",
                    "Accept": "application/json",
                }
            )

    # ---------- 内部：HTTP ----------

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """GET 请求，返回 JSON dict。失败返回 None。"""
        if not self.enabled:
            return None
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except requests.HTTPError as e:
            _log.warning(
                "massive GET %s HTTP %s",
                path,
                e.response.status_code if e.response else "?",
            )
        except Exception as e:
            _log.warning("massive GET %s failed: %s: %s", path, type(e).__name__, e)
        return None

    def _get_paginated(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        max_results: int = 1000,
        results_key: str = "results",
    ) -> list[dict[str, Any]]:
        """GET 带自动翻页。返回聚合后的 results 列表。"""
        all_results: list[dict[str, Any]] = []
        data = self._get(path, params)
        if data is None:
            return all_results
        batch = data.get(results_key)
        if isinstance(batch, list):
            all_results.extend(batch)
        # 翻页
        next_url = data.get("next_url")
        while next_url and len(all_results) < max_results:
            # next_url 是完整 URL，需要追加 apiKey
            if self._key and "apiKey" not in next_url:
                sep = "&" if "?" in next_url else "?"
                next_url = f"{next_url}{sep}apiKey={self._key}"
            try:
                resp = self._session.get(next_url, timeout=self.timeout)
                resp.raise_for_status()
                page = resp.json()
            except Exception as e:
                _log.warning("massive pagination failed: %s", e)
                break
            batch = page.get(results_key)
            if isinstance(batch, list):
                all_results.extend(batch)
            next_url = page.get("next_url")
        return all_results[:max_results]

    # ================================================================
    # Tickers / Reference
    # ================================================================

    def get_ticker_details(self, ticker: str) -> dict[str, Any] | None:
        """GET /v3/reference/tickers/{ticker} — 公司详情。"""
        return self._get(f"/v3/reference/tickers/{ticker.upper()}")

    def get_ticker_types(self) -> dict[str, Any] | None:
        """GET /v3/reference/tickers/types — 证券类型枚举。"""
        return self._get("/v3/reference/tickers/types")

    def list_tickers(
        self,
        market: str = "stocks",
        type: str | None = None,
        limit: int = 100,
        sort: str = "ticker",
    ) -> list[dict[str, Any]]:
        """GET /v3/reference/tickers — 全量 ticker 列表（带翻页）。"""
        params: dict[str, Any] = {
            "market": market,
            "active": "true",
            "limit": min(limit, 1000),
            "sort": sort,
        }
        if type:
            params["type"] = type
        return self._get_paginated("/v3/reference/tickers", params, max_results=limit)

    def get_related_companies(self, ticker: str) -> dict[str, Any] | None:
        """GET /v1/related-companies/{ticker} — 相关公司。"""
        return self._get(f"/v1/related-companies/{ticker.upper()}")

    # ================================================================
    # Snapshots
    # ================================================================

    def get_snapshot(self, ticker: str) -> dict[str, Any] | None:
        """GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker} — 单股快照。"""
        return self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}")

    def get_snapshots_batch(self, tickers: list[str]) -> dict[str, Any] | None:
        """GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers= — 批量快照（≤250）。"""
        batch = tickers[:250]
        params = {"tickers": ",".join(t.upper() for t in batch)}
        return self._get("/v2/snapshot/locale/us/markets/stocks/tickers", params)

    def get_gainers_losers(self, direction: str = "gainers") -> dict[str, Any] | None:
        """GET /v2/snapshot/locale/us/markets/stocks/{direction} — 涨跌幅 TOP20。"""
        if direction not in ("gainers", "losers"):
            direction = "gainers"
        return self._get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")

    # ================================================================
    # Aggregate Bars / OHLC
    # ================================================================

    def get_aggs(
        self,
        ticker: str,
        multiplier: int = 1,
        timespan: str = "day",
        from_: str | None = None,
        to: str | None = None,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
    ) -> dict[str, Any] | None:
        """GET /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}"""
        ticker = ticker.upper()
        from_ = from_ or "1970-01-01"
        to = to or "2100-01-01"
        path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_}/{to}"
        params = {
            "adjusted": "true" if adjusted else "false",
            "sort": sort,
            "limit": min(limit, 50000),
        }
        return self._get(path, params)

    def get_grouped_daily(self, date: str) -> dict[str, Any] | None:
        """GET /v2/aggs/grouped/locale/us/market/stocks/{date} — 全市场单日 OHLC。"""
        return self._get(f"/v2/aggs/grouped/locale/us/market/stocks/{date}")

    def get_daily_open_close(self, ticker: str, date: str) -> dict[str, Any] | None:
        """GET /v1/open-close/{ticker}/{date} — 单股单日 O/C（含盘前盘后）。"""
        return self._get(f"/v1/open-close/{ticker.upper()}/{date}")

    def get_previous_close(self, ticker: str) -> dict[str, Any] | None:
        """GET /v2/aggs/ticker/{ticker}/prev — 前日 OHLC。"""
        return self._get(f"/v2/aggs/ticker/{ticker.upper()}/prev")

    # ================================================================
    # Technical Indicators
    # ================================================================

    def get_sma(
        self,
        ticker: str,
        timespan: str = "day",
        window: int = 50,
        series_type: str = "close",
        limit: int = 5000,
    ) -> dict[str, Any] | None:
        """GET /v1/indicators/sma/{ticker}"""
        return self._indicator("sma", ticker, timespan, window, series_type, limit)

    def get_ema(
        self,
        ticker: str,
        timespan: str = "day",
        window: int = 50,
        series_type: str = "close",
        limit: int = 5000,
    ) -> dict[str, Any] | None:
        """GET /v1/indicators/ema/{ticker}"""
        return self._indicator("ema", ticker, timespan, window, series_type, limit)

    def get_rsi(
        self,
        ticker: str,
        timespan: str = "day",
        window: int = 14,
        series_type: str = "close",
        limit: int = 5000,
    ) -> dict[str, Any] | None:
        """GET /v1/indicators/rsi/{ticker}"""
        return self._indicator("rsi", ticker, timespan, window, series_type, limit)

    def get_macd(
        self,
        ticker: str,
        timespan: str = "day",
        short_window: int = 12,
        long_window: int = 26,
        signal_window: int = 9,
        series_type: str = "close",
        limit: int = 5000,
    ) -> dict[str, Any] | None:
        """GET /v1/indicators/macd/{ticker}"""
        ticker = ticker.upper()
        params: dict[str, Any] = {
            "timespan": timespan,
            "short_window": short_window,
            "long_window": long_window,
            "signal_window": signal_window,
            "series_type": series_type,
            "limit": min(limit, 5000),
        }
        return self._get(f"/v1/indicators/macd/{ticker}", params)

    def _indicator(
        self,
        indicator: str,
        ticker: str,
        timespan: str,
        window: int,
        series_type: str,
        limit: int,
    ) -> dict[str, Any] | None:
        """通用技术指标请求。"""
        ticker = ticker.upper()
        params: dict[str, Any] = {
            "timespan": timespan,
            "window": max(1, min(200, window)),
            "series_type": series_type,
            "limit": min(limit, 5000),
        }
        return self._get(f"/v1/indicators/{indicator}/{ticker}", params)

    # ================================================================
    # Market Operations
    # ================================================================

    def get_market_status(self) -> dict[str, Any] | None:
        """GET /v1/marketstatus/now — 当前美股市场状态。"""
        return self._get("/v1/marketstatus/now")

    def get_market_holidays(self) -> dict[str, Any] | None:
        """GET /v1/marketstatus/upcoming — 假期日历。"""
        return self._get("/v1/marketstatus/upcoming")

    def get_exchanges(self) -> dict[str, Any] | None:
        """GET /v3/reference/exchanges — 交易所列表。"""
        return self._get("/v3/reference/exchanges")

    def get_conditions(self) -> dict[str, Any] | None:
        """GET /v3/reference/conditions — 交易条件码。"""
        return self._get("/v3/reference/conditions")

    # ================================================================
    # Corporate Actions
    # ================================================================

    def get_splits(self, ticker: str | None = None, limit: int = 100) -> dict[str, Any] | None:
        """GET /stocks/v1/splits — 拆股历史。"""
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if ticker:
            params["ticker"] = ticker.upper()
        return self._get("/stocks/v1/splits", params)

    def get_dividends(self, ticker: str | None = None, limit: int = 100) -> dict[str, Any] | None:
        """GET /stocks/v1/dividends — 分红历史。"""
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if ticker:
            params["ticker"] = ticker.upper()
        return self._get("/stocks/v1/dividends", params)

    # ================================================================
    # Fundamentals
    # ================================================================

    def get_short_interest(self, ticker: str) -> dict[str, Any] | None:
        """GET /stocks/v1/short-interest — 空头持仓（FINRA 双周数据）。"""
        return self._get("/stocks/v1/short-interest", {"ticker": ticker.upper()})

    def get_float(self, ticker: str) -> dict[str, Any] | None:
        """GET /stocks/vX/float — 流通股数。"""
        return self._get("/stocks/vX/float", {"ticker": ticker.upper()})

    # ================================================================
    # News
    # ================================================================

    def get_news(
        self,
        ticker: str | None = None,
        limit: int = 10,
        published_utc_lte: str | None = None,
    ) -> dict[str, Any] | None:
        """GET /v2/reference/news — 新闻（可选按 ticker 过滤）。"""
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if ticker:
            params["ticker"] = ticker.upper()
        if published_utc_lte:
            params["published_utc.lte"] = published_utc_lte
        return self._get("/v2/reference/news", params)
