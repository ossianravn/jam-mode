from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .contracts import TASK_PROFILES, normalize_task_profile
from .controller import spawn_controller
from .paths import campaign_dir, codex_home_path, jam_home_path, plugin_root
from .routing import (
    CHILD_ROLES,
    EFFORT_ORDER,
    MODEL_POLICIES,
    MODEL_VALIDATION_MODES,
    build_requested_routing,
    default_routing_config,
    ensure_managed_agents,
    fetch_installed_model_catalog,
    inspect_managed_agents,
    load_routing_config,
    merge_routing_config,
    model_catalog_snapshot,
    requested_routing_from_config,
    resolve_requested_with_installed_catalog,
    resolve_routing,
    routing_config_from_requested,
    routing_config_path,
    save_routing_config,
)
from .store import Store, StoreError
from .util import (
    json_dumps,
    new_campaign_id,
    normalize_paths,
    process_is_alive,
    utc_now,
)


LIVE_STATUSES = {
    "queued",
    "planning",
    "running",
    "finalizing",
    "stopping_after_current",
}


def _default_boundaries(
    workspace: Path, *, sandbox: str, allow_network: bool
) -> dict[str, Any]:
    if allow_network:
        raise ValueError(
            "operating_boundaries are required when network access is enabled; "
            "name the permitted external resources and excluded targets."
        )
    allowed_actions = [
        "Read and inspect files inside the workspace.",
        "Run local commands and validation permitted by the Codex sandbox.",
    ]
    if sandbox == "workspace-write":
        allowed_actions.append(
            "Create or modify files inside the workspace when required by the objective."
        )
    return {
        "resources": [str(workspace)],
        "allowed_actions": allowed_actions,
        "excluded_actions": [
            "Access unrelated local resources or external systems.",
            "Publish, deploy, or communicate externally.",
            "Use credentials or secrets not explicitly supplied for this campaign.",
            "Perform destructive or irreversible actions outside ordinary reversible workspace edits.",
            "Expand these operating boundaries autonomously.",
        ],
        "approval_required_for": [
            "Network access.",
            "External publication or deployment.",
            "Destructive or irreversible actions.",
            "Credentials, secrets, or new accounts.",
            "Any expansion of resources or allowed actions.",
        ],
        "source": "conservative_default",
    }


def _boundary_value(
    value: Any,
    *,
    workspace: Path,
    sandbox: str,
    allow_network: bool,
) -> dict[str, Any]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return _default_boundaries(
            workspace, sandbox=sandbox, allow_network=allow_network
        )
    if isinstance(value, dict):
        boundaries = dict(value)
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            decoded = json.loads(stripped)
            boundaries = decoded if isinstance(decoded, dict) else {"description": stripped}
        except ValueError:
            boundaries = {"description": stripped}
    else:
        raise ValueError("operating_boundaries must be a JSON object or non-empty text.")
    if not any(boundaries.values()):
        raise ValueError(
            "operating_boundaries must contain resources, allowed actions, exclusions, or a description."
        )
    return boundaries


# Compatibility for callers that imported the 0.1 helper.
def _scope_value(value: Any) -> dict[str, Any]:
    if value is None:
        raise ValueError("authorized_scope must not be empty.")
    return _boundary_value(
        value,
        workspace=Path.cwd().resolve(),
        sandbox="read-only",
        allow_network=False,
    )


def _assert_single_live_campaign(store: Store, *, exclude_id: str | None = None) -> None:
    for campaign in store.list_campaigns(limit=200):
        if exclude_id and campaign["id"] == exclude_id:
            continue
        if campaign.get("enabled") and campaign.get("status") in LIVE_STATUSES:
            raise StoreError(
                "JAM 0.3 permits one active campaign at a time. "
                f"Pause or stop {campaign['id']} ({campaign['name']}) first."
            )


def _assert_agent_update_safe(
    store: Store, *, campaign: dict[str, Any] | None = None
) -> None:
    """Prevent static JAM agent files from changing under any live episode."""

    target_id: str | None = None
    if campaign is not None:
        target_id = str(campaign["id"])
        if campaign.get("active_episode_id") or (
            campaign.get("enabled") and campaign.get("status") in LIVE_STATUSES
        ):
            raise StoreError(
                "Pause the campaign and let its current episode finish before changing "
                "its model-routing roster."
            )

    for item in store.list_campaigns(limit=200):
        if target_id and item.get("id") == target_id:
            continue
        if item.get("active_episode_id") or (
            item.get("enabled") and item.get("status") in LIVE_STATUSES
        ):
            raise StoreError(
                "Pause the active JAM campaign before changing model-routing settings; "
                "JAM custom-agent names are shared by the single live campaign."
            )


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
        store.update_campaign(
            campaign["id"], status="error", enabled=False, last_error=str(exc)
        )
        raise
    campaign = store.get_campaign(campaign["id"])
    return {
        "campaign": campaign,
        "controller_pid": pid,
        "managed_agents": agents,
        "routing_warnings": campaign.get("routing_warnings") or [],
    }


