# Massive / Polygon REST API — 客户端参考

本文件是 `src/mommy_chaogu/market_data/massive_client.py` 的接口参考,内容以该模块的实实现为准。

## 端点与认证

- Base URL:`https://api.massive.com`(兼容 `https://api.polygon.io`)
- 认证:Bearer token header;API key 经 `_resolve_api_key()` 解析(参数 > 环境变量)
- 分页:cursor-based,`response.next_url` 指向下一页;`_get_paginated()` 自动跟随

## 方法清单(Basic+ 免费 tier,约 21 个)

### 基础信息
- `get_ticker_details(ticker)` / `get_ticker_types()` / `list_tickers(...)`
- `get_related_companies(ticker)`
- `get_market_status()` / `get_market_holidays()` / `get_exchanges()` / `get_conditions()`

### 行情快照
- `get_snapshot(ticker)` / `get_snapshots_batch(tickers)`
- `get_gainers_losers(direction="gainers")`

### 聚合与 OHLC
- `get_aggs(...)` / `get_grouped_daily(date)`
- `get_daily_open_close(ticker, date)` / `get_previous_close(ticker)`

### 技术指标
- `get_sma(...)` / `get_ema(...)` / `get_rsi(...)` / `get_macd(...)`
  (统一经 `_indicator()` 构造窗口参数)

### 公司行动
- `get_splits(ticker=None, limit=100)` / `get_dividends(ticker=None, limit=100)`
- `get_short_interest(ticker)`

## 约定

- 所有方法返回原始 JSON(`dict`/`list`)或 `None`;本模块不做业务模型映射
- 新增端点时同步更新本文件的方法分组
