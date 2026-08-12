---
name: mommy-onboard
description: Explain, safely install, connect, diagnose, or repair the mommy-chaogu Agent-first investing toolbox, then help the user complete a first chosen research, Strategy Card, indicator check, or monitoring workflow. Use for mommy-chaogu setup or onboarding with Claude Code, Kimi Code, Cline, or Codex, and to assess unsupported MCP hosts without pretending they have a managed adapter.
---

# Mommy Onboard

Explain the toolbox, manage the machine lifecycle, then hand the chosen outcome to
`mommy-research` or `mommy-strategy`. A configured MCP entry or a green doctor is not onboarding
completion. Completion means the user has received and understood one useful result from a workflow
they chose.

## Explain and choose the first outcome

Before discussing installation, explain in the user's language:

- mommy-chaogu is a local toolbox that the current host Agent composes; it is not another LLM or a
  dashboard the user must learn;
- the toolbox covers A-share/US market data, supported calculations and signals, Strategy Cards,
  and consent-gated local monitoring;
- the user can describe an investing or trading-observation workflow in natural language, while the
  Agent maps it to capabilities that actually exist;
- it does not execute trades, prove profitability, or run arbitrary custom indicators.

Ask one open question and retain the answer through installation:

> 你最想先让它帮你完成什么：看一次行情或研究、整理一套投资方法、定义一个指标/观察条件，
> 还是搭一条持续监测流程？

For a custom indicator or workflow, preserve the exact formula and intent. Do not substitute a
similar supported indicator. Anything the available data and tools cannot implement must remain
manual or unavailable.

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
2. If `selection_required=true`, show the detected hosts and ask the user which one to modify. Never
   guess when multiple hosts are present.
3. Ask in ordinary language whether the first experience should use only public market data or may
   also access relevant local holdings, memory, and Strategy Cards. Use `market-only` unless the user
   explicitly chooses personal data.
4. Run:

   ```text
   mommy agent plan --host HOST --profile PROFILE --json
   ```

5. Translate the plan into a compact human summary: configuration target, three Skills, local MCP
   command, privacy scope, and restart requirement. Ask for permission to make exactly those changes.

The plan is read-only. Do not treat a plan as authorization.

## Connect and verify

After explicit approval, run:

```text
mommy agent connect --host HOST --profile PROFILE --timeout 20 --json
```

The timeout is a real execution deadline. Read the embedded doctor result rather than trusting the
word “connected”:

- `host_configuration` must be `ok`;
- all three Skills must have `status=ok`;
- `mcp_initialize_and_list_tools` must say it actually ran initialize and tools/list;
- `privacy_boundary` must match the selected profile;
- `live_market_data=not_checked` is honest and expected until the user's chosen workflow actually
  needs and calls a market-data tool.

If any blocking check fails, do not claim success. Run
`mommy agent repair --host HOST --json` to show a repair proposal. Apply only a
`safe_to_apply=true` proposal after the user sees it, using `--apply`. If doctor reports modified
user configuration or a modified Skill, stop and preserve it; do not use force automatically.

Tell the user to restart the host Agent when `restart_required=true`. Resume the value loop after
restart.

## Complete first value

Return to the first outcome chosen before installation:

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

Do not expose raw tool JSON, a generated spec, or a tool count as the result. Only after the chosen
result is visible and the user has had a chance to react may you say onboarding is complete. Do not
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

Keep the final receipt user-facing:

- connected host and privacy scope;
- doctor result and any honest degraded/not-checked item;
- the first workflow the user chose and a one-sentence summary of its useful result;
- where to continue (`mommy-research` or `mommy-strategy`).

Do not celebrate installation artifacts, schema validation, or tool count as the product outcome.
