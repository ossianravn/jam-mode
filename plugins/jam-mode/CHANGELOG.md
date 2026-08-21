# Changelog

## 0.3.0 — 2026-08-02

- Added named-agent model routing for the parent plus explorer, bulk worker, planner, implementer, producer, reviewer, validator, critic, and closer roles.
- Added `inherit`, `economy`, `balanced`, `quality`, and `custom` routing policies.
- Added `strict`, `fallback`, and `off` compatibility modes backed by Codex App Server `model/list`.
- Added per-role model and reasoning-effort overrides, role-appropriate model fallback, and nearest-supported-effort fallback with persisted warnings.
- Validates explicit efforts on inherited parent or child models against the installed catalog default while preserving normal model inheritance.
- Added separate parent and child Ultra opt-ins; child Ultra remains disabled by default and, when enabled, is limited by generated instructions to one read-only helper one generation deep.
- Added strategy-to-agent routes and generated marker-owned `$CODEX_HOME/agents/jam_*.toml` files with collision protection and one-writer instructions.
- Added `jam models`, `jam routing`, paused-campaign routing updates, and routing refresh on resume.
- Added MCP model-catalog and routing inspection/configuration tools, including paused-campaign reconfiguration and refresh.
- Persisted requested/resolved rosters, model catalog snapshots, routing warnings, collaboration activity, model events, and token usage.
- Added episode artifacts `routing.json`, `agent-activity.json`, `model-events.json`, and `token-usage.json`.
- Added in-place 0.3 database migration while preserving 0.1/0.2 campaign data and compatibility behavior.
- Made episode rows authoritative for active-episode and episode-count state, with migration diagnostics and database-enforced single-active-episode admission.
- Replaced independent lifecycle flags with one validated campaign status and a database-enforced single-live-campaign invariant; legacy flags remain derived read-only output.
- Made explicit state IDs campaign-scoped current-state keys while keeping generated compatibility IDs episode-scoped and preserving latest-update ordering.
- Made role override maps child-only so parent model and effort have one dedicated input path.
- Made Windows upgrades restore the existing marketplace if an active Codex process prevents the atomic directory swap.
- Updated WSL/Linux and native Windows installers and uninstallers to create/remove only JAM marker-owned agents.
- Expanded automated coverage for model-list pagination, routing policies, effort fallback, Ultra gating, agent collision safety, and paused-campaign routing changes.

## 0.2.0 — 2026-07-31

- Generalized JAM from research campaigns to any bounded Codex-compatible task.
- Added adaptive task profiles: general, research, security research, engineering, review, documentation, planning, data, operations, content, and mixed.
- Replaced the mandatory research handoff with a task-neutral contract covering actions, decisions, state, deliverables, validation, blockers, risks, artifacts, open items, and profile-aware next options.
- Added general strategies: parallel explore, critique/synthesize, planner/executor, producer/critic, and execute/validate, while retaining specialized duo and discover/reproduce workflows.
- Added conservative local operating-boundary defaults; explicit boundaries are required when network access is requested.
- Renamed user-facing authorized scope to operating boundaries, retaining `--scope` and `authorized_scope` as compatibility aliases.
- Added in-place migration for 0.1 SQLite databases and normalization for stored 0.1 research handoffs.
- Added campaign/episode profile fields to status, artifacts, MCP results, and summaries.
- Expanded tests for generic campaigns, profile propagation, boundary defaults, network gating, migration, and legacy compatibility.
- Hardened the companion and MCP launchers so the plugin package wins import resolution even when its root is already present later in `PYTHONPATH`.

## 0.1.0 — 2026-07-30

- Initial local Codex Desktop/CLI plugin and marketplace.
- Fresh-thread campaign controller over Codex App Server.
- Adaptive solo and multi-agent strategy contract.
- Persistent SQLite campaign state, transcript/memory review, structured handoffs, and continuation gates.
- Graceful pause-after-current and stop-after-current semantics.
- Bundled stdio MCP tools and companion CLI.
- WSL2 and native Windows installers with absolute installed MCP launcher paths.
- Strict local plugin preflight validation, including manifest identity and default-prompt limits.
- Correct plugin `.mcp.json` `mcpServers` wrapper for current Codex plugin ingestion.
- App Server approval, user-input, elicitation, timeout, and process-cleanup handling.
- Automated unit, MCP smoke, fake App Server integration, and installer tests.
