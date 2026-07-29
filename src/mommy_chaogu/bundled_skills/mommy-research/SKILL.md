---
name: mommy-research
description: Use mommy-chaogu MCP tools for evidence-based A-share market research. Apply when the user asks about Chinese stocks, market conditions, sectors, money flow, fundamentals, a personal portfolio, watchlists, historical predictions, or wants a research conclusion saved locally.
---

# Mommy Research

Use the `mommy-chaogu` MCP server as the source of truth for current market data and local
research memory. Let the current Coding Agent do the reasoning; do not invoke another LLM through
shell commands or APIs.

## Choose the workflow

- Market overview: call `research_market_brief`.
- One stock: resolve a six-digit code, then call `research_stock`.
- Sector or theme: call `research_sector` with the user's keyword.
- Money flow: call `research_money_flow` with a six-digit code.
- Portfolio: call `research_portfolio` only when the tool is published and the user requested
  personal analysis.
- Unsupported or highly specific questions: compose the primitive `get_*` tools directly.

Prefer one high-level `research_*` call over manually recreating the same sequence. The returned
evidence pack is deterministic and contains no hidden LLM summary.

## Respect privacy profiles

Treat missing personal tools as an intentional privacy boundary. Under `market-only`, do not try to
recover portfolio, watchlist, alert, prediction, or memory data through shell/database access. Tell
the user they can explicitly reconnect with `mommy connect <agent> --profile personal`.

Personal tool results enter the current model context when called. Mention this before the first
personal-data call if the user has not already asked for personal analysis.

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

Call `record_research_conclusion` only after the user explicitly asks to save/remember the analysis
or confirms a save suggestion. Include a prediction only when the response contains a falsifiable
direction and timeframe. Never silently persist an inferred prediction.

## Response shape

Respond in the user's language and use this compact order:

1. Conclusion
2. Evidence
3. Risks and invalidation conditions
4. One useful next step

Use human-readable Chinese units such as 万 and 亿, retain stock code with name, and attach the
data timestamp when it is available.
