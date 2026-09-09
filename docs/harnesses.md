# Using JAM with signed-in coding harnesses

Choose one harness when creating a campaign. All of its episodes and child agents
use that harness; resume preserves the choice. Model selection is separate: a
Claude model selected through GitHub Copilot still uses the Copilot harness.

The new adapters are experimental. Their protocol fixtures and local process
checks are tested, but no live account-backed campaign has been verified. JAM
checks the installed version and refuses incompatible adapters instead of
switching harnesses, credentials, or models.

## Setup

JAM's portable Python launcher works without installing the Codex plugin. From
the repository root, use Python 3.11 or later:

```text
python plugins/jam-mode/scripts/jam.py harnesses
python plugins/jam-mode/scripts/jam.py doctor --harness claude-code
python plugins/jam-mode/scripts/jam.py models --harness copilot
```

Use `python3` if that is your Python command. An existing `jam` launcher accepts
the same arguments. The selected harness executable must be on the same host's
PATH as Python. Windows requires native executables; `.cmd`, `.bat`, and `.ps1`
wrappers are not accepted for native adapters.

| Harness | Initial supported contract | Authentication and restrictions |
| --- | --- | --- |
| `codex` | Existing App Server implementation | Existing Codex account, routing, and sandbox behavior. Historical campaigns default here. |
| `claude-code` | Claude Code 2.1.219 or later with forwarded child events | Existing personal Pro/Max Claude subscription; native Windows/Linux without managed policy. WSL/macOS and managed accounts are refused until effective policy isolation can be established. |
| `copilot` | Copilot CLI 1.0.83, SDK protocol 3 | Existing signed-in Copilot account. Per-role effort overrides are unsupported. Other versions are refused. |
| `opencode` | OpenCode 1.18.30 native server | Existing GitHub Copilot OAuth in OpenCode; explicit `github-copilot/<model>` required. Other providers and effort variants are unsupported. |

Version support describes the implemented protocol contract, not a live test
result. Locally inspected on 2026-09-09: Claude Code 2.1.226, Copilot 1.0.5
(incompatible), and no OpenCode executable. Nothing was installed or logged in by
this change.

Sign in using the native tool before starting a campaign. JAM does not create
accounts, perform login, purchase access, or accept direct provider API keys for
the new adapters. `harnesses`, `doctor`, and `models` do not run model tasks.
Model catalogues may be advertised or unavailable rather than account-verified;
JAM reports that distinction.

## Start and resume

```text
python plugins/jam-mode/scripts/jam.py start --harness claude-code --workspace /absolute/workspace --objective "Review the design and produce a supported recommendation." --max-episodes 1
```

Replace the workspace with an absolute path on the execution host. Starting a
campaign runs the selected account-backed harness and consumes its normal usage.
The default campaign is read-only. Add `--sandbox workspace-write` for authorized
file edits; provide explicit operating boundaries when enabling network access.

Use `--model <full-model-id>` and repeated `--role-model ROLE=MODEL` arguments for
parent and role choices. Native harnesses default to `inherit` and `strict`,
independently of saved Codex defaults. They support `inherit`/`custom` policies;
Codex presets, Ultra, and cross-model fallback do not apply. Strict routing checks
observed model identity during execution. Claude aliases require validation
`off`; full IDs are required when an explicit strict model is selected.

For OpenCode, supply `--model github-copilot/<model-id>` from your native account.
JAM currently does not fetch an offline OpenCode account catalogue.

```text
python plugins/jam-mode/scripts/jam.py status CAMPAIGN_ID
python plugins/jam-mode/scripts/jam.py pause CAMPAIGN_ID
python plugins/jam-mode/scripts/jam.py routing CAMPAIGN_ID
python plugins/jam-mode/scripts/jam.py resume CAMPAIGN_ID
```

Pause finishes the current episode before stopping continuation. Update routing
only when the campaign is inactive. The harness itself cannot be changed; create
a new campaign to select another harness.

## Calling JAM through MCP

The existing stdio MCP server is harness independent. Register this process in
your client's MCP configuration using absolute paths:

```json
{
  "command": "/absolute/path/to/python",
  "args": ["/absolute/path/to/jam-mode-marketplace/plugins/jam-mode/mcp/jam_mcp.py"],
  "env": {"JAM_HOME": "/absolute/path/to/shared-jam-state"}
}
```

This is the server process specification; the enclosing configuration structure
depends on the client. On Windows use a native Python executable and Windows
paths. No client configuration is changed automatically.

Use `jam_list_harnesses`, `jam_doctor` with `harness`, `jam_list_models` with
`harness`, and `jam_start_campaign` with `harness`. Status includes the saved
harness. All clients must use the same `JAM_HOME` to see the same campaigns.
Without it, JAM preserves its existing state location under
`$CODEX_HOME/jam-mode` (or `~/.codex/jam-mode`).

## Execution guarantees and limits

The controller preserves JAM's budgets, independent child contributions,
handoffs, continuation gates, and campaign history. New adapters grant read tools
to children; the parent owns authorized edits. Shell commands are unavailable,
so an engineering task that needs executable tests must report that limitation
in its handoff. Native tool permission controls are not an OS sandbox.

External MCP servers, plugins, and hooks are isolated or refused by each adapter's
supported configuration. Network permission covers task tools; the harness still
needs network connectivity for its model service. The initial Copilot and
OpenCode adapters have no task network tools and reject `--network`.
Codex memories and Chronicle
are automatically loaded only for Codex campaigns. Explicit campaign memory paths
continue to work with every harness.

Windows subprocesses belong to a job object that terminates descendants on
cleanup. POSIX cleanup covers the owned process group; a process that deliberately
creates a new session is outside that group. This is process lifetime management,
not filesystem or network isolation.

Native logs are retained alongside canonical `events.jsonl` evidence. A parent
claiming it delegated is insufficient: completion requires verified successful
contributions from two distinct direct children and a valid final handoff.
Synthetic protocol tests establish parser and control behavior; a separately
authorized live smoke campaign is still required to verify each installed
harness and account end to end.

See the [design and primary sources](design/multi-harness-support.md) for the
adapter boundary and deferred mixed-harness work.
