# Monitoring coverage catalog

Use this reference when translating a user's requested information into supported evidence blocks.
The exact adapter and live availability always take precedence over this catalog.

## A-shares

| Block | Preferred project capability | Reportable fields | Common gap |
|---|---|---|---|
| Broad market | index/quote adapters | symbol, name, price, change, source time | index source may fail or return partial data |
| Theme/sector | `ThemeService` and quote adapter | member count, returned count, breadth, average change, leaders/laggards | provider may not expose an equivalent sector ranking |
| Constituents | batch quote adapter | price, change, volume, turnover, turnover rate, volume ratio when present | partial baskets and missing fields |
| K-lines | `get_bars`/cache | interval, OHLCV, adjustment, last completed bar | intraday history limits and incomplete bars |
| Money flow | flows service / source-specific endpoint | net flow and source time | Tencent quote fallback does not provide it |
| Alerts | signals/monitor services | exact rule, threshold, current check, trigger | do not infer unsupported custom rules |

Use the order broad market → theme/sector → constituents. A theme's constituent breadth is not the
same as whole-market breadth unless the full universe was actually returned.

## US stocks

| Block | Yahoo-only expectation | Massive/Polygon plus Yahoo | Reportable fields |
|---|---|---|---|
| Benchmarks | `^GSPC`, `^IXIC`, `^DJI` where available | equity/index coverage depends on key and endpoint | price, change, source time |
| Risk gauges | `^VIX`, `^TNX` where available | Yahoo is typically the fallback | level, change, source time |
| Sector/theme | only explicitly named ETFs/symbols | broader equity universe if entitlement supports it | quote/bar performance, breadth only for returned basket |
| Constituents | user-supplied ticker basket | user-supplied ticker basket | price, change, volume, bars |
| K-lines | chart endpoint with interval limits | native equity bars where entitled, Yahoo fallback otherwise | completed OHLCV, interval, adjustment semantics |
| Money flow | unavailable | do not assume available; verify endpoint semantics | label unavailable unless proven |

US tickers must retain their exact Yahoo symbol form, including `^` indices. A ticker mapping or
source switch is a data-quality event and belongs in the poll update.

## Standard poll record

At minimum preserve these fields in CSV/SQLite or an equivalent structured record:

```text
run_id, poll_id, requested_at, observed_at, exchange, session,
pipeline, source, source_timestamp, scope, requested_count, returned_count,
coverage, values, analysis, missing_fields, freshness_status, error
```

`values` and `analysis` may be compact serialized text in CSV. JSON is acceptable inside one field or
for an explicit downstream contract, but do not create a separate JSON document for every poll.
