# Model and reasoning routing

JAM separates the **parent/synthesizer** from named, bounded child roles. A campaign stores both the requested roster and the roster resolved against the installed Codex model catalog.

## Policies

| Policy | Intent | Parent | Typical children |
|---|---|---|---|
| `inherit` | Respect the parent and existing Codex defaults | inherited | inherited |
| `economy` | Minimize cost and latency for routine work | GPT-6-Astra / medium | GPT-6-Astra / low–high |
| `balanced` | Strong synthesis with economical bounded work | GPT-6-Astra / high | GPT-6-Astra / low–high |
| `quality` | Maximize quality for difficult, high-value work | GPT-6-Astra / max | GPT-6-Astra / medium–max |
| `custom` | Define every role explicitly | user configured | user configured |

All preset values are requests. With `strict` or `fallback` validation, JAM asks Codex App Server `model/list` which model ids and reasoning efforts are actually available.

## Validation modes

- `strict`: refuse to start or save when a requested model/effort is unavailable.
- `fallback`: substitute the nearest available model or effort and record a warning.
- `off`: preserve the requested roster without reading the installed catalog.

`max`, `xhigh`, and `ultra` are accepted only when advertised for the selected model. Child Ultra is disabled by default because nested delegation can make topology and usage less predictable. Parent and child Ultra have separate opt-in switches. When a child role is explicitly enabled and resolves to `ultra`, JAM's generated instructions permit at most one read-only helper at a time, one generation deep; nested writers, JAM controls, and scope expansion remain prohibited.

## Named roles

JAM writes only files marked `# JAM_MODE_MANAGED=1` under `$CODEX_HOME/agents/`:

| Role | Agent name | Default sandbox | Purpose |
|---|---|---|---|
| explorer | `jam_explorer` | read-only | Mapping, retrieval, evidence gathering, option discovery |
| bulk worker | `jam_bulk_worker` | read-only | Clear, separable, repeatable shards |
| planner | `jam_planner` | read-only | Decomposition, dependencies, acceptance criteria |
| implementer | `jam_implementer` | workspace-write | The single engineering/data/operations writer |
| producer | `jam_producer` | workspace-write | The single document/content/planning-output writer |
| reviewer | `jam_reviewer` | read-only | Correctness, regressions, security, acceptance review |
| validator | `jam_validator` | read-only | Tests, reproductions, measurements, falsification |
| critic | `jam_critic` | read-only | Adversarial challenge and alternative explanations |
| closer | `jam_closer` | read-only | Completion assessment and final consolidation |

JAM refuses to overwrite an unmarked personal agent file. A project-level `.codex/agents/jam_*.toml` would override the global managed agent, so JAM detects that collision before a campaign starts.

`sandbox_mode` in a custom-agent file is the role's default. Codex may reapply the parent turn's live sandbox and approval overrides when spawning a child, so a workspace-write parent can give a nominally read-only child broader runtime capability. JAM retains the no-edit rule in the child's developer instructions and permits only one writer, but use a read-only parent episode when runtime-enforced read-only access is required for all delegated roles.

The `sandbox_mode` in a managed custom agent is a default. A live permission override can supersede it, so JAM also restates read/write limits in the role instructions and enforces the campaign sandbox and operating boundaries at the parent/controller level.

## Strategy routes

The parent selects a strategy, invokes the exact named roles, waits for them, and performs the final evidence-weighted synthesis.

```text
parallel_explore   → jam_explorer × N → parent
map_reduce         → jam_bulk_worker × N → parent
builder_reviewer   → jam_implementer → jam_reviewer → parent
planner_executor   → jam_planner → one writer → parent
producer_critic    → jam_producer → jam_critic → parent
execute_validate   → one writer → jam_validator → parent
duo_independent    → jam_explorer + jam_critic → parent
discover_reproduce → jam_explorer + jam_validator → parent
closure             → jam_closer → parent
```

There is never more than one writer in a shared checkout. Child roles do not control campaign continuation and are instructed not to invoke JAM tools or recursively spawn agents.

## CLI controls

Inspect the installed catalog:

```bash
jam models
jam models --hidden
```

Inspect saved defaults:

```bash
jam routing
```

Select a preset:

```bash
jam routing --policy balanced --validation strict
```

Override roles:

```bash
jam routing \
  --policy custom \
  --model gpt-6-astra \
  --effort high \
  --role-model explorer=gpt-6-astra \
  --role-effort explorer=medium \
  --role-model implementer=gpt-6-astra \
  --role-effort implementer=high \
  --role-model reviewer=gpt-6-astra \
  --role-effort reviewer=high
```

Use `inherit` to clear an explicit override and return that role to the selected policy preset. Select the `inherit` policy when every role should follow ordinary Codex inheritance. The routing defaults live at `$CODEX_HOME/jam-mode/config.toml`; edit them through `jam routing` or `jam_configure_model_routing` so the managed agent files remain synchronized. The MCP tool accepts a paused campaign id, while `jam_refresh_campaign_routing` revalidates and rematerializes an existing paused roster.

Campaign-level overrides can be supplied at start:

```bash
jam start \
  -C ~/src/project \
  --objective "Implement, review, and validate the requested feature." \
  --model-policy quality \
  --role-model explorer=gpt-6-astra \
  --role-effort explorer=medium \
  --max-subagents 2
```

The campaign charter freezes its requested and resolved roster. Later changes to global defaults apply to new campaigns, not to an already-created campaign.

## Telemetry

Each episode stores:

- `routing.json`: the requested/resolved roster used for the episode;
- `agent-activity.json`: collaboration tool calls reported by App Server;
- `model-events.json`: reroute, verification, and safety-buffer events;
- `token-usage.json`: the latest token-usage notification when available.

These records distinguish intended routing from observed App Server activity. A reroute or unavailable event is retained rather than silently treated as the requested model having run.
