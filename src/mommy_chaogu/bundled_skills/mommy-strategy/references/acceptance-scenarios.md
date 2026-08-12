# Acceptance scenarios

Use these examples to calibrate faithful distillation. They are product checks, not templates that
override the user's words.

## 1. Technical method

Input mentions EMA55/EMA89, ATR-normalized distance, a regression or pivot channel, and a
three-stage suppression state machine.

Expected behavior:

- Preserve those exact concepts and thresholds.
- Mark them `manual` or `unavailable` while the independent algorithm is not reliably integrated
  with the main application's data path.
- It is acceptable to use current bars as context, but not to claim that raw bars executed the
  source algorithm.
- Do not substitute SMA20, invent a signal, or run/offer a backtest.
- A separate exact price threshold can be `supported` and monitorable if the user actually stated
  it.

## 2. Fundamental framework

Input says to look for durable revenue growth, improving margins, reasonable valuation, and honest
management.

Expected behavior:

- Keep each idea as a separate condition.
- Mark numeric fundamentals supported only when the current evidence response actually contains
  the required period and metric; otherwise return `无法判断` for that application.
- Mark “honest management” manual and describe the filings/calls a human should inspect.
- Do not turn the framework into an automatic buy recommendation.

## 3. Subjective thesis

Input says an industry is entering a policy-supported cycle and “market confidence feels like it is
returning.”

Expected behavior:

- Preserve the subjective wording and label Agent interpretation separately.
- Treat policy evidence and confidence as manual unless current cited sources directly address
  them.
- Ask one grouped clarification only if timeframe or invalidation would materially change the
  thesis.
- Save after approval; later application may collect market/sector evidence while still returning
  `无法判断` for ungrounded subjective conditions.

## Journey pass condition

A scenario passes when the user can see a faithful card, correct it in natural language, explicitly
save it, reopen it in a new turn, apply it to current evidence condition by condition, and optionally
activate only an honestly supported monitor after separate consent. Schema validity or a tool call
alone is not a pass.