def _persist_campaign_routing(
    store: Store,
    campaign: dict[str, Any],
    *,
    requested: dict[str, Any],
    resolved: dict[str, Any],
    catalog: list[dict[str, Any]],
    managed_agents: dict[str, str],
) -> dict[str, Any]:
    parent = resolved.get("parent") or {}
    updated = store.update_campaign(
        campaign["id"],
        model=parent.get("model"),
        effort=parent.get("effort"),
        model_policy=resolved.get("policy") or "inherit",
        model_validation=resolved.get("validation") or "fallback",
        allow_child_ultra=bool(resolved.get("allow_child_ultra")),
        allow_parent_ultra=bool(resolved.get("allow_parent_ultra")),
        requested_routing=requested,
        resolved_routing=resolved,
        model_catalog_snapshot=catalog,
        routing_warnings=list(resolved.get("warnings") or []),
    )
    _write_charter(updated, managed_agents=managed_agents)
    return updated


def refresh_campaign_routing(
    identifier: str | None = None, *, validate: bool = True
) -> dict[str, Any]:
    """Revalidate and rematerialize a paused campaign's persisted routing roster."""

    store = Store()
    campaign = store.get_campaign(identifier or "active")
    _assert_agent_update_safe(store, campaign=campaign)
    requested = campaign.get("requested_routing") or {}
    if not requested:
        requested = build_requested_routing(
            policy=campaign.get("model_policy") or "inherit",
            validation=campaign.get("model_validation") or "fallback",
            parent_model=campaign.get("model"),
            parent_effort=campaign.get("effort"),
            allow_child_ultra=bool(campaign.get("allow_child_ultra")),
            allow_parent_ultra=bool(campaign.get("allow_parent_ultra")),
        )
    resolved, catalog = _resolve_requested_routing(requested, validate=validate)
    agents = ensure_managed_agents(resolved, workspace=campaign["workspace"])
    campaign = _persist_campaign_routing(
        store,
        campaign,
        requested=requested,
        resolved=resolved,
        catalog=catalog,
        managed_agents=agents,
    )
    return {
        "scope": "campaign",
        "campaign": campaign,
        "requested": requested,
        "resolved": resolved,
        "catalog": catalog,
        "managed_agents": agents,
        "routing_warnings": campaign.get("routing_warnings") or [],
        "warnings": campaign.get("routing_warnings") or [],
    }


def get_status(identifier: str | None = None) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    last = store.last_episode(campaign["id"])
    episodes = store.list_episodes(campaign["id"], limit=20)
    return {
        "campaign": campaign,
        "controller_alive": process_is_alive(campaign.get("controller_pid")),
        "last_episode": last,
        "episodes": episodes,
        "campaign_directory": str(campaign_dir(campaign["id"])),
        "managed_agents": inspect_managed_agents(),
    }


def list_campaigns() -> list[dict[str, Any]]:
    return Store().list_campaigns(limit=200)


def pause_campaign(identifier: str | None = None) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    if campaign.get("active_episode_id"):
        status = "stopping_after_current"
        message = "JAM will stop after the current episode finishes naturally."
    else:
        status = "paused"
        message = "JAM is paused. No new episode will start."
    updated = store.update_campaign(
        campaign["id"],
        enabled=False,
        stop_after_current=bool(campaign.get("active_episode_id")),
        status=status,
    )
    return {"campaign": updated, "message": message}


def resume_campaign(
    identifier: str | None = None, *, guidance: str | None = None
) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    _assert_single_live_campaign(store, exclude_id=campaign["id"])
    if guidance:
        store.append_guidance(campaign["id"], guidance)
    refresh = refresh_campaign_routing(campaign["id"])
    updated = store.update_campaign(
        campaign["id"],
        enabled=True,
        stop_after_current=False,
        termination_requested=False,
        status="queued",
        completed_at=None,
        last_error=None,
    )
    pid = spawn_controller(campaign["id"])
    return {
        "campaign": store.get_campaign(campaign["id"]),
        "controller_pid": pid,
        "managed_agents": refresh["managed_agents"],
        "routing_warnings": refresh["routing_warnings"],
    }


