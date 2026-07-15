# Project Evaluation — 2026-07-14

> Repository-wide evaluation of `mommy-chaogu` on branch `tui-overhaul`, after commit
> `d84c8ca` added Kimi K2.6 and Nova Bridge support.

## Executive summary

**Overall score: 7.1/10.**

The project is a strong and unusually capable personal-investing beta. Its domain architecture,
financial modeling practices, and automated test suite are impressive. The current Web/Docker
distribution is not production-ready, however: the clean-clone Docker path is incomplete, two
WebSocket subscriber registrations are not awaited, the publicly bound Web API has no
authentication, and resource-lifecycle warnings are hidden by otherwise green tests.

The recommended target is a **secure, reliable, single-user production release**, not a
multi-tenant SaaS platform.

## Scorecard

| Area | Score | Assessment |
|---|---:|---|
| Product vision and scope | 8.5 | Coherent user story with unusually broad investing workflows |
| Architecture | 8.0 | Strong domain boundaries and adapter-first design |
| Domain implementation | 8.0 | Good financial primitives, fallback behavior, and backtesting depth |
| Testing | 7.5 | Large and fast suite, but weak at runtime boundaries |
| Maintainability | 6.5 | Clear modules overall; orchestration and typing exceptions are accumulating |
| Documentation and developer experience | 7.0 | Extensive documentation, with stale metrics and deployment claims |
| Security | 4.5 | Suitable only for trusted local use in its current form |
| Deployment and operations | 4.5 | Frontend builds, but clean-clone Docker and runtime smoke coverage are incomplete |

## Evidence collected

The evaluation included source review, repository inspection, and the following local checks:

| Check | Result |
|---|---|
| Python non-network tests | **1,018 passed**, 13 deselected |
| Coverage | **62% overall** (`11,369` statements, `4,345` missed) |
| Mypy | No reported issues across 130 source files |
| Ruff lint | Passed |
| Changed-file formatting | Passed |
| Repository-wide formatting | 10 existing files require formatting |
| Vue TypeScript check | Passed |
| Vue production build | Passed |

The coverage run emitted substantial `ResourceWarning` output for unclosed SQLite connections.
Those warnings do not fail the current test suite.

## Strengths

### Product and domain design

- A clear transition from a simple family-oriented stock monitor into an integrated A-share
  research assistant.
- Natural-language routing, structured workflows, CLI, TUI, Web UI, and MCP surfaces share core
  services instead of reimplementing domain logic independently.
- Strong investment-specific features: prediction verification, portfolio analysis, costs,
  walk-forward analysis, market regimes, earnings comparison, and money-flow normalization.
- Appropriate use of `Decimal` for monetary values.
- Explicit source fallback, cache freshness, and stale-data preservation.

### Architecture

- `MarketDataAdapter` keeps upstream providers replaceable.
- SQLite databases are divided by responsibility: market, portfolio, agent, and reference data.
- Domain packages are generally cohesive and well named.
- The workflow engine and tool registry give LLM behavior a structured fast path.
- Memory is treated as an explicit service with episodic, prediction, semantic, and vector layers.

### Engineering practice

- The offline test suite is broad and fast enough to run continuously.
- Backtest, signal, watchlist, configuration, and memory-storage modules have particularly strong
  behavioral coverage.
- Dependencies are locked for Python and JavaScript.
- The frontend passes both `vue-tsc` and a production Vite build.
- Contributor documentation and issue templates emphasize user value and reproducibility.

## Findings

### Critical runtime and delivery gaps

#### E-001 — Clean-clone Docker build cannot supply the frontend

`Dockerfile` copies `web/dist/`, while `web/dist/` is ignored and is not present in the Git tree.
The image does not include a Node build stage. A developer with a locally generated `web/dist`
can build the image, but the documented clean-clone `docker compose up -d` path is incomplete.

**Impact:** the recommended onboarding and deployment path is unreliable.

#### E-002 — Quote and signal WebSocket subscribers are not awaited

