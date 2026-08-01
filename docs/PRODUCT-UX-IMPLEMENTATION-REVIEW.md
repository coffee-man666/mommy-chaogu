# Product UX Implementation Review

> Initially reviewed commit: `a3f58ea7291428270bec94d4c6b1370d58481372`
> Follow-up reviewed commit: `9c0fd0bafda3cac8756fa549c79fcff0abbd461d`
> Review date: 2026-07-31
> Related plan: [`PRODUCT-UX-EXECUTION-PLAN.md`](PRODUCT-UX-EXECUTION-PLAN.md)
> Follow-up result: **Request changes** — several concrete fixes landed, but CI is red and two release-blocking behavior regressions remain.
> Current working tree: **release blockers remediated locally** — full local gates pass; remaining P1–P4 product deliverables are still open.

## 1. Executive summary

The commit establishes the intended navigation direction and introduces useful foundations:

- `/api/overview` aggregation
- a compact Today page
- Follow and trading-style UI
- stock-detail tabs and prediction links
- proactive Weixin notification plumbing

However, the implementation does not yet meet several acceptance criteria in the execution plan. The packaged frontend is stale, notification delivery can repeatedly spam the same signal, overview failures are not fully isolated, and several P2–P4 capabilities are represented only by UI shells or local browser state.

The two release blockers are:

1. Synchronize the current frontend build into the Python package.
2. Add persistent notification deduplication and move blocking Weixin delivery out of the asyncio poller.

## 2. Findings

### P0 — Packaged App still serves the old frontend

**Evidence**

- `src/mommy_chaogu/web/app.py:58-72` documents that installed wheels fall back to `src/mommy_chaogu/web/static`.
- `src/mommy_chaogu/web/static/index.html:50` references `index-C0nx-0V1.js`.
- `web/dist/index.html:50` references the newer `index-CVPzl8QI.js`.
- Commit `a3f58ea` contains no changes under `src/mommy_chaogu/web/static/`.

**Impact**

Source checkouts may display the new P1–P4 interface because `web/dist` is present, while an installed wheel or `uv tool install` falls back to the older P0 bundle. Users can therefore install the new Python code but still see the old Web App.

**Recommended fix**

- Run the production frontend build.
- Synchronize `web/dist/` into `src/mommy_chaogu/web/static/` with deletion of obsolete hashed assets.
- Add a CI assertion that both directories are identical after a build.

### P1 — Weixin notifications can repeat every polling interval

**Evidence**

- `src/mommy_chaogu/web/background.py:146-153` calls `send_signal_notifications()` on every polling tick whenever signals exist.
- The default polling interval is 5 seconds.
- `src/mommy_chaogu/channels/notify.py:42-49` creates a new in-memory `seen` set for each call.
- Existing tests verify duplicates within one call, but not repeated calls or repeated polling ticks.

**Impact**

A signal that remains above its threshold can be sent repeatedly, potentially every 5 seconds. The delivery path also ignores followed themes, severity preferences, reminder times, and previous notification state.

**Recommended fix**

- Persist a notification fingerprint keyed by signal identity and meaningful trigger state.
- Send only on state transition, material value change, or expiry of a deliberate cooldown.
- Apply severity, theme, stock, and reminder-time preferences before delivery.
- Add tests covering consecutive polling ticks and process restarts.

### P1 — Blocking Weixin requests run inside the asyncio poller

**Evidence**

- `BackgroundService._tick()` is asynchronous.
- It calls synchronous `send_signal_notifications()` directly.
- `WeixinClient.send_text()` uses blocking `requests` calls with connection/read timeouts of 8 and 20 seconds.

**Impact**

One slow Weixin request can block the event loop and delay quote WebSockets, signal broadcasts, subsequent polling, and graceful shutdown. Multiple signals are sent sequentially, multiplying the delay.

**Recommended fix**

- Dispatch blocking delivery through `asyncio.to_thread()` or a bounded asynchronous notification queue.
- Limit concurrency and preserve delivery ordering where needed.
- Record failures without blocking quote and signal broadcasts.

### P1 — `/api/overview` does not fully isolate block failures

**Evidence**

