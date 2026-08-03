from __future__ import annotations

import json
import re
from typing import Any

from .contracts import (
    CONFIDENCE_LEVELS,
    STATE_KINDS,
    STATE_STATUSES,
    normalize_strategy,
    normalize_task_profile,
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp_score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _confidence(value: Any) -> str:
    candidate = str(value or "not_applicable").strip().lower()
    return candidate if candidate in CONFIDENCE_LEVELS else "not_applicable"


def _state_status(value: Any) -> str:
    candidate = str(value or "active").strip().lower()
    legacy = {"supported": "validated"}
    candidate = legacy.get(candidate, candidate)
    return candidate if candidate in STATE_STATUSES else "active"


def _infer_legacy_profile(handoff: dict[str, Any]) -> str:
    if any(
        handoff.get(key)
        for key in ("established_claims", "hypotheses", "dead_ends", "open_questions")
    ):
        return "research"
    return "general"


def _legacy_state_updates(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for index, claim in enumerate(handoff.get("established_claims") or [], start=1):
        if not isinstance(claim, dict) or not str(claim.get("claim") or "").strip():
            continue
        updates.append(
            {
                "id": f"legacy-claim-{index}",
                "kind": "claim",
                "statement": str(claim["claim"]).strip(),
                "status": "validated",
                "evidence_refs": _string_list(claim.get("evidence_refs")),
                "confidence": _confidence(claim.get("confidence")),
            }
        )
    for index, hypothesis in enumerate(handoff.get("hypotheses") or [], start=1):
        if not isinstance(hypothesis, dict) or not str(hypothesis.get("statement") or "").strip():
            continue
        updates.append(
            {
                "id": str(hypothesis.get("id") or f"legacy-hypothesis-{index}"),
                "kind": "hypothesis",
                "statement": str(hypothesis["statement"]).strip(),
                "status": _state_status(hypothesis.get("state")),
                "evidence_refs": _string_list(hypothesis.get("evidence_refs")),
                "confidence": _confidence(hypothesis.get("confidence")),
            }
        )
    for index, item in enumerate(handoff.get("dead_ends") or [], start=1):
        statement = str(item or "").strip()
        if statement:
            updates.append(
                {
                    "id": f"legacy-dead-end-{index}",
                    "kind": "dead_end",
                    "statement": statement,
                    "status": "rejected",
                    "evidence_refs": [],
                    "confidence": "not_applicable",
                }
            )
    return updates


def _clean_state_updates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()
        if not statement:
            continue
        kind = str(item.get("kind") or "other").strip().lower()
        if kind not in STATE_KINDS:
            kind = "other"
        result.append(
            {
                "id": str(item.get("id") or f"state-{index}").strip() or f"state-{index}",
                "kind": kind,
                "statement": statement,
                "status": _state_status(item.get("status")),
                "evidence_refs": _string_list(item.get("evidence_refs")),
                "confidence": _confidence(item.get("confidence")),
            }
        )
    return result


def _clean_decisions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    allowed = {"accepted", "tentative", "rejected", "deferred"}
    for item in value:
        if not isinstance(item, dict):
            continue
        decision = str(item.get("decision") or "").strip()
        if not decision:
            continue
        status = str(item.get("status") or "tentative").strip().lower()
        result.append(
            {
                "decision": decision,
                "rationale": str(item.get("rationale") or "").strip(),
                "status": status if status in allowed else "tentative",
            }
        )
    return result


def _clean_deliverables(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    allowed = {"planned", "in_progress", "complete", "verified", "blocked"}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("description") or f"deliverable-{index}").strip()
        if not name:
            continue
        status = str(item.get("status") or "complete").strip().lower()
        result.append(
            {
                "name": name,
                "type": str(item.get("type") or "artifact").strip(),
                "location": str(item.get("location") or item.get("path") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "status": status if status in allowed else "complete",
            }
        )
    return result


def _clean_validation(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    allowed = {"passed", "failed", "partial", "not_run", "not_applicable"}
    for item in value:
        if not isinstance(item, dict):
            continue
        check = str(item.get("check") or "").strip()
        if not check:
            continue
        status = str(item.get("result") or "not_run").strip().lower()
        result.append(
            {
                "check": check,
                "result": status if status in allowed else "not_run",
                "evidence_refs": _string_list(item.get("evidence_refs")),
            }
        )
    return result


def _clean_risks(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    allowed = {"low", "medium", "high", "critical"}
    for item in value:
        if isinstance(item, str):
            risk = item.strip()
            if risk:
                result.append({"risk": risk, "severity": "medium", "mitigation": ""})
            continue
        if not isinstance(item, dict):
            continue
        risk = str(item.get("risk") or "").strip()
        if not risk:
            continue
        severity = str(item.get("severity") or "medium").strip().lower()
        result.append(
            {
                "risk": risk,
                "severity": severity if severity in allowed else "medium",
                "mitigation": str(item.get("mitigation") or "").strip(),
            }
        )
    return result


def _clean_artifacts(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        description = str(item.get("description") or "").strip()
        if not path and not description:
            continue
        result.append(
            {
                "type": str(item.get("type") or "artifact").strip(),
                "path": path,
                "description": description,
            }
        )
    return result


def normalize_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    legacy_profile = _infer_legacy_profile(handoff)
    task_profile = normalize_task_profile(handoff.get("task_profile"), default=legacy_profile)
    strategy = normalize_strategy(handoff.get("strategy_used"))

    state_updates = _clean_state_updates(handoff.get("state_updates"))
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
