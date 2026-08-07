# A-share analysis method

## Evidence hierarchy

Prefer current tool evidence in this order:

1. Quote timestamp and price action
2. K-line trend, volume ratio, turnover and volume confirmation
3. Money-flow direction, persistence and bp strength
4. Fundamentals and announcements
5. Historical memory and prior predictions

Historical memory is context, not current evidence. A prior prediction's hit rate calibrates
confidence but does not prove the new thesis.

When personal context is available, keep facts, historical memory, and model inference in
separate sections. Use the subject-specific context returned by `get_memory_context`; do not
request the full portfolio for a single-stock question.

## Money flow

- Compute or use `bp = main net inflow / circulating market cap * 10000`.
- Above 5bp deserves attention; above 10bp is a significant signal.
- Main outflow while price rises can indicate distribution; inflow while price lags can indicate
  accumulation, but label both as inference.
- Require multiple days before calling a flow persistent.
- Do not compare raw inflow amounts across companies with very different market capitalizations.

## Price and volume

- Volume ratio above 2 indicates unusually active trading.
- Turnover above 5% suggests meaningful ownership rotation.
- Rising price with expanding volume is stronger confirmation than rising price with contracting
  volume.
- Falling price with expanding volume is a material risk signal.
- State the observation window; do not describe a 20-day pattern as a long-term trend.

## Sector analysis

- Compare the sector with major indexes and the sector ranking.
- Check breadth: distinguish broad participation from a move driven by one or two leaders.
- List leading and lagging constituents when evidence is available.
- Separate industry facts from theme momentum.

## Portfolio analysis

- Start with total profit/loss only when both position and cost data are present.
- Check single-name concentration, sector correlation and liquidity.
- Do not infer position size, cost basis or return from a watchlist.
- Describe risk contribution before suggesting position changes.

## Output conventions

- Lead with a calibrated conclusion: strong, moderately strong, neutral, moderately weak, or weak.
- Keep factual statements close to their evidence and timestamp.
- Format percentages to two decimals when precision exists.
- Use 万 and 亿 for money amounts.
- Always state contrary evidence and what would invalidate the conclusion.
