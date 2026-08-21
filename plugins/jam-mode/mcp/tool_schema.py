from __future__ import annotations

from typing import Any

from jam.contracts import TASK_PROFILES
from jam.routing import (
    CHILD_ROLES,
    EFFORT_ORDER,
    MODEL_POLICIES,
    MODEL_VALIDATION_MODES,
)


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


def _annotations(*, read_only: bool, destructive: bool = False) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "openWorldHint": False,
        "destructiveHint": destructive,
        "idempotentHint": read_only,
    }


def _tool(
    name: str,
    title: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    read_only: bool,
    destructive: bool = False,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": input_schema,
        "annotations": _annotations(read_only=read_only, destructive=destructive),
    }
    if output_schema:
        value["outputSchema"] = output_schema
    return value


CAMPAIGN_ID_ARG = {
    "campaign_id": {
        "type": "string",
        "description": "Campaign id or exact campaign name. Omit to use the active/latest campaign.",
    }
}

ROLE_MODEL_PROPERTIES = {
    role: {
        "type": "string",
        "minLength": 1,
        "description": f"Model id override for the {role} role; use 'inherit' to clear it.",
    }
    for role in CHILD_ROLES
}
ROLE_EFFORT_PROPERTIES = {
    role: {
        "type": "string",
        "enum": [*EFFORT_ORDER, "inherit"],
        "description": f"Reasoning effort override for the {role} role.",
    }
    for role in CHILD_ROLES
}
MODEL_ROUTING_PROPERTIES = {
    "model_policy": {
        "type": "string",
        "enum": list(MODEL_POLICIES),
        "description": "Role-routing preset. Omit to use the saved JAM default.",
    },
    "model_validation": {
        "type": "string",
        "enum": list(MODEL_VALIDATION_MODES),
        "description": "Validate requested model/effort pairs against Codex model/list.",
    },
    "model": {
        "type": "string",
        "description": "Parent/synthesizer model override; use 'inherit' to clear it.",
    },
    "effort": {
        "type": "string",
        "enum": [*EFFORT_ORDER, "inherit"],
        "description": "Parent/synthesizer reasoning-effort override.",
    },
    "role_models": {
        "type": "object",
        "properties": ROLE_MODEL_PROPERTIES,
        "additionalProperties": False,
        "description": "Per-child-role model overrides for JAM's named custom agents.",
    },
    "role_efforts": {
        "type": "object",
        "properties": ROLE_EFFORT_PROPERTIES,
        "additionalProperties": False,
        "description": "Per-child-role reasoning-effort overrides.",
    },
    "allow_child_ultra": {
        "type": "boolean",
        "description": "Permit child roles to use Ultra when the selected model advertises it.",
    },
    "allow_parent_ultra": {
        "type": "boolean",
        "description": "Permit the parent/synthesizer to use Ultra when advertised.",
    },
}