- `src/mommy_chaogu/web/routes/overview.py:306` invokes `_build_watchlist()` without an isolation boundary.
- `src/mommy_chaogu/web/routes/overview.py:316` invokes `_build_portfolio()` without an isolation boundary.
- `store.list_entries()`, `store.list_positions()`, snapshot conversion, and response construction can raise outside the current local `try` blocks.
- Tests cover index failure but not watchlist, portfolio, theme-schema, or malformed-snapshot failure.

**Impact**

A failure in one block can still return HTTP 500 for the entire Today page, contradicting the documented `ok / stale / unavailable` contract.

**Recommended fix**

- Isolate each block at the aggregation boundary.
- Convert failures into a typed `unavailable` block with a safe message.
- Add failure-injection tests for every block.
- Log the original exception with block context.

### P1 — Followed themes can disappear from Today

**Evidence**

- `src/mommy_chaogu/web/routes/overview.py:241-249` truncates the global theme list to four items.
- `web/src/pages/today/index.vue:35-40` filters that already-truncated list using locally followed IDs.

**Impact**

If a user follows a theme outside the backend's first four themes, it cannot appear on Today. In some combinations, the Follow page shows a theme as followed while Today shows no corresponding card.

The overview theme contract also lacks the planned overall performance, leader, laggard, and anomaly fields.

**Recommended fix**

- Return all lightweight theme summaries and apply the four-item limit after preference filtering, or pass followed IDs to a server-side preference-aware endpoint.
- Add performance, leader/laggard, anomaly, and `as_of` fields.
- Test a followed theme beyond the first four source items.

### P1 — Stock prediction filtering happens after the global limit

**Evidence**

- `src/mommy_chaogu/web/routes/agent.py:205` loads the latest `limit` predictions globally.
- `src/mommy_chaogu/web/routes/agent.py:206-207` then filters those rows by stock code.

**Impact**

A stock with valid historical predictions can incorrectly show an empty decision history if its predictions are older than the latest global rows.

**Recommended fix**

- Add a tracker query that applies `WHERE code = :code` before `ORDER BY created_at DESC LIMIT :limit`.
- Return a total matching the filtered dataset rather than the truncated in-memory result.
- Add a test with more than `limit` global predictions and an older matching stock prediction.

### P1 — Trading style is injected as user content

**Evidence**

- `web/src/pages/chat/index.vue:222-224` prefixes the style hint to the user's message.
- The enriched message is passed into workflow routing and Agent streaming.
- Server-side history can therefore store the style instruction as if the user wrote it.

**Impact**

- Workflow matching receives altered user input.
- Hidden implementation text can reappear through server conversation history.
- Style policy has weaker semantics than a system/developer context and can conflict with the user's actual request.
- This violates the plan's requirement not to expose prompt or model mechanics.

**Recommended fix**

- Send the original message unchanged.
- Represent style as validated structured metadata or server-side session preference.
- Apply it while constructing system context, not inside user content.
- Keep stored user history identical to visible user input.

### P1 — P3 preferences do not affect the promised product surfaces

**Evidence**

- Trading style is stored only in browser `localStorage`.
- Today does not read the style setting.
- Backend notification delivery cannot access browser-local style, theme, or reminder preferences.
- No default backtest integration reads the selected preset.
- Settings copy says the choice affects homepage sorting, although that behavior is not implemented.

**Impact**

P3 currently changes only an Agent prompt prefix. It does not satisfy the plan's homepage-priority, reminder-priority, explanation, undo, or default-backtest requirements.

**Recommended fix**

- Define a server-owned preference schema.
- Make Today ordering and notification selection consume the same schema.
- Explain why prioritized items moved.
- Provide an explicit restore-default action.
- Keep raw market values identical across styles.

### P2 — “My” is not discoverable on mobile

**Evidence**

- `web/src/App.vue:12-18` defines only Today, Follow, Portfolio, and Ask AI in mobile navigation.
- The plan expects My to be available through a header avatar.
- The new Today header contains only its title and refresh button.

**Impact**

Mobile users cannot discover AI reconfiguration, Weixin reconnection, service status, or trading-style settings without manually entering `/my`.

**Recommended fix**

- Add a visible, accessible `RouterLink` avatar/settings entry to the mobile page header.
- Preserve the four-tab bottom navigation.
- Add a mobile E2E test that reaches My from Today.

### P2 — Initial request-count acceptance criterion is not met