def stop_campaign(identifier: str | None = None) -> dict[str, Any]:
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    active = bool(campaign.get("active_episode_id"))
    updated = store.update_campaign(
        campaign["id"],
        enabled=False,
        stop_after_current=active,
        termination_requested=True,
        status="stopping_after_current" if active else "stopped",
        completed_at=None if active else utc_now(),
    )
    return {
        "campaign": updated,
        "message": (
            "The current episode will finish naturally, then the campaign will stop."
            if active
            else "The campaign is stopped."
        ),
    }


def add_memory_path(identifier: str | None, path: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"Memory path does not exist: {resolved}")
    store = Store()
    campaign = store.get_campaign(identifier or "active")
    updated = store.add_memory_path(campaign["id"], str(resolved))
    return {"campaign": updated, "memory_path": str(resolved)}


def campaign_log(identifier: str | None = None, *, tail: int = 120) -> dict[str, Any]:
    campaign = Store().get_campaign(identifier or "active")
    path = campaign_dir(campaign["id"]) / "controller.log"
    if not path.exists():
        text = ""
    else:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        text = "\n".join(lines[-max(1, tail) :])
    return {"campaign_id": campaign["id"], "path": str(path), "text": text}


def list_models(*, include_hidden: bool = False) -> dict[str, Any]:
    raw = fetch_installed_model_catalog(include_hidden=include_hidden)
    snapshot = model_catalog_snapshot(raw)
    if not include_hidden:
        snapshot = [item for item in snapshot if not item.get("hidden")]
    return {
        "models": snapshot,
        "count": len(snapshot),
        "config_path": str(routing_config_path()),
    }


def list_model_catalog(*, include_hidden: bool = False) -> dict[str, Any]:
    """Compatibility/public alias used by the CLI and MCP surface."""

    return list_models(include_hidden=include_hidden)


