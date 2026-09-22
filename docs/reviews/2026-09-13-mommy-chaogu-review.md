# Architecture & capability review — mommy-chaogu

2026-09-13 · scope: full-repo deep dive with emphasis on the DSH product graft (hot spot of the
last 10 commits) and the uncommitted working-tree fixes; informed by two prior sessions
(4-stage acceptance test that found A8/A10/A11, and the fix session that landed 4 mommy-side
repairs) · HEAD: `91d5d4b` on `feat/dsh-product-graft` **+ 494 lines of uncommitted fixes in 7
files + 5 untracked artifacts (reviewed as working tree)**

## TL;DR

The base is real and deep: one `ToolRegistry` (37 tools, DEFS/HANDLERS import-checked) serves
TUI/Web/CLI/MCP/DSH identically, the cache layer honors "keep old data on refresh failure", the
deterministic-compute discipline held up under live GUI testing, and quality gates (mypy strict
at zero exemptions, 2,301 offline tests) genuinely cover the hot areas. The root disease is that
**every shape that crosses a seam lives in hand-copied duplicates** — Python↔TypeScript,
TUI↔Web↔DSH, code↔docs — and the drift is no longer hypothetical: the TUI label table misses 5
of 37 tools while its comment claims full coverage, the web table misses 12, the approval gate
exists in five encodings whose drift direction is fail-open, and the code-regex canonical in
`codes.py` was migrated by only 2 of 23 call sites so `research_stock` accepts `BRK.B` while
`get_quote`'s schema rejects it. Layered on top, the "supported automated monitoring" product
promise is structurally capped: no scheduler exists, Server Chan push is wired only inside the
web process, and no polling loop has a trading-hours gate. First wave: fix the liars
(WAL×mtime invalidation, the dock "keep old data" lie, trading-hours gate, regex migration,
doctor baseline), all shallow edits; second wave: un-throttle by deriving the cross-language
tables instead of copying them; third wave: decide the ceilings.

## Capability inventory

| # | Capability | Health | Base modules | Holds it back |
|---|------------|--------|--------------|---------------|
| A | Market evidence & deterministic compute — 37 tools / 12 domains; quote+bars have cache fallback, keep-old-on-failure verified | green | `agent/tools/*`, `services/`, `cache/`, `market_data/` | ~9 tools (news/sector/fundamentals/longhuban/indexes) bypass the adapter Protocol: no cache, no fallback (F16) |
| B | DSH product graft — 13 toolview cards, 5 skills, node bridge + browser dock, four-mechanism patch verified on host 0.1.5-rc.2 | amber | `dsh/packages/dsh-bundle`, `cli_commands/dsh_product.py`, `agent/mcp_server.py` | Cross-language contracts are hand-copied and drifting (F1/F2/F5/F8/F11/F12); approval gate drifts fail-open |
| C | Continuous monitoring — 7 built-in rules + custom alerts + flows ratio + earnings compare | red | `monitor/`, `flows/`, `signals/`, `push/` | No scheduler anywhere; push wired only in web process; no trading-hours gate; Bark implemented but never called (F13/F6) |
| D | Strategy distillation loop — extract → save → prepare → activate, three independent confirmations intact | amber | `strategy/store.py`, `agent/tools/strategies.py` | Write-surface governance is three-track and unequal (workflow path has no gate; MCP relies on LLM self-reported `user_confirmed`) (F15); condition mapping silently narrows to manual |
| E | Five-entry consistent UX (CLI 17 subcommands + 10 workflows, TUI 16 slash, Web 13 pages, MCP 5 hosts, DSH) | amber | same ToolRegistry under all five | Tool surface mirrored in 4 places with measured drift; TUI rich cards cover only 4/37 tools; 8KB truncation kills every max-size result (F5/F14) |
| F | Install / upgrade / doctor (`mommy dsh install`, `mommy connect`, agent-managed hosts) | red | `cli_commands/dsh_product.py`, `coding_agents/` | Skill upgrade path self-locks (`previous=None`); doctor version baseline is a string-replace cosmetic (F11/F4) |
| G | Quality infrastructure — 2,301 offline tests / 161 files, mypy strict at zero exemptions, vitest 64 | green | `tests/`, `dsh/.../test/`, CI | dsh-bundle vitest not in any CI workflow; graft GUI layer has zero automation (manual TEST-PLAYBOOK only) |

