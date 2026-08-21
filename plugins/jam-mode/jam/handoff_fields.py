from __future__ import annotations

from typing import Any

from .contracts import (
    CONFIDENCE_LEVELS,
    STATE_KINDS,
    STATE_STATUSES,
    normalize_task_profile,
)

STATE_ID_ORIGIN_FIELD = "_jam_id_origin"
EXPLICIT_ID_ORIGIN = "explicit"
GENERATED_ID_ORIGIN = "generated"


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
                STATE_ID_ORIGIN_FIELD: GENERATED_ID_ORIGIN,
            }
        )
    for index, hypothesis in enumerate(handoff.get("hypotheses") or [], start=1):
        if not isinstance(hypothesis, dict) or not str(hypothesis.get("statement") or "").strip():
            continue
        raw_id = str(hypothesis.get("id") or "").strip()
        updates.append(
            {
                "id": raw_id or f"legacy-hypothesis-{index}",
                "kind": "hypothesis",
                "statement": str(hypothesis["statement"]).strip(),
                "status": _state_status(hypothesis.get("state")),
                "evidence_refs": _string_list(hypothesis.get("evidence_refs")),
                "confidence": _confidence(hypothesis.get("confidence")),
                STATE_ID_ORIGIN_FIELD: (
                    EXPLICIT_ID_ORIGIN if raw_id else GENERATED_ID_ORIGIN
                ),
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
                    STATE_ID_ORIGIN_FIELD: GENERATED_ID_ORIGIN,
                }
            )
    return updates


def _clean_state_updates(
    value: Any,
    *,
    preserve_internal: bool = False,
) -> list[dict[str, Any]]:
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
        raw_id = str(item.get("id") or "").strip()
        origin = EXPLICIT_ID_ORIGIN if raw_id else GENERATED_ID_ORIGIN
        if preserve_internal and item.get(STATE_ID_ORIGIN_FIELD) in {
            EXPLICIT_ID_ORIGIN,
            GENERATED_ID_ORIGIN,
        }:
            origin = str(item[STATE_ID_ORIGIN_FIELD])
        result.append(
            {
                "id": raw_id or f"state-{index}",
                "kind": kind,
                "statement": statement,
                "status": _state_status(item.get("status")),
                "evidence_refs": _string_list(item.get("evidence_refs")),
                "confidence": _confidence(item.get("confidence")),
                STATE_ID_ORIGIN_FIELD: origin,
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
