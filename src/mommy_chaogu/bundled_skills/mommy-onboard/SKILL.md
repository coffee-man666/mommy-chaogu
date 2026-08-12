---
name: mommy-onboard
description: Safely install or connect mommy-chaogu to a host Agent, explain planned file and privacy changes, run an honest MCP doctor probe, repair an unchanged managed connection, and guide the user to their first interpreted evidence-backed research result. Use when the user asks to install, set up, connect, diagnose, repair, or start using mommy-chaogu with Claude Code, Kimi Code, Cline, Codex, or another MCP-capable Agent.
---

# Mommy Onboard

Manage the machine lifecycle, then hand research interpretation to `mommy-research`. A configured
MCP entry or a green doctor is not onboarding completion. Completion means the user has received
and understood one useful research answer about a target they chose.

## Establish the executable

First check whether `mommy agent detect --json` is available. In a source checkout use
`uv run mommy agent detect --json`; otherwise use `mommy agent detect --json`.

If `mommy` is missing, present an installation plan before changing the machine. Include:

- the HTTPS repository source;
- the exact resolved Git commit or released version, never an unreported floating `main`;
- the isolated tool location managed by `uv`;
- that the Agent-managed external mode does not need a second LLM API key;
- which command will run and whether `uv` also needs installation.

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
- `live_market_data=not_checked` is honest and expected until the user chooses a first research
  target.

If any blocking check fails, do not claim success. Run
`mommy agent repair --host HOST --json` to show a repair proposal. Apply only a
`safe_to_apply=true` proposal after the user sees it, using `--apply`. If doctor reports modified
user configuration or a modified Skill, stop and preserve it; do not use force automatically.

Tell the user to restart the host Agent when `restart_required=true`. Resume the value loop after
restart.

## Complete first value

Ask one concrete, open question instead of running a fixed demo:

> 第一次你想研究哪只股票、哪个市场问题，或哪段投资观点？

Then use `mommy-research` and the matching high-level tool:

- one stock: `research_stock`;
- A-share market question: `research_market_brief`;
- US market question: `research_us_market`;
- sector or money flow: the corresponding research tool.

Do not expose raw tool JSON as the result. Explain in the user's language:

1. the direct answer;
2. the strongest successful evidence and its timestamp;
3. failed, missing, or stale data;
4. what is fact versus Agent inference;
5. one useful next step.

Only after that answer is visible and the user has had a chance to react may you say onboarding is
complete. Do not write a metadata flag to manufacture completion.

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
- the research question the user chose;
- a one-sentence summary of the useful result;
- where to continue (`mommy-research` or `mommy-strategy`).

Do not celebrate installation artifacts, schema validation, or tool count as the product outcome.
