# JAM multi-harness support

Status: implemented as experimental adapters; one harness per campaign and
existing signed-in accounts accepted by the user. See [current limits](../harnesses.md).
Evidence checked: 2026-09-09. No model inference requests were made.

## Intended experience

A user starts a JAM campaign with a selected harness and chooses parent and role
models available through that harness. JAM retains the existing objective,
independent contributions, one-writer rule, bounded episodes, progress gates,
handoffs, and pause/resume behavior. The first named targets are Codex, Claude
Code, GitHub Copilot CLI, and OpenCode. Other harnesses require explicit adapters.

One campaign uses one harness initially. Mixed-harness agents are deferred. Model
identity remains separate from harness identity: using a Claude model through
Copilot does not make the campaign a Claude Code campaign.

Authentication uses existing signed-in tools only. Direct Anthropic API access is
deferred. JAM must not silently use API keys or a different provider connection.

## Existing coupling

| Current owner | Required change |
| --- | --- |
| `plugins/jam-mode/jam/campaign_runner.py` | Select an execution adapter instead of importing Codex execution and agent installation directly. |
| `jam/appserver*.py` | Retain as the Codex adapter implementation, including existing protocol handling. |
| `jam/episode_result.py`, `jam/collaboration.py` | Separate generic handoff acceptance from harness-specific evidence parsing. Preserve historical Codex event replay. |
| `jam/service_models.py`, `jam/routing_installed.py`, `jam/routing_catalog.py` | Obtain model/effort capabilities from the selected harness; distinguish advertised support from account availability and observed execution. |
| `jam/routing_agents.py`, `jam/episode_strategy.py`, `jam/prompts.py` | Render the selected harness's agent configuration and instructions; do not write Codex agent files for another harness. |
| `jam/store_*.py`, `jam/service*.py`, CLI and MCP schemas | Persist the campaign harness, include it in routing snapshots, and propagate it through start, inspection, and resume. |
| `jam/paths.py`, `jam/memory.py`, installation files | Preserve existing state locations and explicit memory paths. Make automatic harness-memory discovery specific to the selected harness. |

Paths abbreviated with `jam/` are under `plugins/jam-mode/`.

## Proposed adapter interface

An adapter owns three operations:

1. **Inspect support:** executable/version, model catalogue source, supported
   effort values, permission controls, agent lifecycle evidence, and structured
   output support. Discovery must not run a model task or expose credentials.
2. **Prepare an episode:** validate the frozen routing and operating limits;
   prepare scoped agent definitions and a launch specification. Reject unsupported
   guarantees before starting work. Prefer per-run configuration to shared files.
3. **Run an episode:** launch a fresh session, collect native events, enforce the
   deadline and process cleanup, then return the final response, session identity,
   execution outcome, model observations, usage, and contribution evidence.

The shared controller owns campaign transitions, budgets, continuation decisions,
and handoff acceptance. Adapters translate native events into JAM's existing
canonical collaboration evidence format. Store original events alongside the translation so a parser
fix can be validated without repeating model work.

The evidence format must distinguish agent identity, parent relationship,
assignment/turn identity, final result, successful completion, and delivery to the
parent. Informational messages cannot invalidate completed work. A new assignment
must invalidate stale evidence. A parent claiming that reviews happened is not
sufficient evidence. Terminal success and an idle session are also insufficient.

Keep native delegation as the initial integration approach. Controller-managed
child processes would be a separate orchestration change, not a hidden substitute
when native evidence is unavailable. An adapter lacking verifiable contributions
must report that limitation instead of marking the episode complete.

## Harness evidence and local availability

| Harness | Evidence | Local observation |
| --- | --- | --- |
| Codex | Existing App Server integration and recorded campaign replay. | Existing working JAM integration. |
| Claude Code | Print mode supports JSON/streaming output and schema-constrained results. Custom agents and model selection are documented. | Windows CLI 2.1.226; help exposes structured output, custom agents, forwarded subagent text, and permission modes. |
| GitHub Copilot CLI | Programmatic execution supports model and custom-agent selection. Its SDK documents session agent definitions. | Windows CLI 1.0.5; help exposes JSONL, agent selection, tool controls, and effort selection. |
| OpenCode | CLI programmatic execution and server endpoints expose sessions, children, messages, and permissions. | Executable not found on the Windows or WSL PATH checked. |

