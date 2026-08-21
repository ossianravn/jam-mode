from __future__ import annotations

from typing import Any

from .contracts import (
    CONFIDENCE_LEVELS,
    EPISODE_TASK_PROFILES,
    STATE_KINDS,
    STATE_STATUSES,
    STRATEGIES,
)


_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string"},
        "rationale": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["accepted", "tentative", "rejected", "deferred"],
        },
    },
    "required": ["decision", "rationale", "status"],
    "additionalProperties": False,
}

_STATE_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": list(STATE_KINDS)},
        "statement": {"type": "string"},
        "status": {"type": "string", "enum": list(STATE_STATUSES)},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
    },
    "required": ["id", "kind", "statement", "status", "evidence_refs", "confidence"],
    "additionalProperties": False,
}

_DELIVERABLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"type": "string"},
        "location": {"type": "string"},
        "description": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["planned", "in_progress", "complete", "verified", "blocked"],
        },
    },
    "required": ["name", "type", "location", "description", "status"],
    "additionalProperties": False,
}

_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "check": {"type": "string"},
        "result": {
            "type": "string",
            "enum": ["passed", "failed", "partial", "not_run", "not_applicable"],
        },
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["check", "result", "evidence_refs"],
    "additionalProperties": False,
}

_RISK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk": {"type": "string"},
        "severity": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "mitigation": {"type": "string"},
    },
    "required": ["risk", "severity", "mitigation"],
    "additionalProperties": False,
}

_ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "path": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["type", "path", "description"],
    "additionalProperties": False,
}

_NEXT_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "task_profile": {"type": "string", "enum": list(EPISODE_TASK_PROFILES)},
        "strategy": {"type": "string", "enum": list(STRATEGIES)},
        "expected_value": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["objective", "task_profile", "strategy", "expected_value", "reason"],
    "additionalProperties": False,
}


HANDOFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "report_markdown": {"type": "string"},
        "handoff": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["progress", "complete", "needs_user", "blocked", "error"],
                },
                "summary": {"type": "string"},
                "progress_score": {"type": "number", "minimum": 0, "maximum": 1},
                "task_profile": {
                    "type": "string",
                    "enum": list(EPISODE_TASK_PROFILES),
                },
                "profile_reason": {"type": "string"},
                "strategy_used": {"type": "string", "enum": list(STRATEGIES)},
                "strategy_reason": {"type": "string"},
                "completed_actions": {"type": "array", "items": {"type": "string"}},
                "decisions": {"type": "array", "items": _DECISION_SCHEMA},
                "state_updates": {"type": "array", "items": _STATE_UPDATE_SCHEMA},
                "deliverables": {"type": "array", "items": _DELIVERABLE_SCHEMA},
                "validation": {"type": "array", "items": _VALIDATION_SCHEMA},
                "blockers": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": _RISK_SCHEMA},
                "artifacts": {"type": "array", "items": _ARTIFACT_SCHEMA},
                "open_items": {"type": "array", "items": {"type": "string"}},
                "next_options": {
                    "type": "array",
                    "maxItems": 4,
                    "items": _NEXT_OPTION_SCHEMA,
                },
                "recommended_next_option": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "maximum": 3,
                },
                "needs_user_input": {"type": "boolean"},
                "user_question": {"type": ["string", "null"]},
                "completion_assessment": {
                    "type": "object",
                    "properties": {
                        "goal_reached": {"type": "boolean"},
                        "progress_plateau": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["goal_reached", "progress_plateau", "reason"],
                    "additionalProperties": False,
                },
                "boundary_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "status",
                "summary",
                "progress_score",
                "task_profile",
                "profile_reason",
                "strategy_used",
                "strategy_reason",
                "completed_actions",
                "decisions",
                "state_updates",
                "deliverables",
                "validation",
                "blockers",
                "risks",
                "artifacts",
                "open_items",
                "next_options",
                "recommended_next_option",
                "needs_user_input",
                "user_question",
                "completion_assessment",
                "boundary_flags",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["report_markdown", "handoff"],
    "additionalProperties": False,
}
