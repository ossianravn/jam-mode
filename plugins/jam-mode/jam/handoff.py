from __future__ import annotations

import json
import re
from typing import Any

from .contracts import normalize_strategy, normalize_task_profile
from .handoff_fields import (
    _clamp_score,
    _clean_artifacts,
    _clean_decisions,
    _clean_deliverables,
    _clean_risks,
    _clean_state_updates,
    _clean_validation,
    _infer_legacy_profile,
    _legacy_state_updates,
    _string_list,
    STATE_ID_ORIGIN_FIELD,
)


class HandoffError(ValueError):
    pass


def _extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, count=1, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped, count=1)
    try:
        json.loads(stripped)
        return stripped
    except ValueError:
        pass

    # Find the first balanced top-level object while respecting strings.
    start = stripped.find("{")
    if start < 0:
        raise HandoffError("No JSON object was found in the final response.")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    raise HandoffError("The final response contained an unterminated JSON object.")


def parse_structured_response(text: str) -> tuple[str, dict[str, Any]]:
    if not text.strip():
        raise HandoffError("The episode produced no final response.")
    candidate = _extract_json_candidate(text)
    try:
        payload = json.loads(candidate)
    except ValueError as exc:
        raise HandoffError(f"The episode final response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HandoffError("The structured response must be a JSON object.")
    report = payload.get("report_markdown")
    handoff = payload.get("handoff")
    if not isinstance(report, str) or not isinstance(handoff, dict):
        raise HandoffError("Expected report_markdown (string) and handoff (object).")
    return report, normalize_handoff(handoff)

def normalize_handoff(
    handoff: dict[str, Any],
    *,
    preserve_internal: bool = False,
) -> dict[str, Any]:
    legacy_profile = _infer_legacy_profile(handoff)
    task_profile = normalize_task_profile(handoff.get("task_profile"), default=legacy_profile)
    strategy = normalize_strategy(handoff.get("strategy_used"))

    state_updates = _clean_state_updates(
        handoff.get("state_updates"),
        preserve_internal=preserve_internal,
    )
    if not state_updates:
        state_updates = _legacy_state_updates(handoff)

    completed_actions = _string_list(handoff.get("completed_actions"))
    for attempt in _string_list(handoff.get("attempts")):
        if attempt not in completed_actions:
            completed_actions.append(attempt)

    open_items = _string_list(handoff.get("open_items"))
    for question in _string_list(handoff.get("open_questions")):
        if question not in open_items:
            open_items.append(question)

    boundary_flags = _string_list(handoff.get("boundary_flags"))
    for flag in _string_list(handoff.get("scope_flags")):
        if flag not in boundary_flags:
            boundary_flags.append(flag)

    cleaned_options: list[dict[str, Any]] = []
    options = handoff.get("next_options")
    if isinstance(options, list):
        for option in options[:4]:
            if not isinstance(option, dict):
                continue
            objective = str(option.get("objective") or "").strip()
            if not objective:
                continue
            cleaned_options.append(
                {
                    "objective": objective,
                    "task_profile": normalize_task_profile(
                        option.get("task_profile"), default=task_profile
                    ),
                    "strategy": normalize_strategy(option.get("strategy")),
                    "expected_value": _clamp_score(option.get("expected_value")),
                    "reason": str(option.get("reason") or "").strip(),
                }
            )

    recommended = handoff.get("recommended_next_option")
    if not isinstance(recommended, int) or not (0 <= recommended < len(cleaned_options)):
        recommended = None

    completion_raw = handoff.get("completion_assessment")
    completion = completion_raw if isinstance(completion_raw, dict) else {}
    status = str(handoff.get("status") or "progress").strip().lower()
    if status not in {"progress", "complete", "needs_user", "blocked", "error"}:
        status = "progress"

    user_question_raw = handoff.get("user_question")
    user_question = str(user_question_raw).strip() if user_question_raw is not None else None
    if user_question == "":
        user_question = None

    return {
        "status": status,
        "summary": str(handoff.get("summary") or "").strip(),
        "progress_score": _clamp_score(handoff.get("progress_score")),
        "task_profile": task_profile,
        "profile_reason": str(handoff.get("profile_reason") or "").strip(),
        "strategy_used": strategy,
        "strategy_reason": str(handoff.get("strategy_reason") or "").strip(),
        "completed_actions": completed_actions,
        "decisions": _clean_decisions(handoff.get("decisions")),
        "state_updates": state_updates,
        "deliverables": _clean_deliverables(handoff.get("deliverables")),
        "validation": _clean_validation(handoff.get("validation")),
        "blockers": _string_list(handoff.get("blockers")),
        "risks": _clean_risks(handoff.get("risks")),
        "artifacts": _clean_artifacts(handoff.get("artifacts")),
        "open_items": open_items,
        "next_options": cleaned_options,
        "recommended_next_option": recommended,
        "needs_user_input": bool(handoff.get("needs_user_input")),
        "user_question": user_question,
        "completion_assessment": {
            "goal_reached": bool(completion.get("goal_reached")),
            "progress_plateau": bool(completion.get("progress_plateau")),
            "reason": str(completion.get("reason") or "").strip(),
        },
        "boundary_flags": boundary_flags,
    }


def public_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    public = dict(handoff)
    public["state_updates"] = [
        {
            key: value
            for key, value in item.items()
            if key != STATE_ID_ORIGIN_FIELD
        }
        for item in handoff.get("state_updates") or []
        if isinstance(item, dict)
    ]
    return public


def fallback_error_handoff(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "summary": message,
        "progress_score": 0.0,
        "task_profile": "general",
        "profile_reason": "The episode did not return a valid structured handoff.",
        "strategy_used": "solo",
        "strategy_reason": "The episode did not return a valid structured handoff.",
        "completed_actions": [],
        "decisions": [],
        "state_updates": [],
        "deliverables": [],
        "validation": [],
        "blockers": [message],
        "risks": [],
        "artifacts": [],
        "open_items": [],
        "next_options": [],
        "recommended_next_option": None,
        "needs_user_input": True,
        "user_question": "Review the episode log and decide whether to resume the campaign.",
        "completion_assessment": {
            "goal_reached": False,
            "progress_plateau": False,
            "reason": message,
        },
        "boundary_flags": [],
    }
