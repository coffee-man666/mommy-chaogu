---
name: basket-analysis
description: |
  Reproduce the A-share theme basket end-to-end analysis for ANY theme (粮食安全,
  半导体, 煤炭, 创新药, 新能源, etc.). Pipeline: build/pick a basket (10-50 stocks),
  pull today's money flow, run MA5/10/20/60 technicals on Top-5 candidates, fetch
  PE/ROE/H1 fundamentals, score Top 5 by high-elasticity + fundamentals + technicals,
  then package a 9-deliverable set (report + strategy-card, each in 3 formats:
  .md / .html / .pdf, plus the interactive dark-mode web.html with Chart.js +
  hover tooltips + click-to-jump + embedded report/strategy reader + download
  dropdown, plus pure-text Markdown for non-image readers, plus raw data.json)
  into a timestamped per-day ZIP archive. The procedure is theme-agnostic;
  per-theme specifics (basket source, 4 trigger variables, search queries) live
  in `references/themes/{theme}.md` configs. Use this skill when the user asks
  to analyze any A-share theme / sector / 概念 / 题材, e.g. "做粮食安全分析" /
  "复现刚才的粮食危机分析" / "分析半导体板块" / "煤炭今天怎么样" / "创新药
  资金流" / "出 4 变量历史图" / "网页里读报告和策略卡" / "下载 PDF 或
  Markdown" / "analyze 粮食安全/半导体/煤炭/创新药 theme" / "build a basket
  for {X} and report". Do NOT use for: general A-share market commentary
  without a specific theme (use web research only); single-stock deep-dives
  outside any theme basket (different workflow); pure global macro analysis
  with no A-share basket interest (use web research only); LLM-key-required
  chat-mode queries like "mommy \"今天大盘怎么样\"" without re-running the
  full basket+report pipeline.
---

# Basket Analysis (通用 A 股主题篮子分析)

End-to-end pipeline that takes a trading day (default: today, Beijing time) and a theme name (e.g. 粮食安全, 半导体, 煤炭, 创新药), and produces a packaged set of analysis artifacts for that theme's basket.

## 主题配置 (theme config)

所有主题共用同一套技术方法 (10 步 procedure). 主题间的差异 (篮子, 4 变量触发, 全局背景, 搜索关键词) 都封装在 `references/themes/{theme}.md` 配置里. 

当前内置主题:
- `references/themes/food-security.md` — 粮食安全/危机 (35 只, FAO + 黑海 + 厄尔尼诺 + 399365 PE)
- `references/themes/_template.md` — 新主题模板 (复制此文件 + 改 4 变量即可)

加新主题: `cp references/themes/_template.md references/themes/my-theme.md` 然后填:
- `basket.source` (mommy CLI / SQL group / 手动列表)
- `trigger_variables` (4 个变量 + 搜索 query)
- `global_context_searches` (必查的全局背景)
- `domain_keywords` (主题关键词, 用于篮子筛选)

## Inputs to collect

Ask the user only what the procedure cannot infer:

- **Theme name** (default: `food-security`). 必填, 决定 basket + 4 变量 + 报告标题.
- **Trading day** (default: today Beijing time). Required if back-fill ("复盘 8/15").
- **Run label** (default: auto-timestamp).
- **Mark as final** (default: false if multiple runs already today, true if first or only run).

If the user is vague ("复现刚才的分析"), use the last-used theme + today's date.

## Procedure

1. **Resolve theme + trading day + data freshness**
   - Theme: from user input (or default `food-security`). Load `references/themes/{theme}.md` to get basket source + 4 variable definitions + search queries.
   - Trading day: `today_bj = now(Asia/Shanghai).strftime("%Y-%m-%d")` + `now_bj_iso` with `+08:00`.
   - Detect post-market: if `now_bj.time() > 15:05`, mark `is_market_close=true`. Otherwise `mid-day (Beijing)`.
   - Why: theme drives everything downstream; data label is what readers see.

2. **Verify basket exists for the theme**
   - Read the theme config's `basket.source`. If `mommy <cli>`, run `mommy <cli> list` and `mommy <cli> stats`. If `manual`, ensure the list is provided. If `basket_total` ≠ `len(pulled)`, may need to seed first.
   - Confirm 4 chain/subcategory (or whatever the theme config requires). If missing, run `mommy <cli> seed` first.
   - Why: the basket is the canonical reference; missing seed → downstream flows are incomplete.

3. **Get A-share market snapshot for `today_bj`**
   - `web_search(query="A股 {today_bj} 午间/收盘 上证指数 深证成指 创业板", freshness="day")` for indices + 涨停潮板块 + 拖累板块.
   - If pre-08:00 and no results, fall back to previous trading day's data and label accordingly.
   - Why: mommy has no direct "indices" subcommand; web is the only source.