**Evidence**

On a normal startup:

1. `App.vue` requests authentication status.
2. `App.vue` requests setup status.
3. Today requests `/api/overview`.

The plan permits no more than two initial requests: authentication plus overview.

**Impact**

The initial page adds an extra serial bootstrap round trip before content is mounted.

**Recommended fix**

- Include the minimal `llm_configured` bootstrap state in the authentication response, or combine authentication/setup bootstrap into one endpoint.
- Keep sensitive setup detail behind the existing protected setup endpoint.

### P2 — Stock-detail tabs still load all hidden resources eagerly

**Evidence**

- `web/src/pages/detail/index.vue:402-407` loads quote, bars, funds, and predictions during initial mount.
- Bars are awaited before funds and prediction calls begin.
- The user may never open the corresponding tabs.

**Impact**

The tabbed UI reduces visual density but not network or computation cost. This works against the product goal of reducing unused features and resource consumption.

**Recommended fix**

- Load the quote and overview data initially.
- Lazy-load chart, funds, and decision records on first tab activation.
- Cache loaded tabs for subsequent navigation.
- Reflect the active tab in the URL for stable deep links.

### P2 — Navigation interactions are not consistently semantic or keyboard accessible

**Evidence**

- `web/src/pages/today/index.vue:201-205` navigates from a clickable `<tr>` without keyboard handling.
- `web/src/pages/follow/index.vue:112-117` and `160-165` navigate from clickable card containers.
- `web/src/pages/follow/index.vue:163` uses `transition-all`.
- Several buttons call `router.push()` for navigation where a `RouterLink` would preserve normal link behavior.

**Impact**

Keyboard users cannot reliably open these destinations, and link actions lose expected browser behavior such as Cmd/Ctrl-click and opening in a new tab.

**Recommended fix**

- Use semantic `RouterLink` elements for navigation.
- Keep follow/unfollow as separate buttons.
- Avoid nested interactive elements.
- Replace `transition-all` with explicit transitioned properties.

## 3. Missing or incomplete plan deliverables

The following execution-plan deliverables are not yet implemented completely:

- Unified built-in theme and custom-basket model
- Basket weighting, fixed ordering, hiding, and follow state
- Theme performance, leader/laggard stocks, anomalies, and timestamps
- Holding profit/loss context in stock detail
- Backtest entry and stable deep link from a stock
- Conditional prediction attachment only when an Agent answer creates a prediction
- Prediction freshness and human-readable evidence coverage
- Style-driven Today ordering, reminder priority, and backtest defaults
- Preference-aware Weixin notification selection and durable deduplication
- Mobile and desktop acceptance tests for the new Today/Follow/detail flows

## 4. Documentation consistency

`PRODUCT-UX-EXECUTION-PLAN.md` currently says P1–P4 are implemented, but its final recommendation still says to implement the Overview contract and Today page.

Until the release blockers and acceptance gaps are resolved, recommended status wording is:

> P0 implemented; P1–P4 prototype implemented, acceptance and integration incomplete.

## 5. Recommended remediation order

1. Synchronize and commit packaged frontend assets; add CI drift detection.
2. Stop repeated Weixin notifications and remove blocking network calls from the poller.
3. Make `/api/overview` genuinely failure-isolated.
4. Fix theme selection and stock prediction filtering.
5. Move preferences to a shared server-side model and apply them to Today, Agent, and notifications.
6. Add the mobile My entry and semantic navigation.
7. Complete theme/basket performance, holding context, prediction coverage, and backtest navigation.
8. Add acceptance-level E2E tests and update the plan status only after they pass.

## 6. Review scope

- Reviewed the latest local commit `a3f58ea` against the execution plan.
- Inspected backend aggregation, notification flow, Agent prediction filtering, frontend navigation, Today, Follow, stock detail, trading-style handling, and packaged static assets.
- No implementation files were changed as part of this review.

## 7. Follow-up review of `9c0fd0b`

### 7.1 Executive verdict

The follow-up commit correctly fixes or materially improves several original findings:

- The production frontend is synchronized into the Python package, and the existing CI drift gate now passes.
- Stock prediction filtering is performed in SQL before `LIMIT`.
- The auth bootstrap response now avoids the extra setup-status request.
- A mobile “My” entry is present on Today.
- Today and Follow use semantic links for the main navigation paths.
- Stock-detail secondary data is no longer fetched eagerly on first mount.
- Watchlist, portfolio, and signal aggregation now have outer failure boundaries.

