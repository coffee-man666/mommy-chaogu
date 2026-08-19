# Give your Agent mommy-chaogu

## Explain the product before the installation

mommy-chaogu is a **bounded, Agent-first local investing toolbox**. It is not another chat model and
it is not primarily a dashboard the user must learn. The current host Agent understands the user's
goal and composes the toolbox; mommy-chaogu supplies market data, deterministic calculations, local
records, and supported monitoring. Its value comes from composing reliable building blocks, not
from pretending every possible trading idea is already implemented.

The toolbox is meant to help the user:

- fetch and interpret A-share and US market data;
- combine currently supported indicators, signals, and research tools into a repeatable workflow;
- describe a custom indicator or observation rule in ordinary language, preserve its exact formula,
  and determine which parts the current toolbox can calculate;
- distill an article, report, conversation, or personal method into a readable Strategy Card;
- turn exactly supported price or change conditions into local monitoring after separate consent.

Do not describe it as a broker, automatic trading system, arbitrary indicator runtime, or proof
that a strategy is profitable. A user may define a custom indicator or workflow in ordinary
language, but first map its exact definition to capabilities that really exist. If the current
toolbox cannot calculate or persist part of it, label that part manual or unavailable. Never replace
it with a technically convenient proxy.

Explain this in the user's language, then move straight to the installation plan. **Do not require
the user to choose a research / strategy / indicator / monitoring path before installation.** The
toolbox is designed for free-form exploration once the connection is verified; the user can decide
what to ask for at any time, change direction, or just look around.

Keep two senses of "complete" separate:

- **Integration is available** once configuration, all four Skills (`mommy-onboard`, `mommy-research`,
  `mommy-strategy`, and `market-watch-loop`), a real MCP initialize/tools-list,
  and the privacy boundary check all pass. At that point the toolbox is reachable and the user can
  explore freely; you should not force a workflow to run.
- **An investing or research goal is complete** only when the user sees and understands a useful
  result from a flow they actually asked for, and can refine or reuse it. Installation artifacts,
  tool counts, or a green doctor never satisfy this — but neither is this a reason to block
  exploration behind a mandatory first-task question.

## Confirm that this host has a real connection path

The managed lifecycle currently knows how to modify **Claude Code, Kimi Code, Cline, and Codex**.
`mommy agent detect --json` only detects those hosts. OpenClaw, Hermes, and other MCP hosts are not
valid values for `--host` today.

If the current host is not one of the four managed hosts, do not invent a host value, configuration
path, Skill destination, successful probe, or claim that the managed setup supports it. Tell the
user that the portable stdio MCP server exists but this host's installation is not automated yet.
Only prepare a manual host-specific plan after verifying that host's current documentation and
listing its exact configuration and Skill changes; otherwise stop before modifying the host. A
separately approved base CLI installation is still allowed.

## Safety contract

Before changing the machine, show the user:

- the exact install source and immutable release/version or Git commit;
- which Agent configuration and Skill directories will change;
- the chosen privacy scope in ordinary language;
- that external-Agent mode does not require a second LLM API key;
- that secrets and product databases stay on the local device, while public market requests reach
  external data providers and tool results are processed by the current host Agent/model;
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

If no managed host is detected, follow the compatibility rule above. If the user is clearly running
inside one host (for example they are talking to you through Codex), pass that host directly with
`--host codex` (or the matching value) and treat any other detected CLI only as diagnostic context.
Do not list every detected host as a new selection question, and never modify a host the user did
not ask to connect.

Only when detection is genuinely ambiguous and the user has not indicated a host should you ask
which one to modify. Then ask whether to start with public market data only or also allow
task-relevant local holdings, memory, and Strategy Cards. Default to public market data
(`market-only`).

Create a read-only plan:

```text
mommy agent plan --host <HOST> --profile <market-only|personal> --json
```

Translate its `changes` and `privacy` fields for the user. Wait for approval. Avoid re-confirming
when the read-only plan matches a scope the user already approved; pause again only if command,
paths, host, or privacy materially change.

## 3. Connect and run a real probe

After approval:

```text
mommy agent connect --host <HOST> --profile <PROFILE> --timeout 20 --json
```

Success requires the embedded doctor checks for configuration, all four Skills, real MCP
initialize/tools-list, and privacy boundary to pass. `live_market_data=not_checked` is honest at
this stage. If a blocking check fails, show the failure and inspect a safe repair proposal:

```text
mommy agent repair --host <HOST> --json
```

Do not force-overwrite user-modified configuration or Skills. Restart the host Agent when requested.

When every blocking check passes, **the integration is available**: configuration is written, the
four Skills are installed, MCP initialize and tools/list really ran, and the privacy boundary matches
the chosen profile. Say this plainly and stop. Do not imply an investing or research goal is already
done, and do not push the user to run a workflow before they have asked for one.

## 4. Invite free exploration

The toolbox is now reachable. Offer optional directions the user can take whenever they like — these
are examples, not a mandatory menu, and the user may ask for something else entirely:

- **行情或研究**: use `mommy-research` and the matching high-level `research_*` tool. Give a direct
  answer, successful evidence with timestamps, missing/stale data, fact-versus-inference boundaries,
  and one useful next step.
- **投资方法或策略蒸馏**: use `mommy-strategy` to show a faithful, readable Strategy Card the user
  can correct. Confirmation of meaning and permission to save are separate questions.
- **自定义指标或流程**: restate the exact formula, inputs, schedule, universe, and desired output;
  map each part to current tools; run one supported pass. Clearly mark anything manual or
  unavailable, and do not claim persistence unless a real saved workflow exists.
- **持续监测**: first show the exact supported trigger and run a current check. Preparing a monitor
  is not activation; personal access and activation each require their own plan or consent. Use
  `market-watch-loop` for bounded polling requests and state the selected market data pipeline first.

When the user does pick a direction, finish by showing what it produced, what remains unsupported,
and how they can ask you to run or refine it again. Raw JSON, tool count, installation, a workflow
spec, or doctor status alone is never the product outcome — but you should not withhold exploration
until the user commits to one of these paths.
