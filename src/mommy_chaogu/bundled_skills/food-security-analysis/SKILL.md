---
name: food-security-analysis
description: |
  Reproduce the A-share food-security / food-crisis end-to-end analysis: build
  the 35-stock 粮食安全 basket, pull today's money flow, run MA5/10/20/60
  technicals on Top-5 candidates, fetch PE/ROE fundamentals, rank Top 5 by
  high-elasticity + fundamentals + technicals, then package a 9-deliverable
  set (report + strategy-card, each in 3 formats: .md / .html / .pdf, plus
  the interactive dark-mode web.html with Chart.js + hover tooltips + click-
  to-jump + embedded report/strategy reader + download dropdown, plus the
  pure-text Markdown for non-image readers, plus raw data.json) into a
  timestamped per-day ZIP archive. Use this skill when the user asks to
  "做粮食安全分析" / "复现刚才的粮食危机分析" / "A 股 today + 粮食安全"
  / "food security / crisis analysis" / "build the food-security basket
  and report" / "跑一遍 food-security 主题 流程" / "analyze a single
  A-share day for the 粮食安全 theme" / "我要纯文字版报告" / "给个深色
  模式" / "出 4 变量历史图" / "网页里读报告和策略卡" / "下载 PDF 或
  Markdown". Do NOT use for: general A-share market commentary without a
  theme (use web research only); single-stock deep-dives outside the food-
  security basket (different workflow); pure global macro food analysis
  with no A-share basket interest (use web research only); LLM-key-required
  chat-mode queries like "mommy \"今天大盘怎么样\"" without re-running the
  full basket+report pipeline.
---

# Food Security Analysis

End-to-end pipeline that takes a trading day (default: today, Beijing time) and produces a packaged set of food-security / food-crisis analysis artifacts for the 35-stock A-share basket, plus Top-5 deep-dive with technicals and fundamentals.

## Inputs to collect

Ask the user only what the procedure cannot infer:

- **Trading day** (default: today Beijing time). Required if the user asks for a back-fill ("复盘 8/15 那次涨停潮"). Format: `YYYY-MM-DD`.
- **Run label** (default: auto-timestamp). User can override (`run_label: "morning-prep"`).
- **Mark as final** (default: `false` if multiple runs already today, `true` if first or only run). User can force.

If the user is vague ("复现刚才的分析"), just run with defaults.

## Procedure

1. **Resolve trading day and data freshness**
   - Compute `today_bj = now(Asia/Shanghai).strftime("%Y-%m-%d")` and `now_bj_iso` with offset `+08:00`.
   - Detect post-market: if `now_bj.time() > 15:05`, mark `is_market_close=true` and the data label becomes `as of {today_bj} close (Beijing)`. Otherwise label as `as of {today_bj} mid-day (Beijing)`.
   - Why: the data label is what readers see; getting the freshness wrong misleads every downstream user.

2. **Verify mommy-chaogu + basket exist**
   - Run `mommy food-security list --chain 上游` and `mommy food-security stats`. Confirm 35 codes and 4 chain × 14 subcategory. If missing, run `mommy food-security seed` first.
   - Why: the basket is the canonical 35-code reference for the whole pipeline; missing seed → downstream flows are incomplete.

3. **Get A-share market snapshot for `today_bj`**
   - Use `web_search(query="A股 {today_bj} 午间/收盘 上证指数 深证成指 创业板", freshness="day")` to get 上证/深成/创业/科创50/北证50 half-day or close values plus 涨停潮板块 and 拖累板块.
   - If pre-08:00 and no results, fall back to previous trading day's data and label accordingly.
   - Why: mommy has no direct "indices" subcommand; web is the only available index data source in this sandbox.