It does **not** address all P0/P1/P2 findings as the commit subject claims. The current commit is not release-ready because:

1. GitHub Actions is failing.
2. Trading style replaces the Agent's complete base system prompt and memory context.
3. Weixin delivery can still repeat indefinitely when its new relative dedup file cannot be persisted.

### 7.2 Resolution matrix

| Original finding | Follow-up status | Review note |
|---|---|---|
| Packaged frontend stale | **Resolved** | `web/dist` and packaged static are identical; the existing CI drift assertion passes. |
| Weixin repeats every poll | **Partially resolved** | Persistence exists, but its default path is cwd-relative and the fingerprint suppresses every same-rule state change for an entire day. |
| Blocking Weixin request in poller | **Partially resolved** | HTTP runs in a thread, but `_tick()` still awaits all sends before broadcasting the current quote/signal update. |
| Overview block isolation | **Partially resolved** | Watchlist, portfolio, and signals are isolated; malformed index/theme mapping can still escape as HTTP 500. |
| Followed theme disappears | **Partially resolved** | Backend truncation is removed, but the followed branch no longer enforces the planned maximum of 4, and theme decision fields remain absent. |
| Prediction filter after limit | **Core fix resolved** | `WHERE code` now precedes `LIMIT`; filtered total semantics and regression coverage remain incomplete. |
| Trading style injected as user content | **Regressed differently** | Visible user text is clean, but style now replaces the entire system prompt. |
| P3 preferences not wired | **Open** | Copy was narrowed to match reality; shared preferences and product effects are still absent. |
| Mobile My undiscoverable | **Resolved for Today** | Today has an accessible avatar link; no cross-page mobile header pattern yet. |
| Initial request count | **Resolved** | Current backend requires auth status plus overview on the normal first view. |
| Detail resources eagerly loaded | **Partially resolved** | First mount is lazy; changing stock while a secondary tab is active leaves the new stock's tab unloaded. |
| Navigation semantics/accessibility | **Partially resolved** | Main click navigation uses links, but focus treatment and full-card affordance remain inconsistent. |

## 8. Follow-up findings

### P0 — CI is red on the reviewed commit

**Evidence**

- GitHub Actions run `30686992603` concludes `failure` for commit `9c0fd0b`.
- Both Python 3.12 and Python 3.13 backend jobs fail at the Ruff format step.
- `uv run ruff format --check .` reports:
  - `src/mommy_chaogu/channels/notify.py`
  - `src/mommy_chaogu/web/routes/overview.py`
  - `tests/test_web/test_overview.py`
- The Frontend job fails at Browser smoke.
- Local Playwright reproduction: **3 failed, 5 passed, 1 skipped**.
- The failing E2E tests still expect the pre-redesign conversation-first IA, old navigation labels/counts, and the old mobile context trigger.

**Impact**

The release gate is failing, and the acceptance suite no longer verifies the product that is actually shipped. Passing unit tests cannot substitute for updated Today/Follow/detail navigation acceptance tests.

**Required fix**

- Format the 3 reported Python files.
- Rewrite the 3 obsolete Playwright flows around the current IA.
- Add direct acceptance coverage for Today → theme → stock, Today → My on mobile, lazy detail tabs, and the 2-request bootstrap contract.
- Keep screenshots opt-in, but make the behavior assertions mandatory.

### P0 — Trading style replaces the Agent's base contract

**Evidence**

- `src/mommy_chaogu/web/routes/agent.py:162-168` passes `style_hint` as `system_override`.
- `src/mommy_chaogu/web/routes/ws.py:205-213` does the same for streaming chat.
- `src/mommy_chaogu/agent/service.py:269-275` assigns `system_prompt = system_override` whenever it is non-empty.
- This bypasses both `SYSTEM_PROMPT` and `MemoryService.get_context()`.
- The WebSocket path accepts an unbounded, unvalidated JSON value for `style_hint`; REST only constrains its string length.
- No test asserts that the base prompt, tool behavior, memory context, and exact visible user message are all preserved together.

**Impact**

