from __future__ import annotations

from typing import Any

from jam.contracts import TASK_PROFILES
from jam.resumption import RESUME_OPTIONS

from .tool_schema import (
    CAMPAIGN_ID_ARG,
    MODEL_ROUTING_PROPERTIES,
    _schema,
    _tool,
)


TOOLS: list[dict[str, Any]] = [
    _tool(
        "jam_start_campaign",
        "Start JAM campaign",
        (
            "Create a bounded, persistent JAM campaign for research, engineering, review, documentation, "
            "planning, data, operations, content, or mixed work. A conservative local-workspace boundary is "
            "inferred when none is supplied; explicit boundaries are required for network access. One top-level "
            "episode runs at a time and each episode adapts its task profile and agent strategy."
        ),
        _schema(
            {
                "objective": {"type": "string", "minLength": 1},
                "workspace": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Absolute existing project/workspace directory as seen by this Codex host.",
                },
                "operating_boundaries": {
                    "oneOf": [{"type": "object"}, {"type": "string", "minLength": 1}],
                    "description": (
                        "Optional immutable autonomous boundary covering resources, allowed actions, exclusions, "
                        "and approval requirements. Omit for conservative local-workspace defaults. Required when "
                        "allow_network is true."
                    ),
                },
                "authorized_scope": {
                    "oneOf": [{"type": "object"}, {"type": "string", "minLength": 1}],
                    "description": "Deprecated compatibility alias for operating_boundaries; do not provide both.",
                },
                "task_profile": {
                    "type": "string",
                    "enum": list(TASK_PROFILES),
                    "default": "adaptive",
                    "description": "Campaign profile preference; adaptive lets every episode select the best profile.",
                },
                "name": {"type": "string"},
                "success_criteria": {"type": "string"},
                **MODEL_ROUTING_PROPERTIES,
                "sandbox": {
                    "type": "string",
                    "enum": ["read-only", "workspace-write"],
                    "default": "read-only",
                },
                "allow_network": {"type": "boolean", "default": False},
                "max_episodes": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 20},
                "max_elapsed_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100000,
                    "default": 480,
                },
                "continuation_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.55,
                },
                "max_low_progress": {"type": "integer", "minimum": 1, "maximum": 20, "default": 2},
                "max_subagents": {"type": "integer", "minimum": 2, "maximum": 16, "default": 2},
                "memory_paths": {"type": "array", "items": {"type": "string"}, "default": []},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            ["objective", "workspace"],
        ),
        read_only=False,
        output_schema=_schema(
            {
                "campaign_id": {"type": "string"},
                "status": {"type": "string"},
                "controller_pid": {"type": ["integer", "null"]},
                "message": {"type": "string"},
            },
            ["campaign_id", "status", "controller_pid", "message"],
        ),
    ),
    _tool(
        "jam_status",
        "Get JAM status",
        "Read the current status, latest handoff summary, thread id, budgets, and artifact directory for a JAM campaign.",
        _schema(CAMPAIGN_ID_ARG),
        read_only=True,
    ),
    _tool(
        "jam_list_campaigns",
        "List JAM campaigns",
        "List recent JAM campaigns and their state. This does not change campaign execution.",
        _schema(),
        read_only=True,
    ),
    _tool(
        "jam_list_models",
        "List Codex models",
        "Read the models and reasoning efforts advertised by this installed Codex account through App Server model/list.",
        _schema(
            {
                "include_hidden": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include hidden catalog entries.",
                }
            }
        ),
        read_only=True,
    ),
    _tool(
        "jam_model_routing",
        "Inspect JAM model routing",
        (
            "Inspect the saved default role roster for future campaigns, or provide a campaign id to read "
            "that campaign's immutable requested/resolved roster and validation warnings."
        ),
        _schema(CAMPAIGN_ID_ARG),
        read_only=True,
    ),
    _tool(
        "jam_configure_model_routing",
        "Configure JAM model routing",
        (
            "Persist JAM's default model-routing policy for future campaigns, or provide a campaign id to "
            "replace a paused campaign's frozen roster. Regenerates only JAM-managed custom-agent files; "
            "a live campaign must be paused and its current episode must have ended first."
        ),
        _schema(
            {
                **CAMPAIGN_ID_ARG,
                **MODEL_ROUTING_PROPERTIES,
                "validate": {
                    "type": "boolean",
                    "default": True,
                    "description": "Validate against the installed Codex model catalog before saving agents.",
                },
                "reset": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Reset global defaults when no campaign is supplied, or reset a paused campaign to "
                        "the current global defaults before applying any supplied overrides."
                    ),
                },
            }
        ),
        read_only=False,
    ),
    _tool(
        "jam_refresh_campaign_routing",
        "Refresh JAM campaign routing",
        (
            "Revalidate and rematerialize a paused campaign's existing requested roster against the current "
            "Codex model catalog without changing its configured policy or overrides."
        ),
        _schema(
            {
                **CAMPAIGN_ID_ARG,
                "validate": {
                    "type": "boolean",
                    "default": True,
                    "description": "Read model/list and re-resolve the roster before regenerating agents.",
                },
            },
            ["campaign_id"],
        ),
        read_only=False,
    ),
    _tool(
        "jam_pause_after_current",
        "Pause JAM after current episode",
        (
            "Disable continuation without interrupting the active Codex session. The current episode ends "
            "naturally, its handoff is saved, and no replacement session starts."
        ),
        _schema(CAMPAIGN_ID_ARG),
        read_only=False,
    ),
    _tool(
        "jam_resume_campaign",
        "Resume JAM campaign",
        "Resume a paused/finished campaign by running a fresh context review and planning pass before any new session.",
        _schema(
            {
                **CAMPAIGN_ID_ARG,
                **RESUME_OPTIONS,
            }
        ),
        read_only=False,
    ),
    _tool(
        "jam_stop_campaign",
        "Stop JAM campaign",
        (
            "Stop autonomous continuation until the campaign is explicitly resumed. An active episode is "
            "allowed to end naturally first; no next episode starts."
        ),
        _schema(CAMPAIGN_ID_ARG),
        read_only=False,
    ),
    _tool(
        "jam_add_memory_path",
        "Add JAM memory source",
        "Add an existing local file or directory to the campaign's subject-memory inventory for future planning passes.",
        _schema(
            {
                **CAMPAIGN_ID_ARG,
                "path": {"type": "string", "minLength": 1},
            },
            ["path"],
        ),
        read_only=False,
    ),
    _tool(
        "jam_campaign_log",
        "Read JAM controller log",
        "Return the tail of a campaign controller log for diagnostics.",
        _schema(
            {
                **CAMPAIGN_ID_ARG,
                "tail": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 120},
            }
        ),
        read_only=True,
    ),
    _tool(
        "jam_doctor",
        "Check JAM prerequisites",
        "Check Python, Codex CLI, App Server, state directories, and plugin installation prerequisites.",
        _schema(),
        read_only=True,
    ),
]

READ_ONLY_CHILD_TOOLS = {
    "jam_status",
    "jam_list_campaigns",
    "jam_list_models",
    "jam_model_routing",
    "jam_campaign_log",
    "jam_doctor",
}