4. **Get global food crisis context**
   - Use `web_search(query="FAO Food Price Index {month_before(today_bj)} wheat corn", freshness="month")` for the latest FAO index and sub-indices.
   - Use `web_search(query="Black Sea grain exports {month_before(today_bj)} Russia Ukraine", freshness="month")` for the Black Sea disruption status.
   - Use `web_search(query="El Nino strength 2026 ONI", freshness="month")` for the climate driver.
   - Why: 4-variable trigger check (FAO ≥ +2%, Black Sea ≤ -30%, ONI ≥ 1.5, 399365 PE ≤ 40%) is the topic's gating condition. Without global context, the A-share picture is incomplete.

5. **Pull money flow for the 35-stock basket**
   - Add codes to watchlist: `mommy watchlist add-group 粮食安全-全量` (idempotent) and add all 35 codes via `mommy watchlist add <code> --group 粮食安全-全量`.
   - Pull: `mommy flows --db portfolio.db --pool watchlist pull --target today --force`. Retry up to 2 times to recover efinance rate-limit failures.
   - Compute coverage: `len(cached) / 35`. If < 60%, log warning and continue with what was pulled; do NOT fail.
   - Why: money flow is the basket's real-time signal; partial coverage is normal and reportable, not a failure.

6. **Identify Top-5 by money flow + pull 60-day K-line for each**
   - Sort by `main_net` desc, take top 5 (or top 8 if user wants wider). Skip codes flagged `ST` (荃银高科 300087) from default ranking.
   - For each Top-5 code, fetch 60-day daily K-line via Tencent raw HTTP API (`http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,60,qfq`).
   - Why: efinance's K-line is rate-limited in the sandbox; Tencent raw API is a stable 1.3s/code fallback. The url pattern is documented in `references/data_sources.md`.