Sources: [Claude programmatic usage](https://code.claude.com/docs/en/headless),
[Claude subagents](https://code.claude.com/docs/en/sub-agents),
[Copilot programmatic reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference),
[Copilot SDK agent definitions](https://github.com/github/copilot-sdk/blob/main/docs/features/custom-agents.md),
[OpenCode server](https://opencode.ai/docs/server/),
[OpenCode CLI](https://opencode.ai/docs/cli/).

The implemented contracts are pinned to
[Copilot SDK cd8cf15](https://github.com/github/copilot-sdk/tree/cd8cf15dc3f9e762615790aaed0a771a0f392755/nodejs)
(CLI 1.0.83, protocol 3) and
[OpenCode f69bece](https://github.com/anomalyco/opencode/tree/f69beceaffca94bed05a7669af93602125c37248/packages/opencode)
(1.18.30). Their tests use synthetic native events and fake transports, not
recordings from live campaigns.

Installed-version checks take precedence over examples in newer documentation.
Presence of a binary does not establish login, model access, or a successful
end-to-end JAM campaign. These checks did not inspect credentials or alter tool
configuration.

Claude's documented bare mode does not use subscription login. Therefore a
subscription-backed integration must not silently select that mode or fall back
to an API key. [Claude authentication behavior in bare mode](https://code.claude.com/docs/en/headless)

Model/effort policies must remain harness-specific. Do not translate Codex's
`ultra` or a GPT-only preset into an invented Claude equivalent. Preserve the
requested and observed model separately; reject unapproved substitutions where
strict routing was requested. Native agent configuration alone is insufficient:
Claude documents circumstances in which a requested subagent model is replaced.
[Claude subagent model selection](https://code.claude.com/docs/en/sub-agents#choose-a-model)

Tool permissions and filesystem/process isolation are different guarantees.
Each adapter must describe what it can enforce. A read-only campaign cannot be
implemented merely by telling an unrestricted agent not to write. Never use
permission-bypass flags as a compatibility fallback.

## Implementation sequence

1. Introduce the adapter interface with Codex as the default implementation.
   Preserve old campaigns, routing defaults, state location, and raw log replay.
2. Add campaign-level harness selection to storage, CLI, and MCP. Missing harness
   fields in historical records resolve to Codex. Freeze the choice when creating
   a campaign; resume uses that choice rather than the invoking application's identity.
3. Implement Claude Code against the installed CLI and synthetic protocol fixtures,
   including agent contribution evidence and the selected authentication approach.
4. Add Copilot and OpenCode adapters against explicitly supported versions. Keep
   compatibility checks and capability errors visible rather than claiming that
   an untested executable is fully supported.
5. Extend installer and usage documentation for invoking JAM from each harness.
   Keep existing Codex installs and saved campaigns intact.

CLI surface added in this implementation:

```text
jam harnesses
jam doctor --harness claude-code
jam models --harness copilot
jam start --harness opencode --workspace <path> --objective <objective>
```

Initial harness identifiers: `codex`, `claude-code`, `copilot`, `opencode`.

## Completion evidence required

- Existing Codex campaigns resume with unchanged interpretation and permission
  scope; the previously failing campaign log still verifies correctly.
- The selected harness survives persistence, controller detachment, and resume.
- Each adapter's protocol fixtures cover a successful independent pair, missing
  or failed contributions, informational messages, stale follow-ups, malformed
  handoff, unavailable model, permission refusal, and deadline cleanup.
- A mocked process test covers launch configuration and complete parsing through
  the same adapter interface used by the campaign controller.
- Before claiming live support, a separately authorized bounded smoke campaign
  verifies the installed harness, actual model identity, two contributions, and
  saved handoff. Account-backed model calls and missing-tool installation are not
  authorized by this research alone.
- No new or enlarged hand-maintained code file exceeds 300 lines.

## Deferred scope

Mixed-harness agents, direct provider API credentials, automatic installation,
automatic login, and live account-backed smoke campaigns are outside this change.
