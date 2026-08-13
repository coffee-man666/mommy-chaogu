---
name: mommy-strategy
description: Distill an investment article, report, conversation, or personal method into a clear Strategy Card; revise and save it after explicit approval; reopen it later, apply it to current evidence, or prepare consent-gated monitoring. Use when the user asks to 整理/沉淀/记住/复用 a 投资方法 or strategy, says “按上次的方法看 X”, or wants supported parts of a saved method monitored.
---

# Mommy Strategy

Turn the user's method into a durable, human-readable Strategy Card. Let the current host Agent do
the reading and reasoning. Use `mommy-chaogu` MCP only for validation, local persistence, current
evidence, and supported monitoring; never invoke a second project LLM.

Read [references/card-contract.md](references/card-contract.md) before drafting or saving a card.
Use [references/acceptance-scenarios.md](references/acceptance-scenarios.md) when checking unfamiliar
method types or testing this workflow.

## Choose the path

- New method, article, report, file, URL, or pasted text: follow **Distill a new card**.
- “记住/保存这套方法”: finish the readable draft and approval steps before `strategy_save`.
- “列出/打开我保存的方法”: call `strategy_list`, then `strategy_get` as needed.
- “按这套方法看 X”: follow **Apply a saved card today**.
- “帮我监控”: follow **Prepare and activate a monitor**.
- “归档/删除这套方法”: explain that archive keeps history and existing alerts, then request
  confirmation before `strategy_archive`.

If `strategy_*` tools are absent, the connection is `market-only` or an older installation. The
Agent may still draft a card in the current conversation, but must not save it through shell or
direct database access. Explain that local strategy storage needs a `personal` connection. Run
`mommy agent plan --host <agent> --profile personal --json`, show the changed privacy scope, and
wait for approval before `mommy agent connect`; restart the Agent after a successful connection.

## Distill a new card

1. Read only material the user supplied or authorized the host Agent to access. For a URL, use the
   host's normal browsing capability; do not build or invoke a separate crawler.
2. Record an honest source reference and one to five short, decision-relevant excerpts. Hash content
   only when the host actually has the hashed bytes/text; otherwise omit both `content_hash` and
   `hash_scope`.
3. Separate what the source says from the Agent's interpretation. Preserve the user's original
   intent and terminology; do not replace their method with an easier technical proxy.
4. Draft the card in the user's language using this visible order:

   - 名称
   - 来源与关键原文
   - 用户原始目标
   - 方法摘要
   - 适用对象/场景
   - 观察、进入、退出、风险与失效条件
   - 每项条件：`可自动检查` / `需人工判断` / `当前不可用`，附原因
   - 假设、限制和仍不确定的地方

5. Ask at most one grouped clarification round, and only for ambiguities that change meaning. Do
   not ask the user about schemas, databases, indicators implementation, backtest configuration, or
   engineering choices.
6. Apply the user's natural-language corrections and show the whole final readable card again.
7. Ask two separate questions in plain language:

   - “这张卡是否忠于你的原意？”
   - “是否要把这个确认版本保存在本机，方便以后复用？”

Do not show JSON unless the user asks. Do not call `strategy_save` when the user only confirms that
the interpretation is accurate; saving requires an explicit request to save.

## Save or revise a card

Call `strategy_save` only after the final readable card was shown and the user explicitly agreed to
save it. Set `user_confirmed=true` and write a short, factual `confirmation_note`; never manufacture
consent.

For a revision, first call `strategy_get`. Pass its `strategy_id` and current `version` as
`expected_version`, summarize the user's actual correction in `revision_note`, show the revised
card, and obtain a new save confirmation. If the tool reports a version conflict, reopen the latest
card and show the difference before asking again.

After success, give a short receipt containing the readable title, strategy ID, version, and local
save status. If the tool says `reused=true`, tell the user the existing copy was reused instead of
claiming a new card was created.

## Apply a saved card today

1. Resolve the intended saved card with `strategy_list` / `strategy_get`; ask the user only if
   multiple cards remain plausible.
2. Call `strategy_prepare_application` with the strategy ID and stock code.
3. Call the exact `evidence_request` returned by that tool, normally `research_stock`. The prepare
   response is a checklist, not market evidence.
4. Evaluate every condition against only successful, time-stamped evidence. Use exactly one of:

   - `满足`
   - `不满足`
   - `无法判断`

5. Treat `manual` and `unavailable` honestly. Raw bars do not automatically make a visual pattern,
   narrative judgment, or unintegrated algorithm `supported`. Say what the user can inspect or what
   data/tool is missing.
6. Respond with this compact shape:

   - 当前结论（not a profit promise）
   - 逐条件结果 + evidence timestamp/source
   - 无法判断的条件 and why
   - 最重要的 next observation

Do not silently change thresholds, substitute SMA for EMA/channel logic, run a backtest, or infer
historical profitability. Strategy Distillation reuses the user's method against current evidence;
it does not validate that the method makes money.

## Prepare and activate a monitor

Only a condition carrying an existing `monitor_rule` can become an automatic monitor.

1. Call `strategy_prepare_monitor` with strategy ID, condition ID, code, and optional name.
2. Show the candidate in ordinary language: exact trigger, threshold, subject, related strategy
   condition, source, and why it is supported.
3. Ask a new, explicit question such as “要按这个条件启用本地提醒吗？” The earlier card-save
   confirmation never authorizes monitoring.
4. Only after “yes”, call `strategy_activate_monitor` with `user_confirmed=true` and a factual
   `confirmation_note`.
5. Return the alert ID, trigger explanation, linked strategy/version, and how to view or remove it.

If preparation rejects a condition, keep it manual/unavailable. Never translate it into one of the
four available price/change rules merely to make automation possible.

## Trust boundaries

- Never save an unconfirmed draft or activate an unconfirmed monitor.
- Never bypass a missing personal tool by reading SQLite files directly.
- Never claim a source hash covers a full report when only an excerpt was available.
- Never label a condition supported just because related raw data exists.
- Never present Strategy Distillation as backtesting, strategy validation, auto-recommendation, or
  trade execution.
- Lead with what the user can do now; keep schema and implementation details behind the Agent.