Every normal Web chat sends the default “balanced” style hint, so the Agent can lose its core investment-research instructions, tool-use contract, safety framing, and injected memory. An authenticated WebSocket client can also supply arbitrary replacement system content.

**Required fix**

- Send a validated preset ID (`conservative | balanced | aggressive`), not prompt text supplied by the browser.
- Resolve the preset on the server.
- Extend the normal system-context builder with a clearly delimited preference section; never use `system_override` for this feature.
- Apply the same validation and construction path to REST and WebSocket.
- Add service-level and route-level regression tests proving the base prompt and memory remain present while user history remains unchanged.

### P1 — Weixin dedup persistence can fail in installed deployments

**Evidence**

- `src/mommy_chaogu/channels/notify.py:27` hardcodes `Path("data/weixin_pushed.json")`.
- This bypasses `MOMMY_DATA_DIR`, the installed-app user data directory, and the app's configured database root.
- `mark_pushed()` runs only after `send_text()` succeeds.
- `_save()` raises on an unwritable cwd; the outer send loop catches that as a send failure after the message has already been delivered.
- The next polling tick creates a fresh deduper, sees no persisted key, and sends the same message again.

**Impact**

The original notification-spam blocker can recur when the installed service starts from a read-only or changing working directory. It can also leave stray `data/` directories outside the configured application data root.

**Required fix**

- Resolve the dedup path once during app startup from the configured data/database root and inject a long-lived deduper or notification service into `BackgroundService`.
- Make persistence failure explicit and observable; do not report a successfully delivered message as unsent.
- Add tests for an unwritable destination, configured data roots, and a fresh process instance.

### P1 — Weixin delivery still delays the current broadcast and over-deduplicates events

**Evidence**

- `src/mommy_chaogu/web/background.py:152-154` awaits the thread before quote and signal broadcasts at lines 158-162.
- Signals are delivered sequentially with a per-message read timeout of up to 20 seconds.
- The fingerprint is only `code | rule_id | UTC date`; trigger state, severity, value movement, and clear/retrigger transitions are ignored.

**Impact**

The event loop is no longer blocked, but subscribers can still receive the current market update only after slow notification delivery finishes. Conversely, a genuinely new critical occurrence of the same rule is suppressed for the rest of the UTC day.

**Required fix**

- Broadcast the current snapshot/signals before notification I/O.
- Move delivery to a bounded queue with a single worker, explicit timeout, and shutdown behavior.
- Define a fingerprint/cooldown policy around event identity and meaningful state transition, rather than “one code-rule per day”.
- Apply severity and preference filtering before enqueueing.

### P1 — Overview isolation still has schema escape paths

**Evidence**

- `src/mommy_chaogu/web/routes/overview.py:58-70` protects only the index fetch; index response mapping is outside the `try`.
- `src/mommy_chaogu/web/routes/overview.py:229-249` protects theme service loading; dictionary access and schema construction are outside the `try`.
- `get_overview()` directly calls both helpers without an aggregation-boundary catch.
- New tests cover watchlist, portfolio, and a monkeypatched signals builder, but not malformed index/theme rows.

**Impact**

A malformed upstream index or bundled theme record can still turn the whole Today endpoint into HTTP 500, contrary to the block-level contract.

**Required fix**

- Put every block behind the same aggregation-boundary isolation helper.
- Treat fetch, transformation, and response validation as one block operation.
- Add malformed-row and schema-validation failure injection tests for indexes and themes.

### P1 — Followed-theme limit and theme summary contract remain incomplete

**Evidence**

- `web/src/pages/today/index.vue:36-41` limits the default list to 4 but returns every followed theme without `.slice(0, 4)`.
- Overview themes still expose only ID, name, description, and stock count.
- The planned performance, leader, laggard, anomaly, reason, and freshness fields are absent.

**Impact**

Following many themes can make Today expand beyond its compact one-screen purpose. The section still behaves like a directory of themes rather than a quick answer to “关注方向今天怎么样”.

**Required fix**

- Define an explicit ordering policy and apply the 4-item limit after filtering.
- Add the decision summary fields before considering this P1 block complete.
- Cover a followed item beyond the source's first 4 and more than 4 followed items.

### P2 — Detail lazy loading breaks when changing stocks on the same active tab

**Evidence**

