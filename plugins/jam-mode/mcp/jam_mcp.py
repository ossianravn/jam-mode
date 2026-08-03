#!/usr/bin/env python3
"""Dependency-free stdio MCP server for the JAM Mode Codex plugin."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
# Put the plugin package ahead of the launcher directory even when callers
# already included it later in PYTHONPATH. This prevents scripts/jam.py from
# shadowing the top-level ``jam`` package.
try:
    sys.path.remove(str(PLUGIN_ROOT))
except ValueError:
    pass
sys.path.insert(0, str(PLUGIN_ROOT))

from jam import __version__  # noqa: E402
from jam.contracts import TASK_PROFILES  # noqa: E402
from jam.routing import (  # noqa: E402
    ALL_ROUTING_ROLES,
    EFFORT_ORDER,
    MODEL_POLICIES,
    MODEL_VALIDATION_MODES,
)
from jam.service import (  # noqa: E402
    add_memory_path,
    campaign_log,
    configure_model_routing,
    doctor,
    get_model_routing,
    get_status,
    list_campaigns,
    list_model_catalog,
    pause_campaign,
    refresh_campaign_routing,
    resume_campaign,
    start_campaign,
    stop_campaign,
)
from jam.store import CampaignNotFound, StoreError  # noqa: E402

DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "jam-mode"
CHILD_SESSION = os.environ.get("JAM_CHILD_SESSION") == "1"


class ToolFailure(RuntimeError):
    pass


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
    for role in ALL_ROUTING_ROLES
}
ROLE_EFFORT_PROPERTIES = {
    role: {
        "type": "string",
        "enum": [*EFFORT_ORDER, "inherit"],
        "description": f"Reasoning effort override for the {role} role.",
    }
    for role in ALL_ROUTING_ROLES
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
        "description": "Per-role model overrides for JAM's named custom agents.",
    },
    "role_efforts": {
        "type": "object",
        "properties": ROLE_EFFORT_PROPERTIES,
        "additionalProperties": False,
        "description": "Per-role reasoning-effort overrides.",
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
                "max_subagents": {"type": "integer", "minimum": 1, "maximum": 16, "default": 2},
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
                "guidance": {
                    "type": "string",
                    "description": "Optional new user guidance appended to campaign state before replanning.",
                },
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


def _public_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "name",
        "objective",
        "task_profile",
        "workspace",
        "operating_boundaries",
        "success_criteria",
        "status",
        "enabled",
        "stop_after_current",
        "termination_requested",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "active_episode_id",
        "last_thread_id",
        "sandbox",
        "allow_network",
        "max_episodes",
        "max_elapsed_minutes",
        "continuation_threshold",
        "max_subagents",
        "model",
        "effort",
        "model_policy",
        "model_validation",
        "allow_child_ultra",
        "allow_parent_ultra",
        "requested_routing",
        "resolved_routing",
        "routing_warnings",
        "episode_count",
        "last_error",
    )
    return {key: campaign.get(key) for key in fields}


def _public_episode(episode: dict[str, Any] | None) -> dict[str, Any] | None:
    if not episode:
        return None
    handoff = episode.get("handoff") or {}
    return {
        "id": episode.get("id"),
        "number": episode.get("number"),
        "objective": episode.get("objective"),
        "task_profile": (
            episode.get("task_profile_used")
            or episode.get("task_profile_hint")
            or handoff.get("task_profile")
        ),
        "strategy": episode.get("strategy_used") or episode.get("strategy_hint"),
        "status": episode.get("status"),
        "turn_status": episode.get("turn_status"),
        "thread_id": episode.get("thread_id"),
        "started_at": episode.get("started_at"),
        "ended_at": episode.get("ended_at"),
        "report_path": episode.get("final_path"),
        "handoff_path": episode.get("handoff_path"),
        "summary": handoff.get("summary"),
        "progress_score": handoff.get("progress_score"),
        "needs_user_input": handoff.get("needs_user_input"),
        "user_question": handoff.get("user_question"),
        "next_options": handoff.get("next_options") or [],
        "routing_snapshot": episode.get("routing_snapshot") or {},
        "agent_activity": episode.get("agent_activity") or [],
        "model_events": episode.get("model_events") or [],
        "token_usage": episode.get("token_usage"),
        "error": episode.get("error"),
    }


def _status_payload(identifier: str | None) -> dict[str, Any]:
    result = get_status(identifier)
    return {
        "campaign": _public_campaign(result["campaign"]),
        "controller_alive": result["controller_alive"],
        "last_episode": _public_episode(result.get("last_episode")),
        "episodes": [_public_episode(item) for item in result.get("episodes", [])[:20]],
        "campaign_directory": result["campaign_directory"],
    }


def _campaign_message(campaign: dict[str, Any], message: str = "") -> dict[str, Any]:
    return {"campaign": _public_campaign(campaign), "message": message}


def _invoke(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if CHILD_SESSION and name not in READ_ONLY_CHILD_TOOLS:
        raise ToolFailure(
            "Mutating JAM controls are disabled inside a JAM child session to prevent recursive campaigns. "
            "Use the parent Desktop/CLI session or the `jam` companion command."
        )

    if name == "jam_start_campaign":
        result = start_campaign(
            objective=str(args["objective"]),
            workspace=str(args["workspace"]),
            operating_boundaries=args.get("operating_boundaries"),
            authorized_scope=args.get("authorized_scope"),
            task_profile=str(args.get("task_profile") or "adaptive"),
            name=args.get("name"),
            success_criteria=args.get("success_criteria"),
            model=args.get("model"),
            effort=args.get("effort"),
            model_policy=args.get("model_policy"),
            model_validation=args.get("model_validation"),
            role_models=args.get("role_models"),
            role_efforts=args.get("role_efforts"),
            allow_child_ultra=args.get("allow_child_ultra"),
            allow_parent_ultra=args.get("allow_parent_ultra"),
            sandbox=str(args.get("sandbox") or "read-only"),
            allow_network=bool(args.get("allow_network", False)),
            max_episodes=int(args.get("max_episodes", 20)),
            max_elapsed_minutes=int(args.get("max_elapsed_minutes", 480)),
            continuation_threshold=float(args.get("continuation_threshold", 0.55)),
            max_low_progress=int(args.get("max_low_progress", 2)),
            max_subagents=int(args.get("max_subagents", 2)),
            memory_paths=[str(item) for item in args.get("memory_paths", [])],
            tags=[str(item) for item in args.get("tags", [])],
        )
        campaign = result["campaign"]
        payload = {
            "campaign_id": campaign["id"],
            "status": campaign["status"],
            "controller_pid": result.get("controller_pid"),
            "message": (
                "JAM campaign created. Its controller will create one fresh Codex session at a time and "
                "adapt the task profile and strategy per episode using the campaign's validated named-agent roster."
            ),
        }
        return payload, f"Started JAM campaign {campaign['id']} ({campaign['status']})."

    identifier = args.get("campaign_id")
    if name == "jam_status":
        payload = _status_payload(identifier)
        campaign = payload["campaign"]
        return payload, f"JAM campaign {campaign['id']} is {campaign['status']}."
    if name == "jam_list_campaigns":
        campaigns = [_public_campaign(c) for c in list_campaigns()]
        return {"campaigns": campaigns}, f"Found {len(campaigns)} JAM campaign(s)."
    if name == "jam_list_models":
        payload = list_model_catalog(include_hidden=bool(args.get("include_hidden", False)))
        return payload, f"Codex advertised {payload['count']} model(s)."
    if name == "jam_model_routing":
        payload = get_model_routing(args.get("campaign_id"))
        resolved = payload.get("resolved") or {}
        return payload, (
            f"JAM routing scope={payload.get('scope', 'defaults')}; "
            f"policy={resolved.get('policy') or payload.get('policy') or 'inherit'}; "
            f"validation={resolved.get('validation') or payload.get('validation') or 'fallback'}."
        )
    if name == "jam_configure_model_routing":
        payload = configure_model_routing(
            args.get("campaign_id"),
            model_policy=args.get("model_policy"),
            model_validation=args.get("model_validation"),
            model=args.get("model"),
            effort=args.get("effort"),
            role_models=args.get("role_models"),
            role_efforts=args.get("role_efforts"),
            allow_child_ultra=args.get("allow_child_ultra"),
            allow_parent_ultra=args.get("allow_parent_ultra"),
            validate=bool(args.get("validate", True)),
            reset=bool(args.get("reset", False)),
        )
        warnings = (payload.get("resolved") or {}).get("warnings") or []
        scope = payload.get("scope") or "defaults"
        text = (
            "Saved JAM model-routing defaults and regenerated managed custom agents."
            if scope == "defaults"
            else f"Updated model routing for paused campaign {payload.get('campaign_id')} and regenerated managed custom agents."
        )
        if warnings:
            text += " " + " ".join(str(item) for item in warnings)
        return payload, text
    if name == "jam_refresh_campaign_routing":
        payload = refresh_campaign_routing(
            args.get("campaign_id"), validate=bool(args.get("validate", True))
        )
        warnings = payload.get("routing_warnings") or []
        text = f"Refreshed model routing for paused campaign {payload['campaign']['id']}."
        if warnings:
            text += " " + " ".join(str(item) for item in warnings)
        return payload, text
    if name == "jam_pause_after_current":
        result = pause_campaign(identifier)
        payload = _campaign_message(result["campaign"], result["message"])
        return payload, result["message"]
    if name == "jam_resume_campaign":
        result = resume_campaign(identifier, guidance=args.get("guidance"))
        payload = {
            **_campaign_message(result["campaign"], "JAM resumed with a fresh planning pass."),
            "controller_pid": result.get("controller_pid"),
        }
        return payload, payload["message"]
    if name == "jam_stop_campaign":
        result = stop_campaign(identifier)
        payload = _campaign_message(result["campaign"], result["message"])
        return payload, result["message"]
    if name == "jam_add_memory_path":
        result = add_memory_path(identifier, str(args["path"]))
        payload = {
            "campaign": _public_campaign(result["campaign"]),
            "memory_path": result["memory_path"],
        }
        return payload, f"Added memory source: {result['memory_path']}"
    if name == "jam_campaign_log":
        payload = campaign_log(identifier, tail=int(args.get("tail", 120)))
        return payload, payload["text"] or f"No controller log at {payload['path']}"
    if name == "jam_doctor":
        payload = doctor()
        lines = [
            f"{'OK' if item['ok'] else 'FAIL'} {item['name']}: {item['detail']}"
            for item in payload["checks"]
        ]
        return payload, "\n".join(lines)
    raise ToolFailure(f"Unknown tool: {name}")


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _result(request_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str, data: Any | None = None) -> None:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    _send({"jsonrpc": "2.0", "id": request_id, "error": payload})


def _tools_for_host() -> list[dict[str, Any]]:
    if not CHILD_SESSION:
        return TOOLS
    return [tool for tool in TOOLS if tool["name"] in READ_ONLY_CHILD_TOOLS]


def _handle(message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        requested = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
        instructions = (
            "JAM Mode manages bounded, task-general campaigns across fresh Codex sessions. Require an explicit "
            "objective and workspace. Use conservative local boundaries by default, and require explicit operating "
            "boundaries for networked, security-sensitive, deployment, or other elevated work. Pause is graceful: "
            "the active episode finishes naturally, then no replacement starts. Model routing uses validated "
            "JAM-prefixed custom agents and can be inspected or configured with the routing tools."
        )
        if CHILD_SESSION:
            instructions += " This is a JAM child session; mutating campaign tools are intentionally hidden."
        _result(
            request_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": instructions,
            },
        )
        return
    if method in {"notifications/initialized", "initialized", "notifications/cancelled"}:
        return
    if method == "ping":
        _result(request_id, {})
        return
    if method == "tools/list":
        _result(request_id, {"tools": _tools_for_host()})
        return
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            _result(
                request_id,
                {
                    "isError": True,
                    "content": [{"type": "text", "text": "Tool arguments must be an object."}],
                },
            )
            return
        try:
            payload, text = _invoke(name, arguments)
            _result(
                request_id,
                {
                    "structuredContent": payload,
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            )
        except (ValueError, StoreError, CampaignNotFound, ToolFailure, OSError) as exc:
            _result(
                request_id,
                {
                    "structuredContent": {"error": str(exc), "tool": name},
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        except Exception as exc:  # defensive server boundary
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            _result(
                request_id,
                {
                    "structuredContent": {"error": str(exc), "tool": name},
                    "content": [{"type": "text", "text": f"Unexpected JAM error: {exc}"}],
                    "isError": True,
                },
            )
        return
    if request_id is not None:
        _error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            _handle(message)
        except json.JSONDecodeError as exc:
            _error(None, -32700, "Parse error", str(exc))
        except Exception as exc:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            request_id = message.get("id") if isinstance(locals().get("message"), dict) else None
            _error(request_id, -32603, "Internal error", str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
