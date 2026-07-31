# Product UX Implementation Review

> Reviewed commit: `a3f58ea7291428270bec94d4c6b1370d58481372`
> Review date: 2026-07-31
> Related plan: [`PRODUCT-UX-EXECUTION-PLAN.md`](PRODUCT-UX-EXECUTION-PLAN.md)
> Result: **Request changes** — useful P1–P4 prototype, but not ready to mark P1–P4 complete.

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