- `web/src/pages/detail/index.vue:405-418` resets `loadedTabs` when `props.code` changes.
- It reloads only the quote and does not call `ensureTabLoaded(mainTab.value)`.
- Because `mainTab` itself did not change, its watcher does not fire again.
- Active tab state is still not represented in the URL.

**Impact**

If a user is on 走势、资金, or 决策记录 and navigates to another stock through the code input, the tab remains selected but shows empty/stale state until the user switches away and back.

**Required fix**

- After resetting for a new code, load the current active tab.
- Key or dispose chart state by stock code where necessary.
- Synchronize the active tab with a query parameter and add a navigation regression test.

### P2 — Prediction query contract lacks verification and an untruncated total

**Evidence**

- `PredictionTracker.by_code()` correctly applies SQL filtering before `LIMIT`.
- `/api/agent/predictions` still returns `total = len(rows)`, which is only the returned page size.
- `_FakeTracker` in `tests/test_web/test_agent_routes.py` does not implement `by_code()` and no endpoint test exercises `?code=`.
- No tracker test proves an older matching prediction survives more than `limit` newer global rows.

**Impact**

The original visible bug is likely fixed, but pagination/total semantics are misleading and the exact regression can return unnoticed.

**Required fix**

- Add a code-filtered count query or explicitly rename/document the field as returned count.
- Add tracker and route regression tests using more than `limit` global predictions.

### P2 — Navigation semantics improved, but interaction affordances remain inconsistent

**Evidence**

- Follow cards animate border/shadow/opacity on hover, but only the small title text is a link.
- Several newly added raw `RouterLink` and button controls lack an explicit visible `focus-visible` state.
- Decorative Lucide icons in the changed views are not consistently marked `aria-hidden="true"`.
- Dead imperative navigation helpers/imports remain in Today and Follow.

**Impact**

The semantic-link issue is substantially improved, but keyboard visibility and the clickable area do not consistently match the visual affordance.

**Required fix**

- Make the intended card content one semantic link without nesting the follow action.
- Add consistent focus-visible styling and mark decorative icons hidden from assistive technology.
- Remove dead router helpers/imports and add keyboard navigation checks.

## 9. Verification performed for the follow-up review

- Full offline Python test suite: **passed**.
- Ruff lint on changed source/test files: **passed**.
- Strict mypy over 174 source files: **passed**.
- Vue typecheck: **passed**.
- Vitest: **51 passed**.
- Production build: **passed**.
- `web/dist` versus packaged static: **identical**.
- Ruff format check: **failed; 3 files require formatting**.
- Playwright: **3 failed, 5 passed, 1 skipped**.
- GitHub Actions run `30686992603`: **failed**; backend format, frontend browser smoke, and release gate are red.

The passing suites do not cover the style-system-prompt regression, malformed Overview rows, code-filtered prediction regression, or same-tab stock navigation case described above.

## 10. Next action plan

### Work package A — Restore a green release gate

1. Run Ruff formatting on the 3 reported files.
2. Replace the 3 obsolete E2E flows with Today-first desktop/mobile journeys.
3. Add assertions for mobile My discovery, semantic theme/stock navigation, and bootstrap request count.
4. Require local `ruff format --check`, Playwright, and the remote release gate to pass before the next commit is called complete.

### Work package B — Fix the two release-blocking runtime paths

1. Replace browser-supplied prompt text with a validated style preset ID.
2. Compose style into the normal server system context without replacing the base prompt or memory.
3. Inject a correctly rooted, long-lived Weixin notification service.
4. Broadcast market updates before queued notification delivery.
5. Add focused tests for both fixes, including persistence failure and REST/WebSocket parity.

### Work package C — Finish the remaining P1 correctness contract

1. Standardize aggregation-boundary isolation for all Overview blocks.
2. Add malformed index/theme tests.
3. Enforce ordered, post-filter 4-theme selection.
4. Implement theme performance, leader/laggard, anomaly, reason, and freshness summaries.

### Work package D — Close P2 interaction gaps

1. Reload the current lazy tab after stock-code changes and deep-link the tab state.
2. Add stock-filtered prediction tests and correct total semantics.
3. Finish focus states, icon accessibility, and full-card link affordances.

### Work package E — Resume the product plan only after A–D