`BackgroundService.add_quote_subscriber()` and `add_signal_subscriber()` are async, but the two
routes call them without `await`. The coroutine therefore does not register the socket, and the
immediate snapshot behavior cannot run.

**Impact:** quote and signal sockets may connect successfully without receiving broadcasts.

#### E-003 — Publicly reachable state-changing API has no authentication

Docker publishes the service on port 8000 and starts it on `0.0.0.0`. REST and WebSocket routes
have no authentication. Reachable clients can read or modify holdings/watchlists, read shared
agent history, and indirectly consume the configured LLM account. CORS allows every origin.

**Impact:** unsafe on an untrusted LAN, remote host, or port-forwarded deployment.

### High-priority reliability gaps

#### E-004 — Conversation state is global rather than session-scoped

Web clients share one `ConversationMemory` singleton. REST `ChatRequest.history` is declared but
ignored, and the WebSocket agent path uses the same global memory.

**Impact:** concurrent users or devices can mix context and expose prior conversations.

#### E-005 — CI does not test the complete shipped system

CI covers Python formatting, lint, typing, tests, and CLI help. It does not run frontend
typechecking/building, Docker builds, WebSocket integration tests, or a container health smoke
test. Repository-wide formatting currently identifies ten files, so the declared PR quality gate
would fail.

#### E-006 — SQLite resources are not consistently disposed

Coverage execution produced many unclosed database warnings across stores and tests. Sessions are
usually closed, but long-lived engines and test fixtures are not consistently disposed.

**Impact:** potential descriptor growth, file locking, and unreliable shutdown behavior.

#### E-007 — Runtime boundaries have weak coverage

Overall coverage is 62%. Domain-heavy modules are strong, but WebSocket routes, background
services, report rendering, CLI orchestration, live adapters, and several Web routes have low or
zero coverage. No tests exercise `/ws/quotes`, `/ws/signals`, or `/ws/agent` as real sockets.

### Maintainability and product-trust gaps

#### E-008 — “Mypy strict” excludes several core areas

Broad overrides suppress errors in agent, Web, backtest, CLI, cache, and selected market-data
modules. The reported zero-error result is useful but does not mean those core modules are strict.

#### E-009 — Router caching is ineffective

`_get_router()` declares an `lru_cache`-decorated builder inside the function. Each call creates a
new cached function, so the expensive router construction is repeated.

#### E-010 — Frontend has no automated behavior tests or lint gate

The frontend provides build and typecheck scripts but no unit/component tests, end-to-end smoke
test, or lint command.

#### E-011 — Documentation and metadata have drifted

The README reports 928 tests and four LLM providers; the evaluated state has 1,018 offline tests
and five providers. Tool and test counts also vary between documents. The project version remains
`0.1.0` despite substantial functional growth.

#### E-012 — Orchestration concentration is increasing

`cli.py` is large and has low direct coverage. It contains many parser, wiring, rendering, and
execution responsibilities, making changes harder to isolate.

## Production-readiness judgment

| Target | Judgment |
|---|---|
| Local developer use | Ready |
| Trusted single-user desktop use | Mostly ready after WebSocket fix |
| Trusted home LAN use | Needs authentication and session isolation |
| Publicly hosted single-user instance | Not ready |
| Multi-user or multi-tenant service | Out of scope and not ready |

## Recommended order

1. Repair WebSocket registration and test real socket behavior.
2. Make Docker build the frontend and verify a clean-clone container startup.
3. Add a single-user API token, constrained CORS, safe binding defaults, and session-scoped chat.
4. Close database engines during shutdown and make resource warnings actionable.
5. Expand CI to cover frontend, container, and boundary-level smoke tests.
6. Reduce typing exclusions, split CLI orchestration, and synchronize documentation/versioning.

The concrete implementation sequence and acceptance criteria are maintained in
[ENHANCEMENT-PLAN-2026-07-14.md](ENHANCEMENT-PLAN-2026-07-14.md).
