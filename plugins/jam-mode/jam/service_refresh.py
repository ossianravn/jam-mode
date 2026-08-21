from __future__ import annotations

from typing import Any

from .routing import build_requested_routing, ensure_managed_agents
from .service_boundaries import _assert_agent_update_safe
from .service_support import _resolve_requested_routing, _write_charter
from .store import Store


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
