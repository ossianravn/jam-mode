from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contracts import normalize_strategy
from .episode_strategy import validate_agent_budget
from .handoff import normalize_handoff
from .store import Store


DEFAULT_TURN_TIMEOUT_SECONDS = 4 * 60 * 60


def _elapsed_minutes(campaign: dict[str, Any]) -> float:
    started = campaign.get("started_at") or campaign.get("created_at")
    try:
        parsed = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0)
    except (TypeError, ValueError):
        return 0.0


def _turn_timeout_seconds(campaign: dict[str, Any]) -> int:
    remaining_minutes = float(
        campaign.get("max_elapsed_minutes", 480)
    ) - _elapsed_minutes(campaign)
    remaining_seconds = int(remaining_minutes * 60)
    return max(0, min(DEFAULT_TURN_TIMEOUT_SECONDS, remaining_seconds))


def _recommended_option(handoff: dict[str, Any] | None) -> dict[str, Any] | None:
    if not handoff:
        return None
    options = handoff.get("next_options") or []
    index = handoff.get("recommended_next_option")
    if isinstance(index, int) and 0 <= index < len(options):
        option = options[index]
        return option if isinstance(option, dict) else None
    if options:
        valid = [option for option in options if isinstance(option, dict)]
        if valid:
            return max(valid, key=lambda option: float(option.get("expected_value") or 0.0))
    return None


def next_episode_plan(
    store: Store, campaign: dict[str, Any]
) -> tuple[str, str | None, str | None]:
    validate_agent_budget(campaign)
    last = store.last_episode(campaign["id"])
    if last and isinstance(last.get("handoff"), dict):
        handoff = normalize_handoff(last["handoff"])
        option = _recommended_option(handoff)
        if option:
            return (
                str(option.get("objective") or campaign["objective"]),
                normalize_strategy(option.get("strategy")),
                str(option.get("task_profile") or handoff.get("task_profile") or "general"),
            )
        open_item = (handoff.get("open_items") or [None])[0]
        if open_item:
            return (
                f"Resolve the highest-value open item: {open_item}",
                "duo_independent",
                str(handoff.get("task_profile") or campaign.get("task_profile") or "adaptive"),
            )
    profile = str(campaign.get("task_profile") or "adaptive")
    return campaign["objective"], "duo_independent", profile


def _budget_gate(campaign: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    if int(campaign.get("episode_count", 0)) >= int(campaign.get("max_episodes", 20)):
        return False, "stopped_budget", "Maximum episode count reached."
    if _elapsed_minutes(campaign) >= float(campaign.get("max_elapsed_minutes", 480)):
        return False, "stopped_budget", "Maximum elapsed campaign time reached."
    return True, None, None


def continuation_decision(
    campaign: dict[str, Any], handoff: dict[str, Any], *, turn_status: str
) -> tuple[bool, str, str, int]:
    """Return (continue, status, reason, new_low_progress_count)."""
    handoff = normalize_handoff(handoff)
    low_progress = int(campaign.get("low_progress_count", 0))

    if campaign.get("status") == "stopping_after_current":
        return False, "stopped", "Campaign was stopped by the user.", low_progress
    if campaign.get("status") == "pausing_after_current":
        return False, "paused", "JAM paused after the current episode.", low_progress
    if turn_status not in {"completed", "complete"}:
        return False, "error", f"Codex turn ended with status {turn_status}.", low_progress
    if handoff.get("boundary_flags"):
        return (
            False,
            "needs_input",
            "Continuation would cross or clarify an operating boundary: "
            + "; ".join(map(str, handoff["boundary_flags"])),
            low_progress,
        )
    if handoff.get("needs_user_input") or handoff.get("status") in {"needs_user", "blocked"}:
        return False, "needs_input", str(handoff.get("user_question") or handoff.get("summary")), low_progress
    if handoff.get("status") == "error":
        return False, "error", str(handoff.get("summary") or "Episode reported an error."), low_progress
    completion = handoff.get("completion_assessment") or {}
    if handoff.get("status") == "complete" or completion.get("goal_reached"):
        return False, "completed", str(completion.get("reason") or handoff.get("summary")), 0

    plateau = bool(completion.get("progress_plateau")) or float(
        handoff.get("progress_score") or 0.0
    ) < 0.12
    low_progress = low_progress + 1 if plateau else 0
    if low_progress >= int(campaign.get("max_low_progress", 2)):
        return (
            False,
            "paused",
            "Progress plateau threshold reached; user review is required before resuming.",
            low_progress,
        )

    option = _recommended_option(handoff)
    if not option:
        return False, "completed", "No materially useful next episode was proposed.", low_progress
    expected_value = float(option.get("expected_value") or 0.0)
    threshold = float(campaign.get("continuation_threshold", 0.55))
    if expected_value < threshold:
        return (
            False,
            "completed",
            f"Best next step value {expected_value:.2f} is below threshold {threshold:.2f}.",
            low_progress,
        )
    allowed, budget_status, budget_reason = _budget_gate(campaign)
    if not allowed:
        return False, str(budget_status), str(budget_reason), low_progress
    return True, "queued", str(option.get("reason") or "A valuable next episode is available."), low_progress
