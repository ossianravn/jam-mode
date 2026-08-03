# JAM Mode 0.3 for Codex Desktop and CLI

JAM Mode is a local Codex plugin and companion controller for **bounded, adaptive campaigns across naturally ending fresh sessions**.

A campaign keeps one durable objective while allowing the work to move through investigation, planning, implementation, review, validation, documentation, data processing, operations, content production, or closure. Before each episode, JAM reviews the previous transcript, structured handoffs, cumulative campaign state, relevant Codex memories, Chronicle entries, and campaign-specific memory paths. It then selects the next bounded objective, the task profile, and the smallest useful solo or multi-agent strategy.

Every episode ends normally. JAM saves a human-readable report and machine-readable handoff, applies operating-boundary, user-input, progress, expected-value, plateau, and budget gates, and creates another fresh Codex thread only when continuation is justified. Pausing JAM means **finish the current episode and do not start another**; it does not interrupt an active turn.

## New in 0.3: named-agent model routing

JAM 0.3 adds a first-class routing layer for selecting the model and reasoning effort used by the parent and each delegated role.

- Five routing policies: `inherit`, `economy`, `balanced`, `quality`, and `custom`.
- Per-role model and reasoning-effort overrides.
- Named Codex custom agents such as `jam_explorer`, `jam_implementer`, and `jam_reviewer`.
- Installed-account validation through Codex App Server `model/list`.
- `strict`, `fallback`, and `off` validation modes.
- Separate opt-ins for parent Ultra and child Ultra.
- Strategy-to-agent routing with a one-writer rule for shared workspaces.
- Persisted requested and resolved rosters per campaign and episode.
- App Server collaboration activity, model events, and token-usage artifacts when available.
- Safe agent management: JAM modifies only files carrying the `# JAM_MODE_MANAGED=1` marker and refuses project-level name collisions.

Model IDs and effort levels in a preset are requests, not assumptions. With the default `fallback` validation, JAM asks the installed Codex client which models and reasoning efforts are available and records any substitutions. Use `strict` when a campaign must not start unless the requested roster is available exactly.

## Default balanced roster

A fresh installation uses the `balanced` policy with `fallback` validation:

| Role | Managed agent | Requested model | Requested effort | Purpose |
|---|---|---|---|---|
| Parent / synthesizer | primary thread | `gpt-5.6-sol` | `high` | Episode decisions, arbitration, synthesis, final response |
| Explorer | `jam_explorer` | `gpt-5.6-luna` | `medium` | Read-heavy mapping, retrieval, and evidence gathering |
| Bulk worker | `jam_bulk_worker` | `gpt-5.6-luna` | `low` | Clear, separable, repeatable shards |
| Planner | `jam_planner` | `gpt-5.6-sol` | `high` | Decomposition, dependencies, and acceptance criteria |
| Implementer | `jam_implementer` | `gpt-5.6-terra` | `high` | The single code/configuration/data writer |
| Producer | `jam_producer` | `gpt-5.6-terra` | `high` | The single document/content deliverable writer |
| Reviewer | `jam_reviewer` | `gpt-5.6-sol` | `high` | Correctness, security, regression, and acceptance review |
| Validator | `jam_validator` | `gpt-5.6-terra` | `medium` | Tests, reproductions, measurements, and falsification |
| Critic | `jam_critic` | `gpt-5.6-sol` | `high` | Adversarial challenge and competing explanations |
| Closer | `jam_closer` | `gpt-5.6-sol` | `high` | Completion assessment and final consolidation |

`economy` favors Luna and Terra. `quality` uses Sol more broadly and requests higher effort. `inherit` leaves every role to ordinary Codex inheritance. `custom` provides an empty base for explicit role assignments.

## Routing validation

| Mode | Behavior |
|---|---|
| `strict` | Refuse to save or start when a requested model or effort is unavailable |
| `fallback` | Select a role-appropriate available model or nearest supported effort and record a warning |
| `off` | Materialize the requested settings without calling `model/list` |

JAM accepts `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`, but catalog validation determines which values the selected model actually supports. Child Ultra is disabled by default because it can introduce nested delegation and less predictable topology or usage. Parent and child Ultra have separate switches. When a child role is explicitly allowed and resolves to `ultra`, its generated instructions permit at most one read-only helper at a time, one generation deep; nested writers, JAM controls, and scope expansion remain prohibited.

Custom-agent `sandbox_mode` is a default, not an absolute capability boundary: Codex can reapply the parent turn's live sandbox and approval overrides to spawned agents. JAM therefore also enforces the one-writer/read-only roles through explicit role instructions and campaign boundaries; use a read-only parent episode when a hard read-only runtime is required for every child.

