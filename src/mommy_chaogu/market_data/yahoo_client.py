"""YahooClient: Yahoo Finance chart REST API 客户端。

纯 HTTP 客户端，不做业务模型映射。返回原始 JSON (dict) 或 None。
无需 API key，只依赖 requests。

参考端点：
- chart: GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
  参数 range + interval，返回 meta（实时价/名称/交易所时区/52 周高低等）
  + OHLCV 数组（timestamp + indicators.quote[0]，另有 adjclose 复权收盘）。
  同一端点覆盖美股个股（AAPL）、指数（^GSPC）、波动率（^VIX）、利率（^TNX）。
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import requests

_log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://query1.finance.yahoo.com"
DEFAULT_TIMEOUT = 15.0

# Yahoo chart 是公开未鉴权端点。实测完整浏览器 UA 会被其机器人检测限流（429），
# 极简 "Mozilla/5.0" 反而稳定 200——用后者。
_UA = "Mozilla/5.0"


class YahooClient:
    """Yahoo Finance chart REST API 客户端。

    用法：
        client = YahooClient()
        data = client.get_chart("^GSPC", range="5d", interval="1d")  # → dict | None
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA, "Accept": "application/json"})

    # ---------- 内部：HTTP ----------

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """GET 请求，返回 JSON dict。失败返回 None。"""
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except requests.HTTPError as e:
            _log.warning(
                "yahoo GET %s HTTP %s: %s",
                path,
                e.response.status_code if e.response and e.response.status_code else "?",
                e,
            )
        except Exception as e:
            _log.warning("yahoo GET %s failed: %s: %s", path, type(e).__name__, e)
        return None

    # ---------- chart ----------

    def get_chart(
        self,
        symbol: str,
        range: str = "1d",
        interval: str = "1d",
        include_prepost: bool = False,
    ) -> dict[str, Any] | None:
        """GET /v8/finance/chart/{symbol} — meta + OHLCV。失败返回 None。

        Args:
            symbol: 代码（`^` 前缀的指数/利率/VIX，或字母开头的美股个股）。
            range: Yahoo 时间窗口（1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max）。
            interval: K 线周期（1m/5m/15m/30m/60m/1h/1d/1wk/1mo）。
            include_prepost: 是否包含盘前盘后数据。
        """
        encoded = urllib.parse.quote(symbol.upper(), safe="")
        params: dict[str, Any] = {
            "range": range,
            "interval": interval,
            "includePrePost": "true" if include_prepost else "false",
        }
        return self._get(f"/v8/finance/chart/{encoded}", params)