4. **Get theme-specific global context + 4 trigger variables**
   - The theme config's `global_context_searches` lists the queries to run (one per line). Run each.
   - For each of the 4 `trigger_variables`, fetch its current value (web search per the config's `search_query`).
   - Decide status (✅ trigger / ❌ no) by comparing `current` vs `threshold`.
   - Why: 4-variable trigger is the topic's gating condition. Without theme-specific data, the picture is incomplete.

5. **Pull money flow for the basket**
   - Add codes to the right pool: `mommy watchlist add-group <basket_name>` (idempotent) + `mommy watchlist add <code> --group <basket_name>`.
   - Pull: `mommy flows --db portfolio.db --pool watchlist pull --target today --force` (or `--pool custom --codes X Y Z` if theme has manual codes).
   - Compute coverage: `len(cached) / basket_total`. If < 60%, log warning and continue.
   - Why: money flow is the basket's real-time signal; partial coverage is normal.

6. **Identify Top-5 by money flow + pull 60-day K-line for each**
   - Sort by `main_net` desc, take top 5 (skip codes flagged `ST` or matching theme's `excluded_codes`).
   - For each Top-5 code, fetch 60-day daily K-line via Tencent raw HTTP API (`http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,60,qfq`).
   - Why: efinance K-line is rate-limited; Tencent raw API is a stable 1.3s/code fallback.

7. **Compute MA5/10/20/60 + trend + deviation + position**
   - For each code: MA_n = sum(closes[-n:]) / n.
   - Trend: `bull` if close > MA20 > MA60; `bear` if close < MA20 < MA60; else `mixed`.
   - `dev20` = (close / MA20 - 1) × 100; flag `+5%` overbought, `-2%` oversold.
   - `pos20` = (close - min20) / (max20 - min20) × 100.
   - `vol_ratio` = today_volume / avg(last 5 days volume).
   - Golden cross: MA5_prev ≤ MA20_prev AND MA5_today > MA20_today.

8. **Fetch fundamentals for Top 5 via web**
   - `web_search(query="{name} {code} PE ROE 2026 中报 业绩", freshness="month")` for each.
   - Extract: PE-TTM, latest 2025 annual, 2026 Q1, 2026 H1 (or preannouncement), ROE, key catalyst.
   - Why: ranking needs fundamental anchors, not just price action.

9. **Generate nine deliverables (3 formats × 3 doc types)**
   - `report.md`: full report (≥ 30 KB), 11 sections — hero, 4-var trigger, basket composition, money flow, Top-5 cards, MA comparison, global crisis drivers, A-share snapshot, verification checklist, timeline, key learnings, file list. Header: `数据截至: {today_bj} {close|mid-day} (北京时间)`. Title: `{theme.name} 主题分析报告`.
   - `report.html` + `report.pdf`: same content rendered / printed.
   - `strategy-card.md` + `.html` + `.pdf`: draft strategy card with theme-specific narrative.
   - `web.html`: self-contained HTML, **v1.2 features** (dark mode, Chart.js, hover tooltips, click-to-jump, embedded report+strategy reader, download dropdown, print fab).
   - `text.md`: pure-text version (no images, no JS, no CDN).
   - `data.json`: raw data (basket flow + top-5 tech + flow_ts + global context + theme config).

10. **Package into ZIP**
    - Run directory: `deliverables/{theme}/{today_bj}/{run_ts}/` containing the 9 deliverables.
    - Per-day ZIP: `deliverables/{theme}/{today_bj}.zip`. Structure:
      ```
      manifest.json
      daily-final/
        report.md
        report.html
        report.pdf
        strategy-card.md
        strategy-card.html
        strategy-card.pdf
        web.html
        text.md
        data.json
      runs/{run_ts_1}/... (all 9 files)
      runs/{run_ts_2}/...
      runs/{latest_run}/
      ```
    - `manifest.json` schema: `{skill: "basket-analysis", skill_version: "1.2", theme: {name, name_en}, session_id, generated_at, trading_day, is_market_close, data_as_of, is_final, basket_coverage: {total, money_flow_pulled, kline_pulled_top5}, files: [...], runs_in_zip: [...]}`. v1.2 reads `data_as_of` and `is_market_close` from data.json (no hardcoding).
    - `theme` field in data.json: `{name, name_en, description, basket: {size, source}, trigger_variables: [{label, current, threshold, status}], global_context: {...}}`. This is what the scripts read for theme-specific labels.

## v1.2.1 — Data-fetch retry logic (`scripts/retry.py`)

Sandbox reality: efinance rate-limits aggressively (~70-80% success typical), Tencent K-line SSL handshakes fail intermittently, chrome --print-to-pdf hits dbus/GPU noise, web_search hits 429. v1.2.1 adds a unified `retry.py` module that all data-fetch points use.

- **`retry_with_backoff(fn, max_attempts=3, initial_delay=2, backoff_factor=2, max_delay=30, jitter=0.3)`** — generic decorator. Retries on `URLError`, `HTTPError`, `TimeoutError`, `ConnectionError`, `OSError`, `subprocess.TimeoutExpired`. Non-retriable exceptions (`KeyError`, `ValueError`, `TypeError`) raise immediately.
- **`retry_money_flow(codes, db_path, max_attempts=2, initial_delay=5)`** — best-effort pull. Skips already-cached codes (idempotent). Auto-finds `mommy` binary. Returns `{code: bool}` per-code success. Does NOT raise on partial failure.
- **`retry_kline(code, days=60, max_attempts=3)`** — Tencent K-line with retry. Returns closes list or None.
- **`retry_web_search(search_fn, query, max_attempts=3)`** — wraps Mavis `web_search` for 429/5xx.

**Where the script applies retry automatically**:
- `_chrome_to_pdf()` → retries 2x with 3s backoff (dbus/GPU noise)
- `retry_kline()` → built-in (used by agent when fetching K-line via urllib)

**Opt-in retry (env var)**:
- `BASKET_RETRY=1` → re-runs `mommy flows pull --force` for missing theme codes, max 2 attempts, 5s+10s backoff. Use this when first run got < 80% coverage and you want to try harder. Default is OFF (single attempt) for speed.

## Output contract

Always produce (9 deliverables + 1 archive):

1. `deliverables/{theme}/{today_bj}/{run_ts}/report.md` — full report, ≥ 30 KB
2. `deliverables/{theme}/{today_bj}/{run_ts}/report.html` — rendered HTML
3. `deliverables/{theme}/{today_bj}/{run_ts}/report.pdf` — printed PDF (~1 MB)
4. `deliverables/{theme}/{today_bj}/{run_ts}/strategy-card.md` — draft card, ≥ 8 KB
5. `deliverables/{theme}/{today_bj}/{run_ts}/strategy-card.html` — rendered HTML
6. `deliverables/{theme}/{today_bj}/{run_ts}/strategy-card.pdf` — printed PDF (~700 KB)
7. `deliverables/{theme}/{today_bj}/{run_ts}/web.html` — self-contained HTML, v1.2 features
8. `deliverables/{theme}/{today_bj}/{run_ts}/text.md` — pure-text version
9. `deliverables/{theme}/{today_bj}/{run_ts}/data.json` — raw data
10. `deliverables/{theme}/{today_bj}.zip` — per-day archive

The data timestamp inside each report/webpage header must be `as of {today_bj} close (Beijing)` (or `mid-day (Beijing)`).

## Failure handling

- **efinance K-line rate limit (sandbox)**: fall back to Tencent raw HTTP API. Pattern: `{market}{code},day,,,60,qfq` on `http://web.ifzq.gtimg.cn/appstock/app/fqkline/get`. 1.3s/code, 100% success. SSL timeouts: retry up to 3 times with 2s sleep.
- **TencentAdapter.get_bars is a stub** in mommy-chaogu v1.4.0 (returns `[]`). Do not use it; always call the raw API.
- **efinance money flow rate limit** for any theme basket: retry up to 2 times; if still < 60% coverage, log it explicitly and continue.
- **No LLM key**: that's expected and the script is designed to run without one.
- **web_search empty** for a Top-5 code: mark that code as `fundamentals: unavailable`; do not invent PE/ROE.
- **Multiple same-day runs**: ZIP overwrites the same-day file; old run directories preserved. `daily-final/` repointed to latest run.
- **Theme not in references/themes/**: fall back to `food-security` config, or stop and ask user. Default: stop + ask.

## Examples

**Input**: "做粮食安全分析"
**Theme loaded**: `food-security`
**Output**: 9 files in `deliverables/food-security/2026-08-19/{run_ts}/` + `food-security/2026-08-19.zip`.

**Input**: "分析半导体板块"
**Theme loaded**: `semiconductor` (uses `mommy semicon` template, 106 stocks, with semiconductor-specific 4 variables: 费半 SOX 同比 / 存储芯片现货价 / 国内晶圆厂稼动率 / 北向资金科技净流入)
**Output**: 9 files in `deliverables/semiconductor/2026-08-19/{run_ts}/` + ZIP.

**Input**: "煤炭今天怎么样"
**Theme loaded**: `coal` (15-stock manual basket, 4 variables: 焦煤价格 / 秦皇岛港库存 / 火电发电量同比 / 煤炭板块 PE 分位)
**Output**: 9 files + ZIP.

**Adding a new theme**:
1. `cp references/themes/_template.md references/themes/innovative-drugs.md`
2. Fill in: basket source, 4 trigger variables + their search queries, global context queries
3. Run skill with theme name

## See also

- `references/themes/food-security.md` — 粮食安全 config (the original "food-security-analysis" use case)
- `references/themes/_template.md` — blank template for new themes
- `references/data_sources.md` — A-share + global macro + Tencent K-line API
- `references/output_format.md` — ZIP structure + manifest schema
- `references/themes_api.md` — how to add a new theme programmatically