Continue with the still-open product deliverables: unified custom baskets, server-owned preferences, holding context, prediction freshness/coverage, backtest links/defaults, preference-aware Weixin summaries, and mobile/desktop acceptance screenshots.

Do not change the execution-plan status to “P1–P4 complete” after merely making CI green. The next status gate should require all P1 acceptance criteria and the shared preference/notification integration to be demonstrably complete.

## 11. Remediation result in the current working tree

The issues in work packages A–D above have now been implemented locally. This section records the result without rewriting the historical assessment of commits `a3f58ea` and `9c0fd0b`.

### Resolved locally

- Ruff format failures are fixed.
- Playwright now tests the Today-first information architecture instead of the removed conversation-first shell.
- The normal bootstrap is covered as exactly auth status plus Overview, with no setup-status request.
- Trading style is a validated preset ID; server-owned text is appended to the normal system context without replacing the base prompt, memory context, or visible user message.
- REST and WebSocket use the same preset validation behavior; arbitrary WebSocket prompt content is rejected.
- Agent WebSocket rejects non-object payloads and non-string message bodies without terminating the connection.
- Weixin state uses the configured application data root and is injected as a long-lived service dependency.
- Weixin delivery runs through a size-1 worker queue after quote/signal broadcast.
- Notification state is reserved before network delivery, preventing “delivered but not persisted” repeat loops.
- Dedup now supports clear → retrigger and severity escalation instead of suppressing the same rule for an entire day.
- Index and theme transformation failures are isolated into unavailable Overview blocks.
- Followed themes are limited to 4 after preference filtering.
- Stock prediction filtering has a SQL-level regression test and returns an untruncated filtered total.
- Detail tabs lazy-load, store active state in the URL, and reload the active tab after changing stocks.
- Changed Today/Follow interactions have semantic links, clearer focus states, and larger card link targets.
- The rebuilt frontend is synchronized into the packaged Python static directory.

### Verification after remediation

- Ruff format: **320 files formatted**.
- Ruff lint: **passed**.
- Strict mypy: **175 source files passed**.
- Full offline Python suite with coverage: **1,750 passed, 13 deselected; 74.21% coverage**.
- Resource lifecycle gate: **14 passed**.
- Vue typecheck: **passed**.
- Vitest: **52 passed**.
- Production build: **passed**.
- Packaged frontend drift check: **passed**.
- Playwright: **10 passed, 1 opt-in screenshot test skipped**.

### Still open by product scope

These are not regressions from the remediation work and should remain visible in the execution plan:

- Unified built-in theme and custom-basket persistence model
- Basket weighting, fixed ordering, hiding, and reason metadata
- Theme performance, leader/laggard, anomaly, and freshness summaries on Today
- Server-owned preference schema that drives Today ordering, reminders, Agent emphasis, and backtest defaults
- Holding profit/loss context in stock detail
- Prediction freshness/evidence coverage and Agent prediction attachments
- Stock-level backtest entry and stable deep links
- Preference-aware Weixin selection, reminder windows, merged summaries, and channel-health UX
- Mobile/desktop screenshot acceptance for the final P1–P4 experience

The current working tree is suitable for a corrective commit, but the plan should continue to describe P1–P4 as incomplete until the product-scope items above are implemented and accepted.

## 12. Next-stage implementation review — unified baskets and Today summaries

The 2026-08-01 working tree completes the next bounded work package from the execution plan.

### Implemented

- Built-in themes use `theme:<id>` and existing watchlist groups use `group:<database-id>` under one basket contract; stock membership remains owned by the original theme definition or watchlist group.
- `basket_preferences` persists follow state, hiding, stable ordering, and a user reason. `basket_member_preferences` persists optional `Decimal` weights. Removing a custom group or member removes its orphaned preference state.
- `/api/baskets` exposes the ordered catalog, `/api/baskets/{id}` exposes members plus the decision summary, and explicit mutation endpoints update preferences and member weights.
- Partial weights never silently exclude unweighted members: weighted performance is used only when every available member has a weight and the total is positive; otherwise the summary is equal-weighted.
- Follow no longer treats browser localStorage as the source of truth. A one-time migration preserves the legacy theme selection and then removes the old key.
- Today renders at most four followed baskets with performance, leader, laggard, anomaly, reason, status, and timestamp. It uses snapshot/cache data only, so basket summaries cannot turn the first screen into a blocking market-data fan-out.
- Index retrieval was reduced from six sequential HTTP calls to one two-second batch request, bounding the offline first-screen delay.
- The unified detail page starts with “what happened,” then lists members and optional weights; theme and custom baskets use the same interaction path.

