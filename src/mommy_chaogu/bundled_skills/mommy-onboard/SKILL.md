---
name: mommy-onboard
description: Explain, safely install, connect, diagnose, or repair the mommy-chaogu Agent-first investing toolbox, then leave it open for free-form research, Strategy Card, indicator, or monitoring exploration. Use for mommy-chaogu setup or onboarding with Claude Code, Kimi Code, Cline, or Codex, and to assess unsupported MCP hosts without pretending they have a managed adapter.
---

# Mommy Onboard

Explain the toolbox and manage the machine lifecycle. Keep two senses of "complete" separate:
configuration + four Skills (onboard / research / strategy / market-watch-loop) + a real MCP
initialize/tools-list + the privacy boundary passing means
the **integration is available** and the user can explore freely; an **investing or research goal** is
complete only when the user sees and understands a useful result from a flow they actually asked for.
A green doctor is a legitimate end of installation, not a reason to force a workflow before the user
asks for one.

## Explain the toolbox

Before discussing installation, explain in the user's language:

- mommy-chaogu is a local toolbox that the current host Agent composes; it is not another LLM or a
  dashboard the user must learn;
- the toolbox covers A-share/US market data, supported calculations and signals, Strategy Cards,
  and consent-gated local monitoring;
- the user can describe an investing or trading-observation workflow in natural language, while the
  Agent maps it to capabilities that actually exist;
- it does not execute trades, prove profitability, or run arbitrary custom indicators.

Do **not** require the user to choose a research / strategy / indicator / monitoring path before
installation. Move from the explanation to the install/permission plan, and let the user decide what
to ask for once the connection is verified.

For a custom indicator or workflow the user mentions in passing, preserve the exact formula and
intent. Do not substitute a similar supported indicator. Anything the available data and tools cannot
implement must remain manual or unavailable.

## Check managed-host compatibility

The managed lifecycle supports only `claude`, `kimi`, `cline`, and `codex`. Run
`mommy agent detect --json` only to detect those hosts. OpenClaw, Hermes, and other MCP hosts are not
valid `--host` values today.

For an unsupported host, do not invent detection, configuration paths, Skill destinations, doctor
success, or an installation command. Explain that mommy-chaogu exposes a portable stdio MCP server
but this host is not automated by `mommy agent` yet. Prepare a manual host-specific plan only after
verifying the host's current documentation and listing exact changes; otherwise stop before host
modification. The user may separately approve installing only the base CLI.

## Establish the executable

First check whether `mommy agent detect --json` is available. In a source checkout use
`uv run mommy agent detect --json`; otherwise use `mommy agent detect --json`.

If `mommy` is missing, present an installation plan before changing the machine. Include:

- the HTTPS repository source;
- the exact resolved Git commit or released version, never an unreported floating `main`;
- the isolated tool location managed by `uv`;
- that the Agent-managed external mode does not need a second LLM API key;
- which command will run and whether `uv` also needs installation.

Explain the real data boundary: keys and mommy-chaogu databases stay on the device by default;
public market requests reach external data providers, and the current host Agent/model processes
the conversation and returned tool data. Do not summarize this as “all data stays local.”

For an unreleased Git install, resolve the current commit, then pin the archive URL to that SHA.
Download an installer before running it; do not hide remote execution in a pipe. If a stable release
containing `mommy agent detect` exists, prefer that released version. After installation, rerun
`mommy agent detect --json`. If the command is still absent, state that the installed build lacks the
Agent-managed contract; do not continue by pretending an older release supports it.

Use `uv tool install --upgrade mommy-chaogu` for a qualifying stable release. For an unreleased
commit, use the resolved SHA in
`uv tool install --force "mommy-chaogu @ https://github.com/coffee-man666/mommy-chaogu/archive/<SHA>.tar.gz"`.
Show the exact command first. `--force` prevents an older installed build with the same package
version from being mistaken for this commit.

## Detect and plan

1. Run `mommy agent detect --json`.
2. If the user is clearly inside one host (for example you are talking to them through Codex), pass
   that host directly with `--host codex` (or the matching value) and treat any other detected CLI
   only as diagnostic context. Do not list every detected host as a fresh selection question, and
   never modify a host the user did not ask to connect. Only when detection is genuinely ambiguous
   and the user has not indicated a host should you show `auto_candidates` and ask which one to
   modify.