## Task profiles

The campaign preference defaults to `adaptive`. Each fresh episode may select a more specific profile after reviewing the current objective and campaign state.

| Profile | Typical use |
|---|---|
| `adaptive` | Let each episode select the best profile |
| `general` | Clear bounded work without a specialist contract |
| `research` | Investigation, comparison, explanation, and evidence building |
| `security_research` | Authorized security investigation under explicit boundaries |
| `engineering` | Code, tests, configuration, migrations, refactors, and tooling |
| `review` | Audits, critiques, verification, and approval evidence |
| `documentation` | Technical or user documentation, examples, and migration guides |
| `planning` | Designs, decisions, milestones, dependencies, and executable plans |
| `data` | Inspection, transformation, quality checks, analysis, and reporting |
| `operations` | Bounded actions with verification, approval, and rollback awareness |
| `content` | Prose, structured content, creative material, and communications |
| `mixed` | One episode intentionally combines several profiles |

A campaign can move naturally through sequences such as:

```text
research → engineering → review → documentation → closure
planning → engineering → execute_validate → closure
data → documentation/content → review → closure
content → producer_critic → revision → closure
operations planning → user approval → execute_validate → closure
```

## Adaptive strategies and named routes

Top-level JAM episodes are serial. Inside an episode, the parent may delegate genuinely independent work and then synthesize the results.

| Strategy | Named-agent route |
|---|---|
| `solo` | Parent only |
| `parallel_explore` | `jam_explorer` × N → parent synthesis |
| `critique_synthesize` | `jam_critic` + `jam_reviewer` → parent |
| `map_reduce` | `jam_bulk_worker` × N → parent aggregation |
| `builder_reviewer` | `jam_implementer` → `jam_reviewer` → parent |
| `planner_executor` | `jam_planner` → one appropriate writer → parent |
| `producer_critic` | `jam_producer` → `jam_critic` → parent |
| `execute_validate` | One writer → `jam_validator` → parent |
| `duo_independent` | `jam_explorer` + `jam_critic` → parent |
| `discover_reproduce` | `jam_explorer` + `jam_validator` → parent |
| `evidence_arbitration` | `jam_reviewer` + `jam_critic` → parent |
| `reorientation` | `jam_planner` + `jam_critic` → parent |
| `closure` | `jam_closer` → parent |

The route is a deterministic baseline. The parent may omit a role that is unnecessary for the bounded episode, but it is instructed not to silently replace a routed named role with an anonymous worker. There is never more than one writer in a shared checkout.

## Included components

- A local Codex marketplace and plugin manifest.
- A `$jam-mode` / `@JAM Mode` skill.
- A dependency-free stdio MCP server exposing campaign and routing controls.
- A detached Python controller that uses `codex app-server`.
- One fresh App Server thread per episode and a structured handoff requested through `outputSchema`.
- A SQLite store shared by Desktop, CLI, MCP, and detached controllers.
- A `jam` terminal command.
- WSL/Linux and native Windows installers and uninstallers.
- Automated unit, MCP smoke, protocol, migration, installer, and fake App Server integration tests.

JAM intentionally permits one live campaign and one active top-level episode at a time. The campaign’s `max_subagents` setting caps requested parallelism inside an episode.

# Installation

See [INSTALL.md](INSTALL.md) for the full guide.

## Windows Desktop with WSL2 CLI — recommended

Use the same Codex host for Desktop and CLI. In Codex Desktop, switch the agent runtime to **WSL**, restart Desktop, and point WSL at the Windows Codex home:

```bash
export CODEX_HOME="/mnt/c/Users/<WindowsUser>/.codex"
export PATH="$HOME/.local/bin:$PATH"
```

From the extracted release:

```bash
cd jam-mode-marketplace
python3 plugins/jam-mode/scripts/validate_plugin.py plugins/jam-mode
bash plugins/jam-mode/scripts/install-wsl.sh
jam doctor
jam models
jam routing
```

Restart Desktop and open a new Desktop chat or CLI session so the plugin, skill, MCP server, and generated custom agents are reloaded.

