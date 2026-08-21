from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import campaign_dir
from .routing import (
    ensure_managed_agents,
    load_routing_config,
    requested_routing_from_config,
    resolve_requested_with_installed_catalog,
    resolve_routing,
)
from .util import json_dumps


def _resolve_requested_routing(
    requested: dict[str, Any], *, validate: bool
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if validate:
        return resolve_requested_with_installed_catalog(requested)
    skipped = json.loads(json.dumps(requested))
    configured_validation = str(skipped.get("validation") or "fallback")
    skipped["validation"] = "off"
    resolved = resolve_routing(skipped, catalog_entries=[])
    resolved["validation"] = configured_validation
    resolved["catalog_status"] = "skipped"
    resolved["warnings"] = list(resolved.get("warnings") or []) + [
        "Installed model-catalog validation was skipped; requested model ids and efforts "
        "were materialized without compatibility checks."
    ]
    return resolved, []


def _prepare_routing(
    *,
    workspace: Path,
    model_policy: str | None,
    model_validation: str | None,
    parent_model: str | None,
    parent_effort: str | None,
    role_models: dict[str, Any] | None,
    role_efforts: dict[str, Any] | None,
    allow_child_ultra: bool | None,
    allow_parent_ultra: bool | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    config = load_routing_config(create=True)
    requested = requested_routing_from_config(
        config,
        policy=model_policy,
        validation=model_validation,
        parent_model=parent_model,
        parent_effort=parent_effort,
        role_models=role_models,
        role_efforts=role_efforts,
        allow_child_ultra=allow_child_ultra,
        allow_parent_ultra=allow_parent_ultra,
    )
    resolved, catalog = resolve_requested_with_installed_catalog(requested)
    agents = ensure_managed_agents(resolved, workspace=workspace)
    return requested, resolved, catalog, agents


def _charter_payload(
    campaign: dict[str, Any], *, managed_agents: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "campaign_id": campaign["id"],
        "name": campaign["name"],
        "objective": campaign["objective"],
        "task_profile": campaign["task_profile"],
        "workspace": campaign["workspace"],
        "operating_boundaries": campaign["operating_boundaries"],
        "success_criteria": campaign["success_criteria"],
        "created_at": campaign["created_at"],
        "policy": {
            "sandbox": campaign["sandbox"],
            "allow_network": campaign["allow_network"],
            "max_episodes": campaign["max_episodes"],
            "max_elapsed_minutes": campaign["max_elapsed_minutes"],
            "continuation_threshold": campaign["continuation_threshold"],
            "max_subagents": campaign["max_subagents"],
            "autonomous_boundary_expansion": False,
            "parallel_writers": False,
        },
        "model_routing": {
            "requested": campaign.get("requested_routing") or {},
            "resolved": campaign.get("resolved_routing") or {},
            "catalog_snapshot": campaign.get("model_catalog_snapshot") or [],
            "warnings": campaign.get("routing_warnings") or [],
            "managed_agents": managed_agents or {},
        },
    }


def _write_charter(
    campaign: dict[str, Any], *, managed_agents: dict[str, str] | None = None
) -> None:
    (campaign_dir(campaign["id"]) / "charter.json").write_text(
        json_dumps(_charter_payload(campaign, managed_agents=managed_agents), pretty=True),
        encoding="utf-8",
    )
