---
name: market-watch-loop
description: "Use when the user wants a repeatable intraday monitoring loop for A-shares or US stocks, with a configurable polling frequency, market/theme/stock coverage, optional moving-average analysis, source-aware updates, and a final report. For US stocks, require an explicit data-pipeline choice before collecting data unless one was already provided."
---

# Market Watch Loop

Use this skill to turn a natural-language request into a bounded, auditable market-monitoring
loop. The loop is configurable, but every run must preserve the exchange session, source
timestamps, coverage, missing fields, and stop condition.

## 1. Confirm the monitoring contract

Resolve the smallest set of missing choices before starting repeated collection:

```text
market: A-shares | US stocks
scope: indices, sectors/themes, ETFs, and/or named symbols
frequency: positive duration; default 10 minutes
window: exchange session, explicit start/end, or bounded number of polls
coverage: one or more supported information blocks
analysis: breadth, leaders/laggards, MA timeframes, flows, or other supported calculations
output: live update, CSV/SQLite history, Markdown report
```

Ask for clarification only when a missing choice changes the data source or safety of the run.
Reasonable defaults are:

- **Frequency**: every 10 minutes during regular trading hours. Honor a user-specified cadence,
  including 15 minutes, and state it in the first update.
- **A-share scope**: broad indices → requested sector/theme → canonical constituents when a theme
  is named. Disclose the returned constituent count and any truncation.
- **US scope**: `^GSPC`, `^IXIC`, `^DJI`, `^VIX`, and `^TNX` plus the user's ETF or stock basket;
  do not invent a sector universe when none was requested.
- **Storage**: append one dated CSV summary or use the project's SQLite/cache path. Keep raw OHLC
  in memory or in a deliberately named CSV/SQLite file. Do not create one JSON file per poll.
- **Duration**: stop at the requested end time or exchange close; never run indefinitely by
  implication.

For US stocks, do not fetch data until the user has chosen a pipeline, unless the request already
specifies one:

1. **Yahoo Finance only**: no key; quotes/bars, benchmarks, VIX, and rates where available. It
   does not provide a full-market snapshot, money flow, or reliable A-share-style sector breadth.
2. **Massive/Polygon primary + Yahoo fallback**: use when the corresponding key is configured;
   disclose that equity and index/risk data can have different timestamps and semantics.
3. **Offline fixture/historical replay**: deterministic and network-free; valid for testing loop
   orchestration, not for claiming current market freshness.

State the selected pipeline, credential requirement, expected coverage, and limitations before the
first request. Read [coverage-catalog.md](references/coverage-catalog.md) for the supported blocks
and source-specific gaps.

## 2. Translate the requested coverage into evidence blocks

Only include blocks the selected source can actually supply. Preserve the user's requested meaning;
if a block is unavailable, label it `unavailable` or `degraded` rather than replacing it with a
similar-looking proxy.

### A-shares

Collect in this order:

1. **Broad market**: requested indices and session status.
2. **Theme/sector**: breadth, average change, leaders/laggards, and returned count.
3. **Constituents**: named stocks or canonical theme members.
4. **Optional blocks**: money flow, turnover, volume ratio, K-lines, earnings, and alerts only
   when the selected adapter exposes them.

### US stocks

Collect in this order:

1. **Broad market and risk**: benchmarks, VIX, Treasury/rate symbols, and session status.
2. **Theme/sector**: explicitly requested ETFs or sector symbols.
3. **Constituents**: the user's symbols, with quote/bar coverage.
4. **Optional blocks**: K-lines, volume/relative performance, earnings, and MA analysis when the
   selected pipeline supports them.

Never turn US volume or ETF movement into “money flow”, and never report a partial basket as a full
market breadth reading.

## 3. Start and run the loop

1. Check the current timezone and translate the exchange session:
   - A-shares: `Asia/Shanghai`, 09:30–11:30 and 13:00–15:00; skip lunch.
   - US stocks: `America/New_York`, 09:30–16:00; account for daylight saving time.
2. Build a baseline before the first wait. Record request time, source timestamp, session status,
   pipeline, requested/returned symbols, values, missing fields, and errors.
3. On each poll, perform this fixed sequence:

   ```text
   fetch → normalize → freshness check → compare with prior snapshot
         → calculate selected analyses → append durable summary → report meaningful changes
   ```

4. Use source timestamps as market time. A successful HTTP response with an old timestamp is stale,
   not a fresh observation.
5. Use the hierarchy **broad market → sector/theme → constituents** in every update. If levels
   conflict, show the conflict instead of forcing one conclusion.
6. If no scheduler is available, run a bounded foreground loop and say so. Do not claim a background
   task, task ID, or automatic cleanup that was not actually created.

### Freshness and fallback rules

- Mark `empty`, `partial`, `stale`, `frozen`, or `source_changed` explicitly.
- Compare both values and source timestamps. Identical values are not a change when timestamps also
  do not advance.
- Preserve the previous good observation when a refresh fails; do not overwrite it with nulls.
- Use only fallbacks declared by the selected pipeline. Report when a fallback takes over.
- Stop or reduce claims when coverage falls below the requested scope or a source repeatedly fails.

### Optional multi-timeframe moving averages

When MA analysis is selected, run it on completed OHLC bars and report each requested timeframe:

- `5m`: recent Yahoo 5-minute bars; drop the still-forming bar and call the result experimental.
- `30m`: prefer native 30-minute history when enough EMA warm-up bars are needed.
- `1h`: prefer native 1-hour history.
- `4h`: aggregate completed 1-hour bars using first open, max high, min low, last close, and
  summed volume; Yahoo need not provide a native 4-hour endpoint.
- `1d`: daily bars excluding the current incomplete session.

Use the MA tool's default EMA/ATR configuration unless the user specifies parameters. If history is
too short, return `insufficient_history`; do not invent a regime or alert. When available, include
`bars_used`, `last_bar_time`, `regime`, `alert`, `cloud_dist_atr`, `bottom_score`, and
`suppression_events_total`. Keep the analytical interval's native history separate from any recent
5-minute cross-check.

## 4. Report each poll

Keep live updates concise and stable so the user can compare them. Each update contains:

- **事实**: source-timestamped index/benchmark values, breadth, theme/ETF and stock changes;
- **分析**: only the requested calculations, including MA readouts when selected;
- **当日判断**: strong / neutral / weak (or Chinese equivalents), with the evidence chain;
- **变化**: what changed from the prior poll, or “无有效变化” when timestamps/values did not;
- **数据质量**: pipeline, source timestamps, requested/returned counts, freshness, fallback, and
  missing fields;
- **下一轮**: the exchange-local next poll time or the reason polling is paused.

Separate facts from inference. A five-day view is an explicitly conditional inference, not a
guarantee: state the supporting conditions and the invalidation conditions. Do not issue a trade
order or imply guaranteed returns.

## 5. Stop and persist the run

Stop on the user's cancellation, requested end time, exchange close, or an explicit failure
threshold. On cancellation, preserve the last completed poll and write the report before exiting.

The durable run should contain:

- one append-only CSV summary (or SQLite records) for poll-level results and coverage;
- one Markdown report with contract, pipeline, baseline, timeline, fallback behavior, conclusions,
  invalidation rules, and unresolved issues;
- optional raw OHLC CSV only when needed to reproduce a calculation.

If a scheduler was used, delete only the monitor task created by this run and verify it is gone. If
the loop was foreground-only, record that no scheduler lifecycle existed. Never claim a poll,
source freshness, or cleanup result unless the process output or saved artifact proves it.
