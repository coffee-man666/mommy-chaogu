# Give your Agent mommy-chaogu

Use this guide when a user asks you to install and take over mommy-chaogu. The goal is not a green
connection status. The goal is one useful, interpreted research result about something the user
actually cares about.

## Safety contract

Before changing the machine, show the user:

- the exact install source and immutable release/version or Git commit;
- which Agent configuration and Skill directories will change;
- the chosen privacy scope in ordinary language;
- that external-Agent mode does not require a second LLM API key;
- the exact next command.

Do not install, connect, widen privacy, save personal material, or enable monitoring before the
corresponding user approval.

## 1. Establish a pinned installation

Try this first:

```text
mommy agent detect --json
```

Inside a source checkout, use `uv run mommy agent detect --json` instead. If the command works,
continue to step 2.

If `mommy` is missing, prefer the newest stable release that documents `mommy agent detect`. When
using the Git repository before that release exists, resolve `refs/heads/main` to a commit SHA and
pin the package archive to that SHA. Never silently install a floating branch. If `uv` itself is
missing, download its official installer to a temporary file and inspect it before running; do not
pipe remote code straight into a shell.

For a stable release containing the Agent-managed commands, the command is:

```text
uv tool install --upgrade mommy-chaogu
```

The pinned package requirement has this shape:

```text
mommy-chaogu @ https://github.com/coffee-man666/mommy-chaogu/archive/<COMMIT_SHA>.tar.gz
```

Install that unreleased, immutable source with:

```text
uv tool install --force "mommy-chaogu @ https://github.com/coffee-man666/mommy-chaogu/archive/<COMMIT_SHA>.tar.gz"
```

`--force` matters while the Git build still shares a package version with an older release. Show
this exact command and resolved SHA to the user before running it.

After installation, rerun `mommy agent detect --json`. If that command is unavailable, stop and say
the installed build predates this Agent-managed contract.

## 2. Detect and show the plan

Run:

```text
mommy agent detect --json
```

If more than one host is detected, ask which Agent the user wants to modify. Then ask whether to
start with public market data only or also allow task-relevant local holdings, memory, and Strategy
Cards. Default to public market data (`market-only`).

Create a read-only plan:

```text
mommy agent plan --host <HOST> --profile <market-only|personal> --json
```

Translate its `changes` and `privacy` fields for the user. Wait for approval.

## 3. Connect and run a real probe

After approval:

```text
mommy agent connect --host <HOST> --profile <PROFILE> --timeout 20 --json
```

Success requires the embedded doctor checks for configuration, all three Skills, real MCP
initialize/tools-list, and privacy boundary to pass. `live_market_data=not_checked` is honest at
this stage. If a blocking check fails, show the failure and inspect a safe repair proposal:

```text
mommy agent repair --host <HOST> --json
```

Do not force-overwrite user-modified configuration or Skills. Restart the host Agent when requested.

## 4. Finish with the user's first research

Ask:

> 第一次你想研究哪只股票、哪个市场问题，或哪段投资观点？

Use the matching high-level `research_*` tool. Give the user a direct answer, successful evidence
with timestamps, missing/stale data, fact-versus-inference boundaries, and one useful next step.
Raw JSON, tool count, installation, or doctor status alone never completes onboarding.

After the first useful answer, offer—but do not automatically perform—one of these next actions:

- use `mommy-strategy` to turn a method into an approved local Strategy Card;
- reconnect with `personal` after a new privacy plan if relevant personal context is wanted;
- prepare a supported monitor candidate and ask for separate activation consent.
