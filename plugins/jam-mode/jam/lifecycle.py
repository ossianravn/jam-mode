from __future__ import annotations

from typing import Final


RUNNABLE_CAMPAIGN_STATUSES: Final[frozenset[str]] = frozenset(
    {"queued", "planning", "running"}
)
AFTER_CURRENT_STATUSES: Final[frozenset[str]] = frozenset(
    {"pausing_after_current", "stopping_after_current"}
)
LIVE_CAMPAIGN_STATUSES: Final[frozenset[str]] = (
    RUNNABLE_CAMPAIGN_STATUSES | AFTER_CURRENT_STATUSES
)
NON_LIVE_CAMPAIGN_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "paused",
        "stopped",
        "stopped_budget",
        "needs_input",
        "completed",
        "error",
    }
)
CAMPAIGN_STATUSES: Final[frozenset[str]] = (
    LIVE_CAMPAIGN_STATUSES | NON_LIVE_CAMPAIGN_STATUSES
)

_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "queued": frozenset(
        {"planning", "running", "paused", "stopped", "stopped_budget", "error"}
    ),
    "planning": frozenset({"running", "paused", "stopped", "stopped_budget", "error"}),
    "running": frozenset(
        {
            "queued",
            "pausing_after_current",
            "stopping_after_current",
            "paused",
            "stopped",
            "stopped_budget",
            "needs_input",
            "completed",
            "error",
        }
    ),
    "pausing_after_current": frozenset(
        {"stopping_after_current", "paused", "error"}
    ),
    "stopping_after_current": frozenset({"stopped", "error"}),
    "paused": frozenset({"queued", "stopped", "error"}),
    "stopped": frozenset({"queued", "error"}),
    "stopped_budget": frozenset({"queued", "stopped", "error"}),
    "needs_input": frozenset({"queued", "stopped", "error"}),
    "completed": frozenset({"queued", "stopped", "error"}),
    "error": frozenset({"queued", "stopped"}),
}


def validate_campaign_status(value: object) -> str:
    status = str(value or "").strip().lower()
    if status not in CAMPAIGN_STATUSES:
        raise ValueError(
            f"Unsupported campaign status {value!r}; use one of: "
            + ", ".join(sorted(CAMPAIGN_STATUSES))
        )
    return status


def validate_campaign_transition(current: object, target: object) -> str:
    current_status = validate_campaign_status(current)
    target_status = validate_campaign_status(target)
    if current_status == target_status:
        return target_status
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(
            f"Campaign status cannot transition from {current_status!r} "
            f"to {target_status!r}."
        )
    return target_status


def legacy_campaign_flags(status: object) -> dict[str, bool]:
    normalized = validate_campaign_status(status)
    return {
        "enabled": normalized in RUNNABLE_CAMPAIGN_STATUSES,
        "stop_after_current": normalized in AFTER_CURRENT_STATUSES,
        "termination_requested": normalized
        in {"stopping_after_current", "stopped"},
    }