## Native Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd jam-mode-marketplace
py -3 .\plugins\jam-mode\scripts\validate_plugin.py .\plugins\jam-mode
.\plugins\jam-mode\scripts\install-windows.ps1
jam doctor
jam models
jam routing
```

The native installer creates `jam.cmd` under `%CODEX_HOME%\bin` by default. Add that directory to `PATH` when necessary.

# Configure model routing

## Inspect the installed model catalog

```bash
jam models
jam models --hidden
```

Each entry shows the default and advertised reasoning efforts reported by the installed Codex account.

## Inspect or select a policy

```bash
jam routing
jam routing --policy economy --validation fallback
jam routing --policy balanced --validation strict
jam routing --policy quality --validation fallback
jam routing --policy inherit
```

Global defaults live at `$CODEX_HOME/jam-mode/config.toml`. Configure them through `jam routing` or `jam_configure_model_routing` so the generated custom-agent files remain synchronized. `jam_configure_model_routing` also accepts a paused campaign id; `jam_refresh_campaign_routing` revalidates a paused campaign without changing its overrides.

## Define a custom roster

```bash
jam routing \
  --policy custom \
  --model gpt-5.6-sol \
  --effort high \
  --role-model explorer=gpt-5.6-luna \
  --role-effort explorer=medium \
  --role-model implementer=gpt-5.6-terra \
  --role-effort implementer=high \
  --role-model reviewer=gpt-5.6-sol \
  --role-effort reviewer=high
```

Use `inherit` as an override value to clear an explicit assignment and return that role to the selected preset:

```bash
jam routing --role-model explorer=inherit --role-effort explorer=inherit
```

Use `--no-validate` only when deliberately saving requests without checking the installed catalog.

## Configure one paused campaign

A campaign freezes its requested and resolved roster when created. Global changes affect future campaigns. To alter an existing campaign, pause it and wait for its active episode to finish:

```bash
jam pause <campaign-id>
jam routing <campaign-id> --policy quality
jam routing <campaign-id> --role-model reviewer=gpt-5.6-sol --role-effort reviewer=max
jam routing <campaign-id> --refresh
jam resume <campaign-id>
```

JAM refuses to rewrite its shared custom-agent files while any campaign episode is live.

# Start campaigns

## Balanced adaptive software-delivery campaign

```bash
jam start \
  --name "Import workflow delivery" \
  -C ~/src/service \
  --profile adaptive \
  --sandbox workspace-write \
  --model-policy balanced \
  --model-validation fallback \
  --objective "Implement the import workflow, validate it, review it, update operator documentation, and stop when all acceptance criteria are verified." \
  --success "Focused and integration tests pass; documentation examples are verified; no material review finding remains." \
  --max-episodes 10 \
  --max-subagents 2
```

For ordinary offline workspace work, omitted operating boundaries become conservative local defaults.

## Campaign-level routing overrides

```bash
jam start \
  -C ~/src/project \
  --sandbox workspace-write \
  --model-policy balanced \
  --model gpt-5.6-sol \
  --effort high \
  --role-model explorer=gpt-5.6-luna \
  --role-effort explorer=low \
  --role-model reviewer=gpt-5.6-sol \
  --role-effort reviewer=xhigh \
  --objective "Diagnose the flaky integration test, implement the smallest safe fix, independently review it, and verify the relevant suites."
```

With `strict` validation, an unsupported `xhigh`, `max`, or other setting stops campaign creation rather than silently downgrading it. With `fallback`, the resolved roster and warning are stored in the campaign charter.

## Security-sensitive or networked campaign

Supply explicit operating boundaries:

```bash
jam start \
  --name "Local authorization validation" \
  -C ~/src/service \
  --profile security_research \
  --sandbox read-only \
  --model-policy quality \
  --objective "Confirm or reject whether identifier normalization can expose another local test identity's cached response." \
  --boundaries '{
    "resources": ["this repository", "its local test environment", "local test identities created for this campaign"],
    "allowed_actions": ["read source", "run local non-destructive tests", "inspect local test logs"],
    "excluded_actions": ["production", "third parties", "unrelated hosts", "persistence", "destructive actions"],
    "approval_required_for": ["network access", "scope expansion", "credential use"]
  }' \
  --success "Produce a deterministic reproduction or strong falsification with traceable evidence." \
  --max-episodes 12
```

Explicit boundaries are required when `--network` is requested and should be supplied for production, third-party, credentialed, destructive, deployment, publication, or other elevated work.

## From Codex Desktop

```text
@JAM Mode Start a balanced adaptive workspace-write campaign for this repository.

Objective:
Implement the requested feature, validate it, independently review it, update the
relevant documentation, and close only when the acceptance criteria are verified.

