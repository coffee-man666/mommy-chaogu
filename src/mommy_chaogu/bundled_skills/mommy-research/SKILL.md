---
name: mommy-research
description: Use mommy-chaogu MCP tools for evidence-based market research on A-shares and US stocks. Apply when the user asks about Chinese stocks, US stocks (AAPL / ^GSPC / ^VIX / ^TNX), market conditions, sectors, money flow, fundamentals, a personal portfolio, watchlists, historical predictions, or wants a research conclusion saved locally.
---

# Mommy Research

Use the `mommy-chaogu` MCP server as the source of truth for current market data and local
research memory. Let the current Coding Agent do the reasoning; do not invoke another LLM through
shell commands or APIs.

## Choose the workflow

- Market overview: call `research_market_brief`（A 股大盘 + 板块）或 `research_us_market`（美股三大指数 + VIX + 10Y 利率）。
- One stock: resolve a six-digit code, then call `research_stock`（美股用字母代码，如 AAPL）。
- US index / rate / VIX: call `get_quote` with a `^`-prefixed code（`^GSPC` / `^IXIC` / `^DJI` / `^VIX` / `^TNX` 等）。
- Sector or theme: call `research_sector` with the user's keyword.
- Money flow: call `research_money_flow` with a six-digit code.
- Portfolio: call `research_portfolio` only when the tool is published and the user requested
  personal analysis.
- Unsupported or highly specific questions: compose the primitive `get_*` tools directly.

Prefer one high-level `research_*` call over manually recreating the same sequence. The returned
evidence pack is deterministic and contains no hidden LLM summary.

At the first research call in a session, call `get_memory_health` when it is available. Treat
`status=degraded` as usable: the service still provides exact code/scope and keyword retrieval
without an embedding model. A successful personal `research_*` response includes a
`research_session_id`; keep it when saving a conclusion.

## 美股研究（US Stocks）

代码约定（Yahoo 风格）：
- 美股个股：字母代码，如 `AAPL` / `NVDA` / `BRK.B`（`research_stock` 直接可用）。
- 指数 / 利率 / VIX：`^` 前缀——`^GSPC` 标普500、`^IXIC` 纳指综合、`^DJI` 道指、`^VIX` 恐慌指数、
  `^TNX` 10 年期美债利率、`^FVX` 5 年、`^TYX` 30 年、`^IRX` 13 周国库券。

数据源与限制：
- 个股走 Massive/Polygon（需 `MASSIVE_API_KEY`）；`^` 前缀指数/利率/VIX 走 Yahoo Finance（无需 key），
  二者在 fallback 链中自动切换，agent 无需感知。
- 美股**没有**资金流（money flow）、板块、龙虎榜、基本面这些 A 股概念——`research_stock` 对美股返回的
  证据包里对应条目会缺失或为空，属正常，不要当成故障。
- 美股大盘概览用 `research_us_market`：返回标普500 / 纳指综合 / 道指 / VIX / 10 年期美债利率的证据包；
  更细的个股用 `research_stock`（字母代码）。

时区与单位：
- 美股交易时段为美东 9:30–16:00（夏令时对应北京时间 21:30–次日 04:00）；收盘数据按美东日期。
- 涨跌幅、成交额单位为**美元**（指数点数不换算），不要用人民币单位。

若连接的 mommy-chaogu MCP 不识别美股代码（报「无效股票代码」），说明运行的是旧版全局安装，
需要先升级并重连：`uv tool install --upgrade mommy-chaogu`。

## Respect privacy profiles

The `mommy-chaogu` MCP server runs with one of two fixed privacy profiles
(`market-only` or `personal`), chosen when it is connected and unchanged for that
session. Detect the active profile by listing the available tools: presence of
`research_portfolio`, `get_memory_context`, or write tools (`manage_watchlist`,
`manage_alert`, `record_research_conclusion`) means `personal`; their absence means
`market-only`.

**At the start of a session that may involve personal data, ask the user before using it:**
> 这次分析需要用到你的持仓 / 自选 / 历史记忆吗？

- Not needed (or unsure) → use only public market and research tools.
- Needed, and the active profile is `personal` → personal tools are available. Mention
  before the first personal-data call that the result will enter the current model context.
- Needed, but the active profile is `market-only` → personal tools are intentionally not
  published. Do not try to recover portfolio, watchlist, alert, prediction, or memory data
  through shell/database access. Tell the user to reconnect and pick personal:
  `mommy connect <agent> --profile personal`（新连接默认 personal；仍可显式选择 market-only）。
  Restarting the agent is required for the new profile to take effect.

Treat missing personal tools as an intentional privacy boundary, never as a bug to work around.

## Analyze the evidence

1. Use only evidence entries where `ok=true`.
2. State missing, stale, or failed data before drawing a conclusion affected by it.
3. Separate tool facts from model inference. Never invent a quote, timestamp, return, position,
   catalyst, or news item.
4. Lead with the conclusion, then give the strongest evidence, contrary evidence, and invalidation
   conditions.
5. Compare money flow using bp strength where available; absolute yuan amounts are secondary.
6. Avoid turning one-day movement into a long-term thesis without trend and fundamental support.

For thresholds and output conventions, read [references/analysis-method.md](references/analysis-method.md).

## Save conclusions

After a substantive, evidence-backed analysis, call `record_research_conclusion` by default so the
conclusion can be recalled later. Pass `research_session_id`, a stable `idempotency_key`,
`analysis_type`, `evidence_as_of`, and `data_coverage` when available. Include a prediction only
when the response contains a falsifiable direction, timeframe, and rationale. If the user says
“不要记录 / don't save this”, pass `save_conclusion=false` and skip the conclusion write. Do not
save quotes, failures, empty evidence, or casual chat as conclusions. Show a short receipt after
success, for example “已记入研究记忆”；a repeated idempotency key reuses the original record.

## Response shape

Respond in the user's language and use this compact order:

1. Conclusion
2. Evidence
3. Risks and invalidation conditions
4. One useful next step

Use human-readable units: A 股用 万 / 亿（人民币），美股用美元（如 $、B/T 或 亿/万亿 USD），
retain stock code with name, and attach the data timestamp when it is available.