3. Ask in ordinary language whether the experience should use only public market data or may also
   access relevant local holdings, memory, and Strategy Cards. Use `market-only` unless the user
   explicitly chooses personal data.
4. Run:

   ```text
   mommy agent plan --host HOST --profile PROFILE --json
   ```

5. Translate the plan into a compact human summary: configuration target, the four Skills
   (mommy-onboard, mommy-research, mommy-strategy, and market-watch-loop for continuous
   intraday watch / polling scenarios), local MCP command, privacy scope, and restart
   requirement. Ask for permission to make exactly those changes.
   If the read-only plan matches a scope the user already approved, do not re-confirm; pause again
   only if command, paths, host, or privacy materially change.

The plan is read-only. Do not treat a plan as authorization.

## Connect and verify

After explicit approval, run:

```text
mommy agent connect --host HOST --profile PROFILE --timeout 20 --json
```

The timeout is a real execution deadline. Read the embedded doctor result rather than trusting the
word “connected”:

- `host_configuration` must be `ok`;
- all four Skills (mommy-onboard, mommy-research, mommy-strategy, market-watch-loop) must have
  `status=ok`;
- `mcp_initialize_and_list_tools` must say it actually ran initialize and tools/list;
- `privacy_boundary` must match the selected profile;
- `live_market_data=not_checked` is honest and expected until the user's chosen workflow actually
  needs and calls a market-data tool.

If any blocking check fails, do not claim success. Run
`mommy agent repair --host HOST --json` to show a repair proposal. Apply only a
`safe_to_apply=true` proposal after the user sees it, using `--apply`. If doctor reports modified
user configuration or a modified Skill, stop and preserve it; do not use force automatically.

Tell the user to restart the host Agent when `restart_required=true`. When every blocking check
passes, say plainly that the integration is available and stop. Do not imply an investing goal is
already complete, and do not push a workflow before the user asks for one.

## Invite free exploration

The toolbox is now reachable. Offer the directions below as optional examples — not a mandatory
menu — and let the user ask for something else or simply look around:

- For a market question, use `mommy-research` and the matching high-level `research_*` tool. Explain
  the answer, strongest evidence and timestamp, missing/stale data, fact versus inference, and one
  useful next step.
- For a method, use `mommy-strategy` and show a faithful, readable Strategy Card. Let the user revise
  it. Confirming meaning and granting permission to save are separate.
- For an indicator or composed workflow, restate its formula, inputs, universe, schedule, and output.
  Map every step to published tools, run one supported pass, and mark manual/unavailable parts. Do
  not claim the flow was saved unless a real persistence path was used.
- For monitoring, show the exact supported trigger and a current check first. Personal scope and
  monitor activation each require their own approval; a prepared candidate is not active.

When the user does pick a direction, finish by showing what it produced and what remains
unsupported. Do not expose raw tool JSON, a generated spec, or a tool count as the result. Do not
write a metadata flag to manufacture completion.

## Progressive permissions

- A `market-only` connection intentionally omits portfolio, memory, Strategy Card, and write tools.
- Never inspect personal SQLite files to bypass a profile.
- If the user later asks for relevant personal context, show a new personal connection plan and get
  explicit approval before reconnecting.
- Personal profile approval does not authorize saving a Strategy Card, saving a research conclusion,
  or enabling a monitor. Follow the separate consent rules in the corresponding Skill/tool.
- Do not ask the user to configure DeepSeek/OpenAI/Kimi keys for external-Agent reasoning.

## Completion receipt

Keep the receipt user-facing and split the two senses of "complete":

- **Integration available** (say this once the connection is verified): connected host, privacy
  scope, doctor result, and any honest degraded/not-checked item (for example
  `live_market_data=not_checked` is expected until a market tool is actually called).
- **Investing result** (only when the user actually ran a flow): the workflow they chose and a
  one-sentence summary of its useful result, plus where to continue (`mommy-research` or
  `mommy-strategy`).

Do not celebrate installation artifacts, schema validation, or tool count as the product outcome,
and do not block free exploration behind a forced first-task question.