def preview_model_routing(
    *,
    model_policy: str | None = None,
    model_validation: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    role_models: dict[str, Any] | None = None,
    role_efforts: dict[str, Any] | None = None,
    allow_child_ultra: bool | None = None,
    allow_parent_ultra: bool | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    config = load_routing_config(create=False)
    requested = requested_routing_from_config(
        config,
        policy=model_policy,
        validation=model_validation,
        parent_model=model,
        parent_effort=effort,
        role_models=role_models,
        role_efforts=role_efforts,
        allow_child_ultra=allow_child_ultra,
        allow_parent_ultra=allow_parent_ultra,
    )
    resolved, catalog = _resolve_requested_routing(requested, validate=validate)
    return {
        "scope": "defaults",
        "config_path": str(routing_config_path()),
        "config": config,
        "requested": requested,
        "resolved": resolved,
        "catalog": catalog,
        "warnings": list(resolved.get("warnings") or []),
        "managed_agents": inspect_managed_agents(),
    }


def get_model_routing(
    identifier: str | None = None, *, validate: bool = True
) -> dict[str, Any]:
    """Inspect global defaults or one campaign's persisted requested/resolved roster."""

    if identifier:
        campaign = Store().get_campaign(identifier)
        return {
            "scope": "campaign",
            "campaign_id": campaign["id"],
            "campaign": campaign,
            "policy": campaign.get("model_policy") or "inherit",
            "validation": campaign.get("model_validation") or "fallback",
            "allow_child_ultra": bool(campaign.get("allow_child_ultra")),
            "allow_parent_ultra": bool(campaign.get("allow_parent_ultra")),
            "requested": campaign.get("requested_routing") or {},
            "resolved": campaign.get("resolved_routing") or {},
            "catalog": campaign.get("model_catalog_snapshot") or [],
            "warnings": campaign.get("routing_warnings") or [],
            "managed_agents": inspect_managed_agents(),
        }
    return preview_model_routing(validate=validate)


def configure_model_routing(
    identifier: str | None = None,
    *,
    model_policy: str | None = None,
    model_validation: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    role_models: dict[str, Any] | None = None,
    role_efforts: dict[str, Any] | None = None,
    allow_child_ultra: bool | None = None,
    allow_parent_ultra: bool | None = None,
    validate: bool = True,
    reset: bool = False,
) -> dict[str, Any]:
    """Update global defaults or a paused campaign's immutable routing roster."""

    store = Store()
    campaign: dict[str, Any] | None = None
    if identifier:
        campaign = store.get_campaign(identifier)
        _assert_agent_update_safe(store, campaign=campaign)
        if reset:
            base = load_routing_config(create=True)
        elif campaign.get("requested_routing"):
            base = routing_config_from_requested(campaign["requested_routing"])
        else:
            base = {
                "policy": campaign.get("model_policy") or "inherit",
                "validation": campaign.get("model_validation") or "fallback",
                "allow_child_ultra": bool(campaign.get("allow_child_ultra")),
                "allow_parent_ultra": bool(campaign.get("allow_parent_ultra")),
                "parent": {
                    "model": campaign.get("model"),
                    "effort": campaign.get("effort"),
                },
                "roles": {},
            }
    else:
        _assert_agent_update_safe(store)
        base = default_routing_config() if reset else load_routing_config(create=True)

    config = merge_routing_config(
        base,
        policy=model_policy,
        validation=model_validation,
        parent_model=model,
        parent_effort=effort,
        role_models=role_models,
        role_efforts=role_efforts,
        allow_child_ultra=allow_child_ultra,
        allow_parent_ultra=allow_parent_ultra,
    )
    requested = requested_routing_from_config(config)
    resolved, catalog = _resolve_requested_routing(requested, validate=validate)
    agents = ensure_managed_agents(
        resolved, workspace=campaign["workspace"] if campaign else None
    )

    if campaign is not None:
        updated = _persist_campaign_routing(
            store,
            campaign,
            requested=requested,
            resolved=resolved,
            catalog=catalog,
            managed_agents=agents,
        )
        return {
            "scope": "campaign",
            "campaign_id": updated["id"],
            "campaign": updated,
            "config": config,
            "requested": requested,
            "resolved": resolved,
            "catalog": catalog,
            "managed_agents": agents,
            "warnings": list(resolved.get("warnings") or []),
            "routing_warnings": list(resolved.get("warnings") or []),
        }

    saved = save_routing_config(config)
    return {
        "scope": "defaults",
        "config_path": str(routing_config_path()),
        "config": saved,
        "requested": requested,
        "resolved": resolved,
        "catalog": catalog,
        "managed_agents": agents,
        "warnings": list(resolved.get("warnings") or []),
    }


def reset_model_routing(*, validate: bool = True) -> dict[str, Any]:
    return configure_model_routing(validate=validate, reset=True)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def doctor() -> dict[str, Any]:
    codex = shutil.which("codex")
    codex_path = codex_home_path()
    state_path = jam_home_path()
    state_probe = state_path if state_path.exists() else _nearest_existing_parent(state_path)
    state_writable = state_probe.is_dir() and os.access(state_probe, os.W_OK)
    state_detail = str(state_path)
    if not state_path.exists():
        state_detail += f" (will be created under {state_probe})"
    agents_path = codex_path / "agents"
    agents_probe = agents_path if agents_path.exists() else _nearest_existing_parent(agents_path)
    try:
        routing_config = load_routing_config(create=False)
        routing_config_ok = True
        routing_detail = (
            f"{routing_config_path()} · {routing_config['policy']} / "
            f"{routing_config['validation']}"
        )
    except Exception as exc:
        routing_config_ok = False
        routing_detail = f"{routing_config_path()}: {exc}"
    checks: list[dict[str, Any]] = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": sys.version.split()[0],
        },
        {
            "name": "codex_on_path",
            "ok": bool(codex),
            "detail": codex or "not found",
        },
        {
            "name": "codex_home",
            "ok": codex_path.is_dir(),
            "detail": str(codex_path),
        },
        {
            "name": "agents_directory",
            "ok": agents_probe.is_dir() and os.access(agents_probe, os.W_OK),
            "detail": str(agents_path),
        },
        {
            "name": "jam_home",
            "ok": state_writable,
            "detail": state_detail,
        },
        {
            "name": "routing_config",
            "ok": routing_config_ok,
            "detail": routing_detail,
        },
        {
            "name": "plugin_root",
            "ok": (plugin_root() / ".codex-plugin" / "plugin.json").exists(),
            "detail": str(plugin_root()),
        },
    ]
    if codex:
        try:
            command = [codex, "app-server", "--help"]
            if os.name == "nt" and Path(codex).suffix.lower() in {".cmd", ".bat"}:
                command = ["cmd.exe", "/d", "/s", "/c", codex, "app-server", "--help"]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=20, check=False
            )
            checks.append(
                {
                    "name": "app_server",
                    "ok": result.returncode == 0,
                    "detail": (result.stdout or result.stderr).strip()[:500],
                }
            )
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append({"name": "app_server", "ok": False, "detail": str(exc)})
    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "routing": {
            "policies": list(MODEL_POLICIES),
            "validation_modes": list(MODEL_VALIDATION_MODES),
            "efforts": list(EFFORT_ORDER),
            "roles": list(CHILD_ROLES),
            "managed_agents": inspect_managed_agents(),
        },
    }