### Self-review result

- The server-owned preference model is the only authoritative state after migration.
- Generated SQL tables are additive and created through the existing `WatchlistBase.metadata.create_all()` path, so existing installations do not require a destructive migration.
- Decimal values remain Decimal from persistence through the API; the browser sends weight strings instead of converting them through floating point.
- Desktop and 390×844 visual review confirmed that the four decision summaries, watchlist status, portfolio status, and AI continuation remain visible in one screen.

### Verification

- Ruff format and lint: **passed (325 files)**.
- Strict mypy: **passed (177 source files)**.
- Full offline Python suite: **1,765 passed, 13 deselected; 74.69% coverage**.
- Vue typecheck: **passed**.
- Vitest: **55 passed**.
- Production build and packaged-static drift check: **passed**.
- Playwright: **11 passed, 1 opt-in screenshot test skipped**.
- Manual semantic snapshots and visual review: **Today desktop, Today 390×844, and Follow desktop passed**.

### Open after work package 3

This list records the boundary at the time of commit `66f467e`. The stock-context item was subsequently resolved by `30d9bc8` and is reviewed in section 13.

- The old `/themes` routes and detailed industry-chain page remain for compatibility; consolidation can happen after the unified basket page reaches feature parity for specialist metadata.
- Trading style is still browser-selected and only Agent-aware. A shared server preference schema must drive Today explanations, Agent emphasis, backtest defaults, and Weixin selection together.
- Stock holding profit/loss and automatic Agent page context: **resolved by `30d9bc8`; see section 13**.
- Prediction evidence/freshness, Agent attachments, and one-click stock backtest entry remain P2 work.

## 13. Work package 4 review — stock decision and Agent page context

Commit `30d9bc8` closes the stock-context portion of P2 after the unified-basket work in `66f467e`.

### Implemented

- `/api/stocks/{code}/decision-context` returns server-owned holding aggregation and unified basket membership without fetching market data.
- Multiple open lots of the same stock are combined into total shares, total cost, and weighted average cost; closed lots are excluded.
- Stock detail places shares, average cost, and live unrealized profit/loss directly below the quote, while the existing quote-age label remains visible.
- Basket member links preserve their canonical source ID. Stock detail shows the source basket and can navigate back to it.
- “Ask AI” now sends a structured `page_context` separately from the visible user message. The allow-list accepts only stock surface, six-digit code, known tabs, canonical basket IDs, and a timestamp; extra prompt-like fields are rejected.
- REST and WebSocket compose the same server-enriched page context after the existing trading-style addendum. Holdings and basket names are reread from server storage, and the addendum instructs the Agent to verify live price and P/L with tools.
- Chat displays the active stock/Tab context and provides a semantic, keyboard-focusable exit action. Context-rich follow-ups bypass generic natural-language workflow routing so the structured context reaches the Agent loop.

### Self-review

- No market request is added to the context endpoint; P/L is calculated in the stock page from the already displayed quote and server-owned cost basis.
- Browser-supplied basket IDs are used only when the stock is actually a member of that server-owned basket.
- The new API validates stock codes, and Agent page context rejects unknown fields rather than silently accepting instructions.
- Desktop and 390×844 review found the holding summary readable in one compact row. The mobile chat context bar remains one line and does not displace the composer.

### Verification

- Ruff format and lint over 329 files: passed.
- Full offline Python suite: 1,771 passed, 13 deselected; 74.82% coverage.
- Strict mypy over 179 source files: passed.
- Vue typecheck and 57 Vitest tests: passed.
- Production build and packaged-static drift check: passed.
- Playwright: 12 passed, 1 opt-in screenshot test skipped.
- Visual review: stock detail desktop, stock detail 390×844, and stock-aware chat 390×844 passed.

### Next action

Create a server-owned preference schema and migrate the current browser-only trading preset. The same preference service should drive Today explanations, Agent emphasis, default backtest parameters, and Weixin reminder selection before adding more preference fields to individual screens.