Health: green (sound base) / amber (works, conditional or throttled) / red (lying under
specific conditions, or structurally capped). Numbers measured at HEAD (see Appendix).

## Prior-review scorecard (2026-08-15 → today)

| # | Candidate | Status | Evidence |
|---|-----------|--------|----------|
| 1 | HostInfo registry (host metadata single source) | **not done** | No `HostInfo` in src; host literals still in `connect.py:49-75`, `agent_managed.py:143`, `base.py:134-149`; the predicted cost already materialized — adding the 5th host (dsh, 9b1df27) required hand-editing every copy |
| 2 | Host adapter merge (JSON/CLI families) | partial | JSON-family adapters share `base.py:320-346` skeleton; still 4 classes + YAML-family `dsh.py` (284 lines), no descriptor table |
| 3 | TUI card builders as free functions | **done** (commit 18f17d9) | `tui/widgets/cards.py` ~20 builders; `chat.py` `_build_` count 0 |
| 4 | TurnController | not done | Turn state still split `tui/app.py:176-187` + `chat.py:183-207`; chat.py grew 946→993 lines |
| 5 | Timestamp normalization at 3 serialization boundaries | not done | No `TypeDecorator`; defensive branches remain `web/mappers.py:50,138,210-213`, `basket_service.py:222,239` |
| 6 | Web AppState de-self-mutation | not done | `app.py:122` still mutates module state via setter; 15 `lru_cache` singletons in `deps.py` |
| 7 | Services completion (MoneyFlow serialization + public cache interface) | not done | `quotes.py:107-152` + `flows.py:57` still duplicate MoneyFlow→dict; `cache/manager.py:38,75,80` still pokes `adapter._last_fetch_attempt` |
| 8 | Delete `frontend/` (Taro shell) | **done** (commit 32bdee3) | directory gone, TECH-DEBT.md:49 records it |

Net: 2.5/8 landed. Only #3 of the four Strong candidates landed; #1's pain was amplified by
the DSH 5th host.

## Findings

### F1 · WAL defeats the mtime-based SSE invalidation signal
- **Damage class**: silent failure (inference-grade evidence — marked for live verification)
- **Files**: `dsh/packages/dsh-bundle/src/events.ts:27,39` (2s poll of `portfolio.db` main-file
  mtime; header asserts "any write changes the file time"), `src/mommy_chaogu/db.py:41`
  (`PRAGMA journal_mode = WAL`), `agent/mcp_server.py:320-324` (long-lived connection,
  `runtime_ctx` built once per process)
- **Problem**: the invalidation `seam` couples to SQLite checkpoint behavior it does not
  control. CLI/TUI writes become visible only because process exit checkpoints the WAL; an
  MCP-server write (e.g. host agent adds a watchlist stock) can stay in `-wal` without moving
  the main-file mtime, so the DSH dock never receives the change signal.
- **Capability today**: the TEST-PLAYBOOK once verified "Allow once → persisted → dock SSE
  updates", but that path cannot distinguish checkpoint timing.
- **Unlocked**: after stat'ing `-wal`/`-shm` together (or a trigger+revision table), AI-driven
  watchlist edits in DSH become *reliably* reflected, not incidentally.
- **Strength**: Strong (fix is shallow; failure mode is silent staleness)