Limits:
- Maximum 8 episodes
- Maximum 2 subagents
```

## From Codex CLI

```text
$jam-mode Configure the balanced model-routing policy, show me the resolved roster,
then start a bounded campaign for this repository to diagnose and fix the flaky test.
```

# Campaign controls

```bash
jam status
jam --json status
jam list
jam pause
jam resume
jam resume --guidance "Prioritize runtime reproduction over additional static analysis."
jam stop
jam add-memory ./notes
jam log --tail 200
jam doctor
```

- `pause`: the active episode finishes naturally; no successor starts.
- `resume`: revalidates the frozen roster, rematerializes managed agents, reviews persisted state, and plans a fresh episode.
- `stop`: ends autonomous continuation after the active episode; an explicit later resume can reopen the campaign.
- `status`: shows campaign state, latest episode, selected profile/strategy, parent model, routing warnings, thread id, and artifacts.

# Persistent state and artifacts

By default, JAM stores state under `$CODEX_HOME/jam-mode`:

```text
config.toml                         global routing defaults
jam.sqlite3                        campaign and episode state
campaigns/<campaign-id>/charter.json
campaigns/<campaign-id>/campaign.md
campaigns/<campaign-id>/episodes/NNN/
  context.json
  prompt.md
  events.jsonl
  report.md
  handoff.json
  routing.json
  agent-activity.json
  model-events.json
  token-usage.json
  app-server.stderr.log
```

The campaign stores both the **requested** roster and the **resolved** roster. Episode artifacts snapshot the roster actually intended for that episode. App Server collaboration and model events are retained separately so a reroute, unavailable model, or incomplete agent observation is not misrepresented as proof that the requested model executed exactly as configured.

Managed custom-agent files are written to `$CODEX_HOME/agents/jam_*.toml`. JAM refuses to overwrite an unmarked file with the same name. It also refuses to start in a workspace containing `.codex/agents/jam_*.toml`, because project-scoped files would override the managed personal agents.

A role's `sandbox_mode` is a custom-agent default, not an unconditionally stronger permission boundary: live turn/session permission overrides can supersede it. JAM therefore repeats the role boundary in each managed agent's developer instructions and still applies the campaign sandbox and operating-boundary checks at the parent/controller level.

# Upgrade from 0.1 or 0.2

Run the 0.3 installer over the extracted 0.3 marketplace. Do not delete `$CODEX_HOME/jam-mode`.

```bash
bash plugins/jam-mode/scripts/install-wsl.sh
```

or:

```powershell
.\plugins\jam-mode\scripts\install-windows.ps1
```

Existing SQLite state is migrated in place. Version 0.1 research handoffs remain unchanged on disk and are normalized when read. Version 0.2 task-general campaigns receive the new routing fields when the database is opened. The installer creates a default routing config when one does not exist and materializes the JAM-managed agent files without requiring a live model-catalog call; campaign start and resume perform account-specific validation.

A backup before any upgrade is prudent:

```bash
cp -a "$CODEX_HOME/jam-mode" "$CODEX_HOME/jam-mode.backup"
```

# Uninstall

WSL/Linux:

```bash
bash plugins/jam-mode/scripts/uninstall-wsl.sh
```

Native Windows:

```powershell
.\plugins\jam-mode\scripts\uninstall-windows.ps1
```

The uninstallers remove the plugin, marketplace copy, companion command, and only marker-owned `jam_*.toml` files. They preserve `$CODEX_HOME/jam-mode`, including campaign history and routing configuration.

# Safety and operating model

- One active top-level campaign episode at a time.
- Fresh thread for every episode.
- No autonomous scope expansion.
- One writer in a shared checkout.
- Child agents cannot control campaign continuation and are instructed not to invoke JAM tools.
- Child Ultra is opt-in.
- Routing changes are blocked while a campaign episode is live.
- Network access requires explicit boundaries.
- The parent, not a child agent, synthesizes the episode result and writes the campaign handoff.
- Continuation is controlled by deterministic gates outside the model turn.

The public plugin surface does not provide a permanent custom Desktop sidebar toggle. JAM implements the intended behavior through `@JAM Mode`, `$jam-mode`, MCP tools, and `jam pause/resume/stop`.

# Development checks

From `plugins/jam-mode`:

```bash
python3 scripts/validate_plugin.py .
python3 -m compileall -q jam mcp scripts
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n scripts/install-wsl.sh scripts/uninstall-wsl.sh
```

The suite covers plugin layout, MCP restrictions, App Server protocol handling, model-catalog pagination, routing policies, effort fallback, Ultra gates, managed-agent collision safety, global and campaign routing updates, database migration, structured handoffs, continuation gates, transcript/memory handling, a complete fake App Server episode, and WSL installer behavior.

# Environment limitation

This package is a local reference implementation. The release build environment did not provide an authenticated Codex installation, a live Codex Desktop host, or native Windows PowerShell. No real model turn, live Desktop plugin load, or native Windows installer execution was performed there. App Server and marketplace command integration are covered with deterministic protocol-faithful fakes. Run `jam doctor`, `jam models`, and `jam routing` on the target machine after installation and after significant Codex updates.
