# JAM Mode 0.3.0 build report

Build date: 2026-08-02

## Release scope

This release adds validated, per-role model and reasoning-effort routing to the task-general JAM campaign controller.

It includes:

- `inherit`, `economy`, `balanced`, `quality`, and `custom` routing policies;
- `strict`, `fallback`, and `off` installed-catalog validation modes;
- per-campaign parent and role-specific model/effort overrides;
- separate parent and child Ultra opt-ins, with bounded one-level read-only delegation instructions for Ultra children;
- nine marker-owned named custom agents under `$CODEX_HOME/agents/`;
- strategy-to-agent routing with parent synthesis and a single-writer rule;
- `model/list` pagination and model/effort compatibility checks through Codex App Server;
- role-appropriate model fallback and nearest-effort fallback with persisted warnings;
- requested/resolved routing snapshots in campaign and episode state;
- collaboration activity, model event, and token-usage episode artifacts;
- CLI commands `jam models` and `jam routing`;
- MCP tools for model catalog inspection, global or paused-campaign routing configuration, and paused-campaign refresh;
- safe routing updates for paused campaigns and blocked changes during live episodes;
- in-place database migration from JAM 0.1 and 0.2;
- WSL/Linux and native Windows installer support for generating and removing only JAM-managed agent files.

All task-general 0.2 capabilities remain: adaptive profiles, fresh sessions, structured handoffs, cumulative state, transcript and memory review, operating boundaries, graceful stop-after-current behavior, continuation gates, detached controllers, and local Desktop/CLI/MCP access.

## Verification performed

The final source tree was checked with:

```text
python3 scripts/validate_plugin.py .
python3 -m compileall -q jam mcp scripts
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n scripts/install-wsl.sh scripts/uninstall-wsl.sh
git diff --check
```

The release archive was additionally checked by:

```text
unzip -t jam-mode-codex-plugin-0.3.0.zip
extracting the ZIP into a clean directory
running the plugin validator and complete automated suite from the extracted payload
checking that no .git, __pycache__, .pyc, or .pyo entries were shipped
verifying SHA-256 checksums
```

All **49 automated tests passed** in the final source-tree run and in the extracted ZIP verification run.

The automated suite covers:

- plugin, marketplace, skill, MCP, and manifest layout;
- MCP initialization, parent/child tool listing, campaign-routing schemas, child-session restrictions, and tool invocation;
- App Server initialization, approvals, user input, elicitation, current time, event handling, turn completion, and model-list pagination;
- a complete episode against a deterministic protocol-faithful fake `codex app-server`;
- balanced role routing and strategy routes;
- strict/fallback effort validation;
- unavailable-model fallback;
- parent and child Ultra gating plus bounded nested-delegation instructions;
- managed-agent generation, marker ownership, removal, personal-file collision protection, and project-agent collision protection;
- global routing configuration round trips;
- paused-campaign routing reconfiguration and refresh;
- requested/resolved roster persistence and episode routing artifacts;
- task profiles, operating-boundary defaults, network gating, and legacy aliases;
- generic and legacy handoff parsing and normalization;
- campaign persistence, leases, pause/resume, expected-value, progress, plateau, user-input, boundary, and budget gates;
- transcript extraction, memory inventory, relevance selection, secret filtering, and symlink filtering;
- WSL installer and uninstaller behavior against a fake Codex CLI;
- companion-launcher import behavior.

## Environment limitation

The build container did not provide an authenticated executable Codex installation, a live Codex Desktop host, or native Windows PowerShell. Therefore, no real model turn, live Desktop plugin load, live account model-catalog validation, or native Windows installer execution was performed in the build environment. App Server and marketplace command integration were exercised with deterministic protocol-faithful fakes, and Windows scripts were reviewed as source. Run the following on the target machine:

```bash
jam doctor
jam models
jam routing
```

Model and effort availability is account- and client-catalog-dependent; the release intentionally resolves that information at installation use time rather than claiming that every preset entry is available everywhere.