7. **Compute MA5/10/20/60 + trend + deviation + position**
   - For each code: MA_n = sum(closes[-n:]) / n (simple arithmetic mean, equivalent to mommy's `agent.tools.analysis._ma`).
   - Trend: `bull` if close > MA20 > MA60; `bear` if close < MA20 < MA60; else `mixed`.
   - `dev20` = (close / MA20 - 1) × 100; flag `+5%` as overbought, `-2%` as oversold.
   - `pos20` = (close - min20) / (max20 - min20) × 100; 0% = 20-day low, 100% = 20-day high.
   - `vol_ratio` = today_volume / avg(last 5 days volume).
   - Golden cross scan: if MA5_prev ≤ MA20_prev AND MA5_today > MA20_today, flag as `golden_cross_recent`.

8. **Fetch fundamentals for Top 5 via web**
   - `web_search(query="{name} {code} PE ROE 2026 中报 业绩")` for each. Extract: PE-TTM, latest 2025 annual report figures, 2026 Q1, 2026 H1 (or preannouncement), ROE, gross margin, key catalyst.
   - Why: ranking needs fundamental anchors, not just price action.

9. **Generate nine deliverables (v1.2 = 9 files: each doc in 3 formats)**
   - `report.md`: full report (≥ 30 KB, 11 sections) — hero summary, 4-variable trigger, basket composition, money flow tables, Top-5 cards, MA comparison, global crisis drivers, A-share snapshot, verification checklist, timeline, key learnings, file list. Header: `数据截至: {today_bj} {close|mid-day} (北京时间)`.
   - `report.html`: same content as `report.md` rendered to standalone HTML (Python `markdown` lib with tables/fenced_code/toc/sane_lists extensions). Has dark-mode toggle + print CSS. For opening in browser without running through the report pipeline.
   - `report.pdf`: same content printed to PDF via `chrome --headless --print-to-pdf` (1-1.2 MB). For sharing / printing.
   - `strategy-card.md`: draft strategy card (unsaved, not written to `portfolio.db`). Sections: 1-sentence strategy, 4 trigger conditions + current values, Tier 1-4 sub-themes ranking, Top-5 weight allocation, fact vs inference breakdown, save options. Header: same timestamp.
   - `strategy-card.html`: same as `strategy-card.md` rendered to standalone HTML.
   - `strategy-card.pdf`: same printed to PDF (600-700 KB).
   - `web.html`: self-contained HTML, report-mode design (cream `#f7f5f0` light / `#0f1419` dark, forest green `#2f6f5e` + amber `#c97b3f` accent). **v1.2 增强**: ① all v1.1 features (sticky topbar + scroll-spy, dark mode, hover tooltips, click-to-jump, Chart.js, mode toggle); ② **embedded reader** — sections #section-strategy and #section-report-md render the strategy card and full report as readable HTML inside web.html (no need to open separate files); ③ **download dropdown** in topbar with 8 file links grouped by complete report / strategy card / other; ④ **floating "另存 PDF" button** at bottom-right that triggers `window.print()` (browser save-as-PDF); ⑤ **print CSS** — topbar, toggles, fab, dropdowns hidden in print; ⑥ **Blob download fallback** — if MD link 404s in deployed previews, page extracts from embedded source and triggers client-side download. Modules: hero, 4-variable trigger, basket donut, money flow with hover tooltips, Top-5 cards with click-jump, MA table, Chart.js time-series, crisis drivers, A-share snapshot, verification checklist, embedded strategy card, embedded full report, file list. Header: same timestamp.
   - `text.md`: **pure-text version** for non-image readers. No charts, no images, no JS, no CDN — pure Markdown tables + monospace ASCII blocks. Higher information density than the report (same data, more compact tables). Can be pasted into WeChat / email / Notion directly. Header: same timestamp.
   - `data.json`: raw data (basket flow for all 35 codes, Top-5 K-line + MA, global context, A-share snapshot, fundamentals, top5_flow_ts for Chart.js).

10. **Package into ZIP**
    - Run directory: `deliverables/food-security/{today_bj}/{run_ts}/` containing the 9 deliverables + `data.json`.
    - Per-day ZIP: `deliverables/food-security/{today_bj}.zip`. Structure:
      ```
      manifest.json
      daily-final/                     # canonical final version (latest run or user-marked)
        report.md
        report.html
        report.pdf
        strategy-card.md
        strategy-card.html
        strategy-card.pdf
        web.html
        text.md
        data.json
      runs/
        {run_ts_1}/                    # all 9 files
        {run_ts_2}/...
        {latest_run}/                  # also linked from daily-final
      ```
    - If multiple runs already exist for `today_bj`, append a `run_N` counter to the run directory; the latest run becomes `daily-final/`.
    - `manifest.json` schema: `{session_id, skill_version: "1.2", generated_at, trading_day, is_market_close, data_as_of, is_final, basket_coverage: {total, money_flow_pulled, kline_pulled_top5}, files: [{path, type, size_bytes, sha256}, ...], runs_in_zip: [{ts, is_final}]}`. `is_final` is true for the run that backs `daily-final/`.
    - Why: the per-day ZIP lets the user "send me today's full food-security package" with one file; `daily-final/` removes ambiguity about which run is canonical; 3-format duplication (md/html/pdf) covers every reader; `text.md` is for non-image readers (email, WeChat, Notion, print).

## Output contract

Always produce (9 deliverables + 1 archive):

1. `deliverables/food-security/{today_bj}/{run_ts}/report.md` — full report, ≥ 30 KB, 11 sections
2. `deliverables/food-security/{today_bj}/{run_ts}/report.html` — rendered HTML version (dark mode + print CSS)
3. `deliverables/food-security/{today_bj}/{run_ts}/report.pdf` — printed PDF (~1 MB)
4. `deliverables/food-security/{today_bj}/{run_ts}/strategy-card.md` — draft card, ≥ 8 KB
5. `deliverables/food-security/{today_bj}/{run_ts}/strategy-card.html` — rendered HTML
6. `deliverables/food-security/{today_bj}/{run_ts}/strategy-card.pdf` — printed PDF (~700 KB)
7. `deliverables/food-security/{today_bj}/{run_ts}/web.html` — self-contained HTML, **v1.2** has dark-mode + Chart.js + hover/click + embedded report/strategy reader + download dropdown + print fab
8. `deliverables/food-security/{today_bj}/{run_ts}/text.md` — pure-text version (no images, no JS, no CDN, paste-anywhere)
9. `deliverables/food-security/{today_bj}/{run_ts}/data.json` — raw data (basket flow, top-5 tech + flow time series, global context)
10. `deliverables/food-security/{today_bj}.zip` — per-day archive with `daily-final/` + `runs/` + `manifest.json`

The data timestamp inside each report/webpage header must be `as of {today_bj} close (Beijing)` (or `mid-day (Beijing)`) — never the analysis-generation time, never the A-share session open time, never the wall-clock time of script execution.

## Failure handling

- **efinance K-line rate limit (sandbox)**: fall back to Tencent raw HTTP API. The url pattern is `{market}{code},day,,,60,qfq` on `http://web.ifzq.gtimg.cn/appstock/app/fqkline/get`. 1.3s/code, 100% success. See `references/data_sources.md` for the Python snippet.
- **TencentAdapter.get_bars is a stub** in mommy-chaogu v1.4.0 (returns `[]`). Do not use it; always call the raw API.
- **efinance money flow rate limit** for the 35-code basket: retry up to 2 times; if still < 60% coverage, log it explicitly in the report and continue. Do not fail the whole run.
- **No LLM key**: that's expected and the script is designed to run without one (mommy has built-in signal rules + the analysis is rule-based, not LLM-routed). The `agent detect` "no managed host" output is normal, not a failure.
- **web_search empty** for a Top-5 code: mark that code as `fundamentals: unavailable` in the report; do not invent PE/ROE.
- **Multiple same-day runs**: ZIP overwrites the same-day file; old run directories are preserved inside `runs/`. The `daily-final/` is repointed to the latest run.
- **User asks to force-mark a run as final**: set `is_final: true` in that run's `manifest.json` and copy its contents to `daily-final/`, even if it's not the latest.

## Examples

**Input**: "复现刚才的粮食安全分析"  
**Output**:
- `deliverables/food-security/2026-08-17/20260817-153000/report.md` (with header `数据截至: 2026-08-17 close (北京时间)`)
- `deliverables/food-security/2026-08-17/20260817-153000/strategy-card.md`
- `deliverables/food-security/2026-08-17/20260817-153000/web.html` (dark-mode + Chart.js + hover/click enabled)
- `deliverables/food-security/2026-08-17/20260817-153000/text.md` (pure-text version for non-image readers)
- `deliverables/food-security/2026-08-17/20260817-153000/data.json`
- `deliverables/food-security/2026-08-17.zip` (with `daily-final/` + `runs/20260817-153000/` + `manifest.json`)

**Input**: "给个深色模式 + 4 变量历史图"  
**Output**: same 5 files. The `web.html` includes the dark-mode toggle (top-right) and the Chart.js section with the 4-variable 6-month bar chart. No additional files needed; the data is embedded in the HTML.

**Input**: "我要纯文字版报告, 不看图"  
**Output**: same 5 files. The `text.md` is the canonical answer — point the user to it. It has higher information density than `report.md` (same data, more compact tables) and works in any text-only channel (email, WeChat, Notion, terminal).

**Input**: "复盘 2026-08-15 那次粮食板块涨停潮"  
**Output**: same structure but `trading_day=2026-08-15`; web_search uses that date; money flow is the historical snapshot (mommy will pull whatever is in cache; if cache is empty, fall back to web search of that day's news for 涨停潮个股).

## See also

- `references/basket.md` — the 35 codes with chain/subcategory, source of truth for the basket
- `references/data_sources.md` — A-share web sources, efinance, Tencent K-line raw API, global macro URLs
- `references/output_format.md` — exact ZIP file structure, manifest.json schema, report header format
