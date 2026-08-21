from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .contracts import TASK_PROFILES, normalize_task_profile
from .controller import spawn_controller
from .service_boundaries import (
    _assert_single_live_campaign,
    _boundary_value,
)
from .service_campaigns import (
    add_memory_path,
    campaign_log,
    get_status,
    list_campaigns,
    pause_campaign,
    resume_campaign,
    stop_campaign,
)
from .service_doctor import doctor
from .service_models import (
    configure_model_routing,
    get_model_routing,
    list_model_catalog,
    list_models,
    preview_model_routing,
    reset_model_routing,
)
from .service_refresh import refresh_campaign_routing
from .service_support import _prepare_routing, _write_charter
from .store import Store
from .util import new_campaign_id, normalize_paths


def start_campaign(
    *,
    objective: str,
    workspace: str | None,
    operating_boundaries: Any | None = None,
    authorized_scope: Any | None = None,
    task_profile: str = "adaptive",
    name: str | None = None,
    success_criteria: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    model_policy: str | None = None,
    model_validation: str | None = None,
    role_models: dict[str, Any] | None = None,
    role_efforts: dict[str, Any] | None = None,
    allow_child_ultra: bool | None = None,
    allow_parent_ultra: bool | None = None,
    sandbox: str = "read-only",
    allow_network: bool = False,
    max_episodes: int = 20,
    max_elapsed_minutes: int = 480,
    continuation_threshold: float = 0.55,
    max_low_progress: int = 2,
    max_subagents: int = 2,
    memory_paths: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    objective = objective.strip()
    if not objective:
        raise ValueError("objective is required.")
    workspace_path = Path(workspace or os.getcwd()).expanduser().resolve()
    if not workspace_path.exists() or not workspace_path.is_dir():
        raise ValueError(f"workspace must be an existing directory: {workspace_path}")
    if sandbox not in {"read-only", "workspace-write"}:
        raise ValueError("sandbox must be 'read-only' or 'workspace-write'.")
    if operating_boundaries is not None and authorized_scope is not None:
        raise ValueError(
            "Provide operating_boundaries or the deprecated authorized_scope alias, not both."
        )
    raw_profile = str(task_profile or "adaptive")
    normalized_profile = normalize_task_profile(raw_profile, default="")
    if normalized_profile not in TASK_PROFILES:
        raise ValueError("task_profile must be one of: " + ", ".join(TASK_PROFILES))
    if not (1 <= int(max_episodes) <= 1000):
        raise ValueError("max_episodes must be between 1 and 1000.")
    if not (1 <= int(max_elapsed_minutes) <= 100_000):
        raise ValueError("max_elapsed_minutes must be positive.")
    if not (0.0 <= float(continuation_threshold) <= 1.0):
        raise ValueError("continuation_threshold must be between 0 and 1.")
    if not (1 <= int(max_low_progress) <= 20):
        raise ValueError("max_low_progress must be between 1 and 20.")
    if not (1 <= int(max_subagents) <= 16):
        raise ValueError("max_subagents must be between 1 and 16.")

    boundaries = _boundary_value(
        operating_boundaries if operating_boundaries is not None else authorized_scope,
        workspace=workspace_path,
        sandbox=sandbox,
        allow_network=bool(allow_network),
    )

    store = Store()
    _assert_single_live_campaign(store)
    campaign_name = name or objective[:72]
    campaign_id = new_campaign_id(campaign_name)
    requested, resolved, catalog, agents = _prepare_routing(
        workspace=workspace_path,
        model_policy=model_policy,
        model_validation=model_validation,
        parent_model=model,
        parent_effort=effort,
        role_models=role_models,
        role_efforts=role_efforts,
        allow_child_ultra=allow_child_ultra,
        allow_parent_ultra=allow_parent_ultra,
    )
    parent = resolved.get("parent") or {}
    campaign = store.create_campaign(
        {
            "id": campaign_id,
            "name": campaign_name,
            "objective": objective,
            "task_profile": normalized_profile,
            "workspace": str(workspace_path),
            "operating_boundaries": boundaries,
            "success_criteria": success_criteria or "",
            "model": parent.get("model"),
            "effort": parent.get("effort"),
            "model_policy": resolved.get("policy") or "inherit",
            "model_validation": resolved.get("validation") or "fallback",
            "allow_child_ultra": bool(resolved.get("allow_child_ultra")),
            "allow_parent_ultra": bool(resolved.get("allow_parent_ultra")),
            "requested_routing": requested,
            "resolved_routing": resolved,
            "model_catalog_snapshot": catalog,
            "routing_warnings": list(resolved.get("warnings") or []),
            "sandbox": sandbox,
            "allow_network": bool(allow_network),
            "max_episodes": int(max_episodes),
            "max_elapsed_minutes": int(max_elapsed_minutes),
            "continuation_threshold": float(continuation_threshold),
            "max_low_progress": int(max_low_progress),
            "max_subagents": int(max_subagents),
            "memory_paths": normalize_paths(memory_paths or []),
            "tags": tags or [],
        }
    )
    _write_charter(campaign, managed_agents=agents)
    try:
        pid = spawn_controller(campaign["id"])
    except Exception as exc:
        store.transition_campaign(campaign["id"], "error", last_error=str(exc))
        raise
    campaign = store.get_campaign(campaign["id"])
    return {
        "campaign": campaign,
        "controller_pid": pid,
        "managed_agents": agents,
        "routing_warnings": campaign.get("routing_warnings") or [],
    }
