# Executable Enhancement Plan — 2026-07-14

> Implementation plan derived from [Project Evaluation — 2026-07-14](EVALUATION-2026-07-14.md).
> Target: a secure and reliable **single-user production release**.

## Plan contract

This plan is intentionally split into independently reviewable pull requests. Each work package
must leave the repository runnable, include regression tests, and pass its own definition of done.

### Global definition of done

Every implementation PR must pass:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -m "not network"
cd web && npm run typecheck && npm run build
```

After the Docker work package lands, also require:

```bash
docker compose build --no-cache mommy-web
docker compose up -d
curl --fail http://127.0.0.1:8000/api/health
docker compose down
```

### Scope decisions

- Optimize for one trusted owner using multiple devices.
- Do not introduce user registration, roles, billing, or multi-tenant data models.
- Preserve CLI and TUI behavior when Web authentication is added.
- Continue using SQLite; improve lifecycle and concurrency discipline before considering another
  database.
- Keep network-dependent market-data tests separate from the deterministic PR gate.

## Delivery map

| Order | Work package | Priority | Effort | Depends on | Primary outcome |
|---:|---|---|---|---|---|
| 0 | WP-0 Baseline repair | P0 | S | — | CI can become green and trustworthy |
| 1 | WP-1 WebSocket correctness | P0 | S | WP-0 | Real-time quote/signal delivery works |
| 2 | WP-2 Reproducible Docker build | P0 | M | WP-0 | Clean clone starts successfully |
| 3 | WP-3 Single-user security | P0 | L | WP-2 | Safe LAN/hosted deployment |
| 4 | WP-4 Session isolation | P1 | M | WP-3 | Devices do not mix conversations |
| 5 | WP-5 Database lifecycle | P1 | M | WP-0 | Clean shutdown and no connection leaks |
| 6 | WP-6 Complete CI surface | P1 | M | WP-1, WP-2 | Runtime boundaries are continuously tested |
| 7 | WP-7 Quality and coverage | P2 | L | WP-6 | Fewer blind spots and honest quality claims |
| 8 | WP-8 Maintainability and docs | P2 | L | WP-3–7 | Easier releases and lower change risk |

`S` is roughly one focused change, `M` is several related modules, and `L` should be split into
multiple commits even when delivered in one PR.

## WP-0 — Baseline repair

**Goal:** make the existing quality contract pass before feature work starts.

### Tasks

- **H-001:** Format the ten files currently rejected by `ruff format --check .`.
- **H-002:** Confirm formatting produces no behavioral changes.
- **H-003:** Update CI branch filters so active `feat/**`, `fix/**`, and `codex/**` branches receive
  push feedback, or deliberately document PR-only enforcement.
- **H-004:** Add a concise local `quality` command or script that mirrors CI exactly.

### Likely files

- Existing Python files reported by Ruff
- `.github/workflows/ci.yml`
- `pyproject.toml` or `scripts/quality.sh`
- `CONTRIBUTING.md`

### Acceptance criteria

- Repository-wide Ruff format and lint checks pass.
- No functional test changes are required solely because of formatting.
- A developer can run one documented command to reproduce CI locally.

### Recommended commit

`chore: restore repository quality baseline`

## WP-1 — WebSocket correctness

**Goal:** prove that connected clients are registered, receive data, and are removed on disconnect.

### Tasks

- **H-101:** Add `await` to quote and signal subscriber registration.
- **H-102:** Add WebSocket integration tests using `TestClient.websocket_connect` for:
  - immediate quote snapshot;
  - later quote broadcast;
  - signal broadcast;
  - ping/pong;
  - removal after disconnect;
  - dead-client cleanup.
- **H-103:** Add an agent WebSocket test for invalid JSON, missing agent configuration, chunking,
  completion, and disconnect.
- **H-104:** Ensure background-service tests explicitly start and stop the service.

### Primary files

- `src/mommy_chaogu/web/routes/ws.py`
- `src/mommy_chaogu/web/background.py`
- `tests/test_web/test_ws.py` (new)
- `tests/test_web/test_background.py` (new or expanded)

### Acceptance criteria

- Subscriber counts change from 0 → 1 → 0 during a socket lifecycle.
- Quote and signal payload schemas are asserted, not merely connection success.
- No `coroutine was never awaited` warning appears.
- WebSocket route and background-service coverage materially increases.

### Recommended commit

`fix(web): repair and test websocket subscriptions`

## WP-2 — Reproducible Docker build

**Goal:** make the documented clean-clone Docker path real.

### Tasks

- **H-201:** Add a Node builder stage that runs `npm ci`, `npm run typecheck`, and `npm run build`.
- **H-202:** Copy the generated frontend from the Node stage into the Python runtime image.
- **H-203:** Stop copying tests and unnecessary development documentation into the runtime image.
- **H-204:** Pin the `uv` container image to a version or digest rather than `latest`.
- **H-205:** Run the final image as a non-root user with a writable `/app/data` volume.
- **H-206:** Add a container smoke script that waits for health and checks the root page.
- **H-207:** Validate both missing `.env` and configured-provider startup paths.

### Primary files

- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- `scripts/smoke_docker.sh` (new)
- `README.md`

### Acceptance criteria

- `git archive HEAD` contains everything required for a successful image build.
- No locally generated `web/dist` is required.
- `/api/health` and `/` return success from the running container.
- Container process is non-root and the data volume remains writable.
- Image contains neither tests nor local secrets.

### Recommended commits

1. `build: compile web assets in docker image`
2. `test: add clean-container smoke check`

## WP-3 — Single-user security boundary

**Goal:** make LAN and public single-owner deployments safe by default.

### Design

Use one owner-managed bearer token:

- Environment variable: `MOMMY_API_TOKEN`.
- REST: `Authorization: Bearer <token>`.
- WebSocket: short-lived signed ticket obtained from an authenticated REST endpoint, avoiding a
  long-lived token in WebSocket URLs and logs.
- Health endpoint may remain unauthenticated but must expose no filesystem paths or secrets.
- Default CLI host becomes `127.0.0.1`; explicit `--host 0.0.0.0` enables remote access.

### Tasks

- **H-301:** Add security configuration with validation and secure token comparison.
- **H-302:** Add a reusable FastAPI dependency for REST authentication.
- **H-303:** Protect portfolio, watchlist, agent, signal history, cache statistics, and other
  owner-data routes.
- **H-304:** Implement short-lived WebSocket tickets and validate them before `accept()`.
- **H-305:** Make allowed CORS origins configurable; remove wildcard defaults for remote mode.
- **H-306:** Remove `db_path` from unauthenticated health output.
- **H-307:** Add rate/concurrency limits around agent requests to control accidental API spend.
- **H-308:** Update the frontend API and WebSocket clients to authenticate.
- **H-309:** Update setup, `.env.example`, Docker, and deployment documentation.

### Primary files

- `src/mommy_chaogu/config.py`
- `src/mommy_chaogu/web/security.py` (new)
- `src/mommy_chaogu/web/app.py`
- `src/mommy_chaogu/web/routes/*.py`
- `src/mommy_chaogu/cli.py`
- `web/src/api/client.ts`
- `web/src/api/ws.ts`
- `web/src/api/agent.ts`
- `.env.example`
- `docker-compose.yml`

### Acceptance criteria

- Protected REST calls return 401 without a token and succeed with the configured token.
- WebSockets reject missing, invalid, and expired tickets before accepting.
- Default local startup remains frictionless and documented.
- Remote binding without a token fails fast with an actionable error.
- Agent concurrency is bounded and returns 429 when saturated.
- Secrets do not appear in URLs, access logs, error bodies, or frontend storage beyond the chosen
  session mechanism.

### Recommended commits

1. `feat(web): add single-user API authentication`
2. `feat(web): secure websocket connections`
3. `feat(web): authenticate frontend clients`

## WP-4 — Conversation session isolation

**Goal:** prevent different devices or browser sessions from sharing conversational context.

### Tasks

- **H-401:** Add a `session_id` column and index to `agent_memory` through an idempotent migration.
- **H-402:** Require or generate a session ID in Web chat clients.
- **H-403:** Scope `add`, `recent`, `clear`, and history APIs by session.
- **H-404:** Decide whether CLI/TUI use stable named sessions or a default local session.
- **H-405:** Either honor REST `ChatRequest.history` or remove it from the public schema.
- **H-406:** Add retention controls for inactive sessions.

### Primary files

- `src/mommy_chaogu/agent/memory.py`
- `src/mommy_chaogu/web/deps.py`
- `src/mommy_chaogu/web/routes/agent.py`
- `src/mommy_chaogu/web/routes/ws.py`
- `web/src/api/agent.ts`
- `web/src/pages/agent/index.vue`
- `scripts/migrate_db_layout.py` or a focused migration script

### Acceptance criteria

- Messages from session A never appear in session B.
- Existing unscoped memory is migrated into a documented default session.
- Concurrent-session tests cover REST and WebSocket chat.
- History limits are validated and capped.

### Recommended commit

`feat(agent): isolate conversation memory by session`

## WP-5 — Database and resource lifecycle

**Goal:** eliminate unclosed-engine warnings and make shutdown deterministic.

### Tasks

- **H-501:** Inventory every class that owns a SQLAlchemy engine or raw SQLite connection.
- **H-502:** Add idempotent `close()` methods and context-manager support where appropriate.
- **H-503:** Dispose cached Web dependencies during FastAPI lifespan shutdown.
- **H-504:** Close stores in CLI commands, scripts, and test fixtures.
- **H-505:** Configure SQLite consistently for busy timeout, WAL where safe, and foreign keys.
- **H-506:** Add a focused test run that treats `ResourceWarning` as an error.
- **H-507:** Document ownership: the object that constructs a store is responsible for closing it.

### Primary files

- `src/mommy_chaogu/cache/store.py`
- `src/mommy_chaogu/watchlist/store.py`
- `src/mommy_chaogu/portfolio/store.py`
- `src/mommy_chaogu/agent/*memory*.py`
- `src/mommy_chaogu/web/deps.py`
- `src/mommy_chaogu/web/app.py`
- shared test fixtures

### Acceptance criteria

- The non-network suite produces no project-owned unclosed-database warnings.
- Repeated app startup/shutdown does not increase open database descriptors.
- `close()` can be called more than once safely.
- Concurrent read/write smoke tests do not fail with immediate `database is locked` errors.

### Recommended commits

1. `refactor(db): standardize store lifecycle`
2. `fix(web): dispose cached resources on shutdown`

## WP-6 — Complete CI surface

**Goal:** continuously verify every artifact users are told to run.

### Tasks

- **H-601:** Add frontend `npm ci`, typecheck, and production build job.
- **H-602:** Add WebSocket/background integration tests to the Python job.
- **H-603:** Add Docker build and container health smoke job.
- **H-604:** Cache npm and Docker layers without weakening reproducibility.
- **H-605:** Add dependency update automation and a scheduled network-adapter probe.
- **H-606:** Upload test/coverage summaries as artifacts.
- **H-607:** Keep network failures informational until provider reliability and rate limits are
  understood; alert on repeated scheduled failures.

### Primary files

- `.github/workflows/ci.yml`
- `.github/workflows/network-smoke.yml` (new)
- Dependabot/Renovate configuration
- test and smoke scripts from prior packages

### Acceptance criteria

- A PR cannot merge when Python, frontend, or Docker build validation fails.
- Scheduled probes identify upstream data-source failures separately from code regressions.
- CI commands match the documented local commands.
- The full deterministic pipeline remains reasonably fast.

### Recommended commit

`ci: validate frontend docker and runtime boundaries`

## WP-7 — Quality and coverage

**Goal:** focus coverage on costly failures rather than maximizing a vanity percentage.

### Tasks

- **H-701:** Establish a 65% initial coverage floor without excluding weak production modules.
- **H-702:** Raise boundary coverage first: Web routes, background service, report rendering,
  portfolio store/analysis, and agent tool handlers.
- **H-703:** Add Vitest component/unit tests for API state, formatting, and chat controls.
- **H-704:** Add one Playwright happy-path smoke flow against the built application.
- **H-705:** Begin removing `mypy ignore_errors` overrides one package at a time.
- **H-706:** Validate provider names rather than silently falling back to DeepSeek.
- **H-707:** Make generation parameters provider-aware instead of globally applying one
  temperature policy.

### Acceptance criteria

- Coverage cannot regress below the agreed floor.
- At least one test would fail for each critical finding E-001 through E-006.
- Frontend API failure and reconnect behavior is deterministic under tests.
- Mypy exclusions are narrower than at plan start and documented with owners/reasons.
- Invalid provider configuration fails with a useful message.

### Recommended commits

1. `test: cover production runtime boundaries`
2. `test(web): add frontend behavior suite`
3. `refactor(types): narrow strict-mode exclusions`

## WP-8 — Maintainability, metadata, and documentation

**Goal:** reduce change risk and make published claims match reality.

### Tasks

- **H-801:** Split `cli.py` into command-family modules while preserving entry points.
- **H-802:** Move router construction and caching to module scope with explicit dependencies.
- **H-803:** Define version once and expose it to package metadata and FastAPI.
- **H-804:** Choose the next release version and add a changelog/release checklist.
- **H-805:** Update test/provider/tool counts and Docker/security instructions.
- **H-806:** Add an architecture decision record for single-user authentication and sessions.
- **H-807:** Archive or label historical evaluation documents so they are not mistaken for current
  state.

### Acceptance criteria

- Existing CLI commands and help snapshots remain compatible.
- No individual CLI command module becomes a new monolith.
- Package, API, and documentation versions agree.
- README quick start is verified from a clean checkout.
- Current evaluation and enhancement plan are linked from the documentation index.

### Recommended commits

1. `refactor(cli): split command families`
2. `refactor(web): make router construction explicit`
3. `docs: synchronize release and deployment guidance`

## Release gates

### Gate A — Reliable local beta

Requires WP-0, WP-1, and WP-2.

- Clean clone builds and starts.
- Quote/signal WebSockets work under integration tests.
- Python and frontend quality gates pass.

### Gate B — Secure single-user release

Requires Gate A plus WP-3, WP-4, and WP-5.

- Remote exposure requires authentication.
- Conversations are session-scoped.
- Database resources close cleanly.

### Gate C — Maintained production release

Requires Gate B plus WP-6, the critical parts of WP-7, and metadata tasks from WP-8.

- CI validates Python, frontend, Docker, and runtime smoke behavior.
- Coverage and typing have enforced, honest baselines.
- Versioned documentation matches the shipped artifact.

## Execution checklist

Use this table as the live status ledger. Change only the status and PR/commit columns during
implementation; keep task details in the work-package sections.

| Work package | Status | PR/commit | Verification evidence |
|---|---|---|---|
| WP-0 Baseline repair | Not started | — | — |
| WP-1 WebSocket correctness | Not started | — | — |
| WP-2 Reproducible Docker build | Not started | — | — |
| WP-3 Single-user security | Not started | — | — |
| WP-4 Session isolation | Not started | — | — |
| WP-5 Database lifecycle | Not started | — | — |
| WP-6 Complete CI surface | Not started | — | — |
| WP-7 Quality and coverage | Not started | — | — |
| WP-8 Maintainability and docs | Not started | — | — |

## First executable slice

Start with WP-0 and WP-1 in one short stabilization cycle:

1. Create branch `codex/runtime-stabilization`.
2. Restore repository-wide formatting compliance.
3. Add failing WebSocket integration tests that reproduce missing subscriber registration.
4. Add the two missing `await` expressions.
5. Run the global definition of done.
6. Commit baseline formatting separately from the behavioral fix.
7. Open a PR containing exact test output and the before/after socket behavior.

After that PR is green, begin WP-2 without mixing authentication changes into the Docker build.
