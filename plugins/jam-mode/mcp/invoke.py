from __future__ import annotations

from typing import Any
from jam.harnesses.registry import harness_doctor, list_harnesses

from jam.service import (
    add_memory_path,
    campaign_log,
    configure_model_routing,
    get_model_routing,
    list_campaigns,
    list_model_catalog,
    pause_campaign,
    refresh_campaign_routing,
    resume_campaign,
    start_campaign,
    stop_campaign,
)

from .presentation import _campaign_message, _public_campaign, _status_payload
from .settings import CHILD_SESSION, ToolFailure
from .tool_catalog import READ_ONLY_CHILD_TOOLS


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
            harness=str(args.get("harness", "codex")),
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
            "harness": campaign.get("harness", "codex"),
            "status": campaign["status"],
            "controller_pid": result.get("controller_pid"),
            "message": (
                "JAM campaign created. Its controller will create one fresh harness session at a time and "
                "adapt the task profile and strategy per episode using the campaign's validated named-agent roster."
            ),
        }
        return payload, f"Started JAM campaign {campaign['id']} ({campaign['status']})."

    identifier = args.get("campaign_id")
    if name == "jam_list_harnesses":
        payload = list_harnesses()
        return payload, "Inspected configured coding harnesses; no model tasks were run."
    if name == "jam_status":
        payload = _status_payload(identifier)
        campaign = payload["campaign"]
        return payload, f"JAM campaign {campaign['id']} is {campaign['status']}."
    if name == "jam_list_campaigns":
        campaigns = [_public_campaign(c) for c in list_campaigns()]
        return {"campaigns": campaigns}, f"Found {len(campaigns)} JAM campaign(s)."
    if name == "jam_list_models":
        payload = list_model_catalog(include_hidden=bool(args.get("include_hidden", False)),
                                     harness=str(args.get("harness", "codex")))
        return payload, f"Harness catalogue contains {payload['count']} model(s); see availability metadata."
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
        result = resume_campaign(identifier, guidance=args.get("guidance"), max_subagents=args.get("max_subagents"))
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
        payload = harness_doctor(str(args.get("harness", "codex")))
        lines = [
            f"{'OK' if item['ok'] else 'FAIL'} {item['name']}: {item['detail']}"
            for item in payload["checks"]
        ]
        return payload, "\n".join(lines)
    raise ToolFailure(f"Unknown tool: {name}")