### F2 · The "keep old data on refresh failure" chain lies three times in a row
- **Damage class**: silent failure
- **Files**: `cli_commands/quote.py:36-39` (refresh failure → exit 0 + `{"source":"","quotes":[],"error":…}`),
  `dsh/.../src/bridge.ts:110-124` (forwards as 200), `dsh/.../src/client/api.ts:33-41`
  (`fetchQuotes` drops the `error` field entirely), `dsh/.../src/client/dock.tsx:137-151`
  (comment says "拉新失败保留旧数据语义" but `quotes` is a fresh empty Map and state is replaced
  wholesale — old quotes are wiped, not kept)
- **Problem**: the CLI-as-contract discipline covers only happy-path shapes; error semantics
  forked into an exit-0-with-error-payload that every consumer must remember to check, and the
  one consumer that documented the right behavior implements the opposite.
- **Capability today**: on upstream jitter the DSH watchlist dock shows an *empty* watchlist
  with no error, and hammers the upstream on every refresh (no cache, see F16-adjacent path:
  `quote.py:33` uses `create_adapter_chain()` directly, bypassing the cache layer).
- **Unlocked**: stale prices + source label + explicit degradation notice instead of silent
  emptiness; the documented semantic becomes true.
- **Strength**: Strong

### F3 · Code-regex canonical exists but 15 of ~23 call sites still hand-copy the old pattern
- **Damage class**: silent failure
- **Files**: `codes.py:33-36` (canonical accepts `BRK.B`/`BF-B`), `agent/tools/quote.py:19`
  (DEFS pattern `^(\^[A-Z]{1,6}|[A-Z]{1,6}|\d{6})$` — rejects them); 15 inline old-style
  patterns across `agent/tools/*.py` (flows.py:21,26, bars.py:20, holdings.py:65, intel.py:52,
  memory.py:52, backtest.py:38, …); only `strategies.py:11` + `research_tools.py` migrated
  (30f79bf)
- **Problem**: one MCP server exposes two tool faces that disagree on the same input —
  `research_stock` accepts `BRK.B`, `get_quote`'s schema rejects it. A single source of truth
  that is only partially adopted is *worse* than none: it manufactures false confidence.
- **Unlocked**: suffixed US tickers behave identically across all 37 tools; the canonical
  becomes load-bearing instead of decorative.
- **Strength**: Strong (mechanical migration, DEFS patterns generated from `codes.py`)

### F4 · Doctor version baseline is a string-replace cosmetic
- **Damage class**: silent failure
- **Files**: `cli_commands/dsh_product.py:53` (`PRODUCT_TESTED_DSH_VERSION = "0.1.5-rc.2"`),
  `:384-387` (`check["message"].replace("0.1.1-rc.2", PRODUCT_TESTED_DSH_VERSION)`), comparison
  semantics still hardcoded in `coding_agents/dsh.py:41,59-103`
