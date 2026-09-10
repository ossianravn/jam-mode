# Campaign follow-up in the invoking task

Starting or resuming a campaign includes arranging a return path for its results. The invoking task monitors and reports; the JAM controller alone decides whether another episode may run. This workflow applies regardless of the campaign's selected harness. JAM episode sessions and their children must not create monitors or execute a second copy of the campaign work.

## After a successful start or resume

1. Read `jam_status` for the exact returned campaign id. If the campaign has already finished or needs input, return its result or question now instead of creating an unnecessary monitor.
2. Unless the user declines follow-up, discover the host's automation tool. In Codex Desktop, use `automation_update` to create a **heartbeat attached to the original invoking task**. Default to checking every five minutes unless the user specifies a cadence. Do not substitute a standalone scheduled task or an operating-system scheduler.
3. Inspect existing automation records using the host tool's instructions. Match the exact campaign id, state location, and original invoking task; reuse or reactivate its heartbeat instead of creating a duplicate. Preserve existing cadence and notification preferences. For mute/unmute requests, use the tool's notification-policy field rather than adding notification settings to the prompt.
4. Give the heartbeat a human-readable prompt with the exact campaign id, the state location when customized, and a working status tool or absolute CLI fallback command. Never target whichever campaign happens to be active. Include the check behavior below, and identify the heartbeat itself so it can pause its own schedule when finished.
5. Verify the automation tool returned success and retain its id in the invoking task. Report that follow-up is scheduled only after this succeeds. If unavailable or unsuccessful, keep the authorized campaign running, clearly state that automatic follow-up is unavailable, and give the exact command or tool arguments needed to check this campaign. Do not claim that launching the controller schedules notifications.

## Each heartbeat check

Read `jam_status` with the fixed campaign id, or use the verified companion CLI with `--json status <campaign-id>` against the same state store. Inspect campaign state, controller liveness, latest episode, error or user question, and report/handoff paths. JAM's persisted state and controller evidence determine progress; a task being unloaded in the app is not evidence that its campaign failed.

- While `queued`, `planning`, or `running`, stay quiet when progress is unchanged or non-actionable. Notify only on a meaningful change affecting the promised outcome or requiring user action. Avoid routine progress messages. Elapsed time alone does not establish failure.
- While `pausing_after_current` or `stopping_after_current`, keep checking until the active episode finishes and its handoff is saved.
- When `completed`, read the saved report and handoff, then return a concise result and artifact link in the original invoking task. Include unresolved choices or limitations; controller completion alone does not prove every success criterion was met. Pause this heartbeat after delivering the result.
- When `needs_input`, `error`, `paused`, `stopped`, or `stopped_budget`, report the useful completed work and the specific question, failure, or reason continuation ended. State the available next action, then pause this heartbeat. A later authorized resume restores follow-up.
- If a supposedly live campaign has no controller, inspect its latest log and episode before reporting a problem. If it cannot continue, explain what prevents progress and the available next action, then pause the monitor. If status cannot be read, disclose that monitoring is impaired without inventing a campaign outcome; retry transient failures on the next scheduled check and avoid repeating the same notification.

Monitoring does not authorize resuming a campaign, changing budgets or boundaries, restarting a controller, or performing campaign work. Preserve the original scope. For automation updates, use the returned automation id and preserve unrelated fields according to the tool's current schema.
