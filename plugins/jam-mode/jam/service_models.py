from __future__ import annotations

from typing import Any

from .routing import (
    default_routing_config,
    ensure_managed_agents,
    fetch_installed_model_catalog,
    inspect_managed_agents,
    load_routing_config,
    merge_routing_config,
    model_catalog_snapshot,
    requested_routing_from_config,
    routing_config_from_requested,
    routing_config_path,
    save_routing_config,
)
from .service_boundaries import _assert_agent_update_safe
from .service_refresh import _persist_campaign_routing
from .service_support import _resolve_requested_routing
from .store import Store


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


def list_model_catalog(*, include_hidden: bool = False, harness: str = "codex") -> dict[str, Any]:
    """Compatibility/public alias used by the CLI and MCP surface."""

    if harness == "codex":
        return list_models(include_hidden=include_hidden)
    from .harnesses.registry import get_adapter
    result = get_adapter(harness).models()
    return {**result, "harness": harness, "count": len(result["models"])}


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
            "managed_agents": inspect_managed_agents() if campaign.get("harness", "codex") == "codex" else {},
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
        if campaign.get("harness", "codex") != "codex":
            from .harnesses.routing import configure_native_routing
            return configure_native_routing(store, campaign, validate=validate, reset=reset,
                                            model_policy=model_policy, model_validation=model_validation,
                                            model=model, effort=effort, role_models=role_models,
                                            role_efforts=role_efforts, allow_child_ultra=allow_child_ultra,
                                            allow_parent_ultra=allow_parent_ultra)
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