- **Problem**: munging a message on a `seam` instead of parameterizing the check. A host
  running 0.1.5-rc.2 (the product's own verified baseline) gets `warning: newer than verified
  baseline 0.1.5-rc.2` — self-contradictory. Any wording change in `dsh_version_check`
  silently breaks the replace.
- **Unlocked**: doctor — the only drift-detection surface — reports a true baseline;
  parameterize as `dsh_version_check(version, tested=...)`.
- **Strength**: Strong (mechanical)

### F5 · The tool surface is mirrored in 4 places; two mirrors have measured drift
- **Damage class**: rate-limited (with a lying comment)
- **Files**: truth `agent/tools/*` DEFS; mirrors `tui/widgets/tool_indicator.py:31` (32/37,
  comment claims "覆盖 agent/tools/ 的全部工具"; missing `check_kline_signal`, `run_backtest`,
  `screen_inflow_stocks`, `check_earnings_catalyst`, `get_memory_health`), `web/src/lib/toolNames.ts`
  (32/37, missing those 5 + all 7 strategy tools), `dsh/.../cards.tsx` + `client/index.ts:5`
  (comment "×7" but 13 cards registered), plus stale prose in `cordis.patch.yml:23-25`
  ("7 write tools" vs 5 actually gated)
- **Problem**: adding one tool is an N-file coordinated edit with no drift alarm. The comment
  on the TUI table already lies.
- **Unlocked**: label tables generated from DEFS (codegen or a build-time completeness assert):
  a new tool is readable in every entry the day it lands.
- **Strength**: Strong

### F6 · No trading-hours gate on any polling loop
- **Damage class**: silent failure (false signals)
- **Files**: `monitor/poller.py` (no session check), `web/background.py:33-58` (5s loop),
  `flows/monitor.py:96-148` (post-close empty ticks can trip the >50%-failure alarm)
- **Capability today**: overnight monitoring evaluates yesterday's close snapshot against
  PriceChange rules and can push false WeChat alerts at 3am.
- **Unlocked**: monitoring semantics re-align with "real-time"; no midnight bombardment.
- **Strength**: Strong

### F7 · Documentation counts lie in three places
- **Damage class**: silent failure (capability under-reported)
- **Files**: `AGENTS.md:93` "13 透传子命令" vs 17 actual (`cli.py:209-227`); `AGENTS.md:82,118`
  "9 workflows" vs 10 (`definitions.py:220-531`, `us_market_brief` uncounted); `AGENTS.md:191`
  "9 pages" vs 13 (`web/src/router/index.ts:10-37`); `docs/BACKEND-CAPABILITIES.md:308,345`
  "25 tools" vs 37; `DESIGN.md` (2026-08-11) still narrates a two-source world without
  massive/yahoo/fundamentals/news/sector modules
- **Unlocked**: host agents integrating by documentation stop underestimating the surface;
  predictions/baskets pages become discoverable.
- **Strength**: Strong (doc edits; consider generating counts)

### F8 · Approval semantics exist in five encodings; drift direction is fail-open
- **Damage class**: rate-limited (safety-critical)
- **Files**: `agent/service.py:44-69` (`CONFIRM_ALWAYS` 3 + `CONFIRM_BY_ACTION` 2 — the TUI
  table), `dsh/.../src/gate.ts:31-51` (hand-copied TS table), `agent/research_tools.py:59-67`
  (`WRITE_TOOL_NAMES`, 7 members incl. `backfill_history`, `record_research_conclusion`),
  `mcp_server.py:280` (readOnlyHint annotations derived from WRITE_TOOL_NAMES — the
  cross-language source of truth MCP designed for exactly this, unused by the TS gate),
  `research_tools.py:675` (`user_confirmed` self-reported boolean). Prefix
  `mcp__mommy-chaogu__` written twice in TS (`gate.ts:28`, `client/index.ts:58`);
  `serverName` literal in 5 places across languages. `gate.test.ts:21-22` asserts
  `backfill_history` is *not* confirmed while the MCP annotations mark it a write.
- **Problem**: "what is a write" has five answers that evolve independently. The failure mode
  of any prefix/serverName rename is `startsWith` miss → `undefined` → `next()` — the gate
  silently opens. No startup cross-assertion ties the patch-row serverName to the gate prefix.
- **Unlocked**: gate derives from MCP annotations (or a generated table + cross-assert test):
  adding a write tool touches one place; approval stays consistent across TUI/DSH/hosts.
- **Strength**: Strong

### F9 · The positions×quotes join is implemented 4(+1) times; two of them loop per-code
- **Damage class**: rate-limited
- **Files**: `agent/tools/holdings.py:96-149` (batched), `tui/services/bootstrap.py:55-75`
  (batched), `web/routes/portfolio.py:52-57` (**per-code `adapter.get_quote` loop**),
  `web/routes/overview.py:160-185` (per-code loop), `services/stock_context_service.py:40-46`
  (no-price variant)
- **Problem**: ae670fc centralized the watchlist join into `WatchlistQuoteService` but missed
  the isomorphic positions join. Web pays N upstream round-trips where tools/TUI pay 1.
- **Unlocked**: `PortfolioQuoteService.fetch_positions_snapshot()` — the portfolio page drops
  from N to 1 upstream requests; one place to fix join bugs.
- **Strength**: Strong

### F10 · Default ToolContext assembly is copy-pasted 6 times; the factory's default path is dead
- **Damage class**: rate-limited
- **Files**: `workflow/assembly.py:190-206` (`_default_context` — no caller reaches it),
  `cli.py:285-293`, `agent/mcp_server.py:178-198`, `web/routes/agent.py:99-108`,
  `cli_commands/agent.py:53-70`, `tui/services/bootstrap.py:219-245`
- **Problem**: changing the default adapter chain (e.g. fallback order) means editing 6 files.
  MCP doesn't go through the factory at all — a 4th assembly lineage.
- **Unlocked**: one `default_tool_context(...)` consumed by all entries incl. MCP.
- **Strength**: Worth exploring

### F11 · Product-mode skill upgrades self-lock: `previous=None` makes every content upgrade look like user modification
- **Damage class**: rate-limited (installer-grade availability bug)
- **Files**: `dsh_product.py:319` (`install_skill(..., None, ...)`), `coding_agents/base.py:245-247`
  (`current_hash not in {bundled_hash, previous_hash}` → RuntimeError), hash state persisted
  only by enhanced mode (`cli_commands/agent_managed.py:105-109`); install is non-transactional
  (manifest/patch rows land before the skill loop, `dsh_product.py:301-315`)
- **Problem**: the moment a bundled skill's content changes, an untouched on-disk copy matches
  neither hash → forced `--force`, which would also overwrite *genuinely* user-modified skills.
  The correct pattern already exists in-repo: TS `presets.ts:84-97` per-file stamp (upgrade
  untouched files, skip modified ones). No test covers "bundled content changed, reinstall".
- **Unlocked**: skill iteration upgrades cleanly; real user edits are skipped per-file instead
  of being clobbered by a blunt `--force`.
- **Strength**: Strong

### F12 · Default-data-dir resolution exists 3 times with forked semantics, frozen at import time
- **Damage class**: rate-limited
- **Files**: `db_paths.py:48-57` (`DEFAULT_DATA_DIR` evaluated at import via cwd probe — no
  XDG branch), `dsh/.../src/presets.ts:28-32` + `src/bridge.ts:138-142` (two verbatim TS
  copies: `MOMMY_DATA_DIR || ~/.local/share/mommy-chaogu`), stragglers `web/deps.py:139`
  (`Path("data/signals.log")`), `services/theme_service.py:43-49`, `cli_commands/flows.py:324`;
  the bridge pins `MOMMY_DATA_DIR` explicitly as a downstream patch for the cwd probe
  (`bridge.ts:139-159`)
- **Unlocked**: path resolution becomes a function (per-call), TS converges on one
  `resolveMommyDataDir()`; the bridge stops needing its defensive pinning.
- **Strength**: Worth exploring

### F13 · "Supported automated monitoring" is structurally "supported manual monitoring"
- **Damage class**: capped
- **Files**: no scheduler module exists in `src/` (grep: only a static JS bundle and a SKILL.md
  mention); Server Chan notifier wired only in `web/app.py:136-168`; `monitor/poller.py` and
  `flows/monitor.py` have zero notifier wiring (grep verified); `push/bark.py:43-113` fully
  implemented with **zero callers**; close report / earnings compare are manual commands; the
  only automation is external crontab (`scripts/cron_verify.py:15-17`)
- **Capability today**: "push me the daily brief at 9am" has no ready path — the user must
  keep the web process alive (the only pusher), configure keys, and hand-assemble crontab;
  the daily report itself has no push channel at all (Server Chan only pushes live Signals
  from the web BackgroundService).
- **Unlocked**: a `mommy scheduler` (or daemon) + report-push channel + notifier wiring in the
  monitor loops turns the monitoring promise into one command; Bark gives iOS users a second
  channel for free.
- **Strength**: strategic (product-shape decision, not a patch)

### F14 · The 8KB result truncation and per-tool limits don't know about each other
- **Damage class**: capped
- **Files**: `agent/tools/bars.py:76-78` (`MAX_BARS_LIMIT = 120`, schema-advertised),
  `agent/tools/registry.py:70-87` (`MAX_RESULT_BYTES = 8192`, truncates to *illegal* JSON by
  design); measured: 120 daily bars serialize to 22,404 B with MA / 18,444 B without — a
  max-size `get_bars` is truncated 100% of the time; downstream `workflow/engine.py:305-312`
  degrades illegal JSON to raw string and still records success; `strategies.py:249-260`
  hand-rolls its own pre-shrink to survive; TUI drops the card entirely for >8KB results
  (`tui/services/renderers.py:25,59`) and its rich cards cover only 4/37 tools
- **Unlocked**: limits coupled (row-count derived from byte budget, or truncation that yields
  valid JSON): max-size bars/backtest/screen results stay renderable; TUI card coverage can
  grow past 4/37 without each tool hand-rolling shrink logic.
- **Strength**: Worth exploring

### F15 · Write-surface governance is three-track and the weakest track is the deterministic one
- **Damage class**: capped (safety semantics)
- **Files**: LLM path gated (`agent/service.py:64-71` via `on_confirm`); workflow path ungated
  — compiler feeds all 37 tools incl. writes to the compiling LLM (`workflow/compiler.py:62-73`),
  validator checks existence only (`validator.py:72-79`), executor calls directly
  (`engine.py:232`), and a `trigger_patterns` hit auto-executes a spec that may carry
  `manage_watchlist add`; MCP personal profile relies on the host's honor + LLM-self-reported
  `user_confirmed` (no server-side enforcement; prompt-only declaration `mcp_server.py:133`)
- **Unlocked**: one validator blocking rule ("write tools require a confirmation step") closes
  the workflow track for one line of code; server-side pending-confirmation would make the
  three-authorization product semantics a hard gate instead of a gentleman's agreement.
- **Strength**: Strong (the validator rule); strategic (server-side enforcement)

### F16 · The MarketDataAdapter Protocol covers half the data sources; ~9 tools run on the ungated half
- **Damage class**: capped
- **Files**: `market_data/adapter.py:33-107` (Protocol: quote/quotes/bars/flows/snapshot…);
  direct module calls bypassing it: `agent/tools/quote.py:63-64` (indexes via `rankings`),
  `sector.py:79-105`, `intel.py:104-128` (news/announcements/longhuban/fundamentals),
  `analysis.py:183-205`, `web/routes/market.py:113-149`
- **Problem**: these tools have internal error handling but no cache and no source fallback —
  when the Eastmoney public endpoints rate-limit, they fail bare while quote/bars degrade
  gracefully from `market.db`. The seam is unnamed and unowned (services also call this way —
  this is a data-source seam gap, not a tools-bypassing-services gap).
- **Unlocked**: either extend the Protocol (with cache semantics) or name the second seam
  (XxxDataSource protocol); rate-limit storms stop producing asymmetric failures across the
  tool surface.
- **Strength**: Worth exploring

### F17 · agent.db is a junk drawer for 7 subsystems; "reset memory" and "keep strategy cards" are mutually exclusive
- **Damage class**: capped
- **Files**: `db_paths.py:72-73` (defined as "memory system"), actual tenants:
  `agent/memory.py:22`, `episodic_memory.py:25`, `semantic_memory.py:36`, `prediction_tracker.py:29`,
  `token_tracker.py:35`, `workflow/store.py:31` (custom_workflows),
  `strategy/store.py:65-127` (strategy_cards + revisions + monitor_links via
  `agent/tools/strategies.py:208-230`)
- **Problem**: strategy cards are user-confirmed documents and custom workflows are user
  orchestration — conceptually portfolio.db-grade user data, not agent memory. Storage boundary
  drifted from concept boundary; deletion test is clean (zero cross-schema coupling — pure
  cohabitation), so this is a placement fix, and it gets more expensive as data grows.
- **Unlocked**: memory reset without losing strategy cards/workflows; smaller write-contention
  surface across the 3 processes that open agent.db.
- **Strength**: strategic (timing decision)

## Mapping matrix

| Fix (finding) | Damage removed | Capability unlocked | Chain |
|---------------|----------------|---------------------|-------|
| F1 stat -wal/-shm (or revision table) | silent staleness | DSH dock reliably reflects AI writes | 1 |
| F2 error-path honesty (exit code / error field / prev-state) | silent emptiness | dock degrades visibly, keeps stale prices | 1 |
| F3 DEFS patterns generated from `codes.py` | contradictory schemas | suffixed tickers work everywhere | 3 |
| F4 parameterized version check | self-contradictory doctor | true baseline reporting | 4 |
| F5 label tables generated from DEFS | 4-mirror drift | new tool readable in all entries day one | 3 |
| F6 trading-hours gate | 3am false alerts | monitoring semantics honest | 2 |
| F7 doc counts corrected | under-reported surface | host agents integrate the real surface | 3 |
| F8 gate derives from MCP annotations + cross-assert | fail-open drift | one-place write-tool addition | 1 |
| F9 PortfolioQuoteService | N-request loop | portfolio page N→1 upstream calls | 5 |
| F10 single assembly fn | 6-file edit per change | adapter-chain change in one place | 5 |
| F11 skill previous-hash/stamp | upgrade self-lock | clean skill iteration | 4 |
| F12 data-dir as function | 3 forked resolutions | bridge drops defensive pinning | 1 |
| F13 scheduler + push wiring | manual-only monitoring | "9am daily push" in one command | 2 |
| F14 coupled limits | guaranteed truncation | max-size results renderable | 3 |
| F15 validator write rule (+ server-side confirm) | ungated deterministic path | three-authorization semantics enforced | 2 |
| F16 Protocol completion / named second seam | asymmetric failures | rate-limit storms degrade uniformly | 5 |
| F17 agent.db split | concept/storage drift | memory reset preserves user artifacts | 5 |

## Recommended waves

0. **Commit the working tree first** — the 494 uncommitted lines are four product-grade
   repairs (SSE reconnect+revision reset, MCP idle watchdog, arg passthrough, draggable dock)
   with their tests already written but untracked. Everything below assumes they land.
1. **Stop the lying** — F2, F6, F3, F4, F5, F7 (plus F1, shallow stat fix, marked for one live
   verification on the DSH host). All are small, surgical, and each currently corrupts a
   conclusion a user or host agent could draw.
2. **Un-throttle** — F8 (annotations-derived gate + prefix cross-assert), F9, F11, then F10,
   F12. These tax every future change today.
3. **Decide the ceilings** — F13 (product-shape: scheduler/push), F15 (server-side
   confirmation), F14, F16, F17. Strategic calls, not patches; schedule explicitly.

## Appendix — measured at HEAD (91d5d4b + working tree)

| Metric | Value | How measured |
|--------|-------|---------------|
| registry tools | 37 (DEFS = HANDLERS = 37, unique 37) | `ToolRegistry(ToolContext(adapter=MassiveAdapter())).definitions()` |
| domain modules | 12 (alerts 1 / analysis 3 / backtest 1 / bars 2 / flows 2 / holdings 4 / intel 4 / memory 5 / quote 3 / sector 3 / strategies 7 / themes 2) | same run, per-module `DEFS` count |
| market-only profile | 19 base + 5 research (personal: 37 + 7) | `len(MARKET_ONLY_BASE_TOOLS)`; `_MARKET_RESEARCH_NAMES` |
| toolview cards | 13 | `grep '^export function' dsh/.../cards.tsx` |
| bundled skills | 6 on disk; 5 installed by product mode (`food-security-analysis` goes via plugins.py route) | `find . -name SKILL.md`; `PRODUCT_SKILL_NAMES` dsh_product.py:56-62 |
| offline tests | 2,301 collected / 161 files (grep `def test_` = 2,238) | `uv run pytest -m "not network" --collect-only -q` |
| bundle vitest | 64 cases (parse 33 / gate 10 / bridge 9 / api 6 / presets 6) | `grep -rn "it(\|test(" dsh/.../test/` |
| LOC | Python 54,807; TS/TSX 3,463 | `find … -exec cat {} + \| wc -l` |
| 120-bar payload | 22,404 B with MA / 18,444 B without vs 8,192 B limit | synthetic `_bar_to_dict`-shaped payload ×120, `len(json.dumps().encode())` |
| TUI label coverage | 32/37 (missing 5) | set-diff TOOL_DISPLAY_NAMES vs registry names |
| web label coverage | 32/37 (missing 12 incl. all strategy tools) | set-diff `web/src/lib/toolNames.ts` vs registry names |
| CLI subcommands / workflows / web pages | 17 / 10 / 13 (AGENTS.md says 13 / 9 / 9) | `cli.py:209-227`; `definitions.py:220-531`; `web/src/router/index.ts:10-37` |
| prior review landed | 2.5/8 candidates | git log + grep per candidate (scorecard above) |
| uncommitted work | 7 modified files (+494/−45), 5 untracked paths | `git diff --stat`; `git status --porcelain` |

Evidence-grade note: F1's WAL×mtime mechanism is reasoned from `db.py:41` + SQLite WAL
checkpoint semantics + the long-lived MCP connection, not yet reproduced live; verify once on
the DSH host (add a watchlist stock via MCP, watch for the SSE signal) before scheduling the
fix. All other findings were verified directly at file:line or by execution.

**Open question for the user**: which finding to explore first — the recommendation is Wave 1
(F2+F6 as the pair with the highest lie-per-line ratio, or F8 as the safety-critical
un-throttle).

## Errata — 2026-09-14

Cross-checked against a second review of this review; corrections to the record above:

- **F12**: "no XDG branch" is wrong — `db_paths.py:52` *does* have an `XDG_DATA_HOME`
  branch. The defect is solely the import-time freeze (`DEFAULT_DATA_DIR = default_data_dir()`
  at `:58`), not a missing branch. Fix approach unchanged.
- **F10**: the assembly copy-count is ~8 sites, not 6 — `web/deps.py:257` and the second
  `bootstrap.py` spot were missed. Also `_default_context` is not dead code: production
  entries all inject their own context; only tests reach the factory default. Fix unchanged,
  scope widened.
- **F3**: the meta-test as originally specified ("assert pattern == canonical") is wrong
  one-size-fits-all: `codes.py:41` deliberately defines `A_SHARE_CODE_PATTERN` for A-share-only
  domains (analysis ×3, run_backtest legitimately narrow), while flows/memory/holdings drift
  the *other* way (A-share semantics but US letters allowed). The shipped meta-test asserts
  "pattern must be generated from a codes.py constant (canonical or A-share variant)" with
  per-tool wide/narrow adjudication.

Execution state as of 2026-09-14: wave 0, F1, F4, F2① committed in the first fix batch;
F2②③, F8① (via a 44-name `MOMMY_TOOL_SURFACE` snapshot — plain unknown→ask would have
gated all 33 read tools), F3, F5, F7, F15 committed in the second. Open: F6, F8② (manifest
should supersede the hand snapshot), F11, F9, F10+F12, wave 3.
