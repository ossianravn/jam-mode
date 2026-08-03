# Episode handoff contract

Every JAM episode returns a human-readable `report_markdown` and a machine-readable `handoff`. The controller persists both before deciding whether another fresh session is justified.

## Generic core

The handoff contains:

- `status`: `progress`, `complete`, `needs_user`, `blocked`, or `error`.
- `summary`: concise result of the bounded episode.
- `progress_score`: 0–1 estimate of meaningful campaign progress.
- `task_profile` and `profile_reason`.
- `strategy_used` and `strategy_reason`.
- `completed_actions`: work actually performed.
- `decisions`: accepted, tentative, rejected, or deferred choices with rationale.
- `state_updates`: durable task state with a stable id, kind, status, evidence references, and confidence.
- `deliverables`: named outputs, their location when applicable, description, and completion state.
- `validation`: checks and their passed/failed/partial/not-run result.
- `blockers`, `risks`, `artifacts`, and `open_items`.
- Up to four `next_options`, each with objective, task profile, strategy, expected value, and reason.
- `recommended_next_option`, or null when no continuation is justified.
- `needs_user_input` and `user_question`.
- `completion_assessment`: goal reached, plateau state, and reason.
- `boundary_flags`: any operating boundary that prevents autonomous continuation.

A current episode may recommend a next objective but must not launch it. The external controller validates the recommendation against user state, operating boundaries, progress, expected value, and budgets.

## State-update examples

Engineering:

```json
{
  "id": "AC-4",
  "kind": "acceptance_criterion",
  "statement": "Legacy configuration aliases remain accepted.",
  "status": "validated",
  "evidence_refs": ["tests/test_config.py", "pytest tests/test_config.py"],
  "confidence": "high"
}
```

Documentation/content:

```json
{
  "id": "DOC-2",
  "kind": "draft",
  "statement": "Migration guide includes Windows and WSL examples.",
  "status": "complete",
  "evidence_refs": ["docs/migration.md"],
  "confidence": "not_applicable"
}
```

Planning:

```json
{
  "id": "DEP-3",
  "kind": "dependency",
  "statement": "The rollout depends on schema compatibility testing.",
  "status": "active",
  "evidence_refs": [],
  "confidence": "medium"
}
```

## Compatibility

JAM 0.2 and later normalize stored 0.1 research handoffs into the generic contract. Legacy claims, hypotheses, attempts, dead ends, open questions, and scope flags become state updates, completed actions, open items, and boundary flags without rewriting the original episode artifacts.
