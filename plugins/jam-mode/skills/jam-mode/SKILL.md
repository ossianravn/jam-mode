---
name: jam-mode
description: Start, inspect, pause, resume, stop, or configure a bounded multi-session JAM campaign for any Codex-compatible task. Use when work should continue across naturally ending fresh sessions with Duo as the default, independent agent contributions and parent synthesis, relevant prior context, per-role model routing, and graceful pause after the current episode.
---

# JAM Mode

JAM Mode is a journey-aware campaign controller. It does not keep one Codex thread alive indefinitely. It creates one fresh, bounded episode at a time, records a task-neutral structured handoff, reviews campaign history and relevant subject memories, and starts another episode only when operating-boundary, user-input, progress, expected-value, and budget gates permit it.

JAM is task-general. A campaign may investigate, implement, review, document, plan, analyze data, perform bounded operations, produce content, or move between those phases.

## Core invariants

- Run at most one top-level JAM episode at a time.
- Each episode is a fresh Codex thread and is expected to finish naturally.
- Select a task profile per episode: general, research, security research, engineering, review, documentation, planning, data, operations, content, or mixed.
- Default to Duo: spawn an independent explorer and critic, wait for both, then synthesize in the parent. Other multi-agent strategies require a task-specific reason and at least two child contributions. Single-agent execution and solo fallback are unavailable.
- Parallelize genuinely independent work. Never use more than one writer in a shared checkout.
- Treat the campaign charter and operating boundaries as immutable during autonomous work.
- Disabling JAM means “finish the active episode, save its handoff, and do not start another.” It is not an interrupt.
- A JAM child session must not call mutating JAM tools or launch a nested campaign.

Read [task-profiles.md](references/task-profiles.md) for profile selection, [strategy-registry.md](references/strategy-registry.md) for reasoning topology, [model-routing.md](references/model-routing.md) for named roles and model/effort policies, [handoff-schema.md](references/handoff-schema.md) for durable episode state, and [operating-boundaries.md](references/operating-boundaries.md) for action limits. For security-sensitive work, also read [security-boundaries.md](references/security-boundaries.md).

## Starting a campaign

Collect or infer only what is already unambiguous from the user and current Codex host:

1. `objective`: the durable outcome or problem to solve.
2. `workspace`: an absolute existing directory as seen by this host. Do not silently use the plugin directory.
3. Optional `task_profile`: default to `adaptive` unless the user clearly requests a profile.
4. Optional `operating_boundaries`: resources, allowed actions, exclusions, and approval requirements.
5. Optional success criteria, model-routing policy or per-role model/effort overrides, limits, memory paths, and whether file writes or network access are permitted.

When boundaries are omitted for local, non-networked work, the controller creates conservative defaults limited to the workspace and sandbox. Explicit boundaries are required when network access is requested. Obtain explicit target/action boundaries for security research, deployment, external publication, production operations, third-party resources, credentials, destructive actions, or other elevated work. Never infer authorization from technical reachability.

Default to:

- `task_profile: adaptive`
- `sandbox: read-only` unless the objective clearly requires workspace changes
- `allow_network: false`
- `max_subagents: 2`
- saved model-routing defaults (`balanced` / `strict` on a new install)
- child Ultra disabled unless explicitly requested
- bounded episode and elapsed-time limits

Use `jam_start_campaign` after the required objective and workspace are present and any elevated-work boundaries are explicit. Starting a campaign is a state-changing action. After a successful start, verify its status and arrange follow-up in the invoking task using [campaign-follow-up.md](references/campaign-follow-up.md) before reporting the launch as handled. Report the campaign id, current state, and whether follow-up was actually scheduled. The invoking task owns monitoring and returning results; the controller owns campaign execution.

## Profile guidance

Use `adaptive` when the campaign may move between phases. Examples:

- Investigation → implementation → validation → documentation
- Planning → execution → review → closure
- Data inspection → transformation → quality checks → report
- Drafting → critique → revision → final verification

A profile guides the handoff vocabulary and validation style; it does not rigidly force one strategy. The episode may override a prior profile hint when the current objective has changed.

## Status and control

Use the MCP tools as follows:

- `jam_status`: inspect state, latest summary/profile, thread id, resolved roster, subagent/model activity, budgets, question, and artifact paths.
- `jam_list_models`: inspect models and reasoning efforts advertised by the installed Codex account.
- `jam_model_routing`: inspect saved defaults or a campaign's frozen requested/resolved roster.
- `jam_configure_model_routing`: update defaults for future campaigns, or update a paused campaign's frozen roster, and regenerate only JAM-managed custom agents.
- `jam_refresh_campaign_routing`: revalidate and rematerialize a paused campaign's current roster without changing its overrides.
- `jam_list_campaigns`: find campaign ids and prior campaigns.
- `jam_pause_after_current`: graceful stop-after-current. Never describe this as cancelling the active episode.
- `jam_resume_campaign`: append optional guidance, then run a fresh context-review and planning pass. Do not blindly reuse a prompt generated before the pause. After success, restore or reuse the campaign's follow-up according to [campaign-follow-up.md](references/campaign-follow-up.md).
- `jam_stop_campaign`: stop autonomous continuation after the current episode, if one is active; an explicit resume can reopen the campaign later.
- `jam_add_memory_path`: add an existing local file or directory to future context reviews.
- `jam_campaign_log` and `jam_doctor`: diagnose setup or controller failures.

## Choosing the user-facing control path

In Codex Desktop, the user can invoke this plugin with `@JAM Mode` or ask naturally for JAM controls. In Codex CLI, the user can invoke `$jam-mode`, ask naturally, or use the companion `jam` command. The plugin does not provide a permanent native left-sidebar toggle; represent that behavior through pause/resume tools and the companion command.

## Reporting behavior

For start/resume/pause/stop actions, state exactly what will happen next. For status, prioritize:

- current state and campaign task-profile preference;
- active or latest episode, selected profile/strategy, and thread id;
- latest result and completed deliverables;
- whether user input or approval is required;
- why continuation stopped or will continue;
- campaign artifact directory.

Do not claim that a background episode succeeded merely because the controller started. Use `jam_status` to verify actual progress.
