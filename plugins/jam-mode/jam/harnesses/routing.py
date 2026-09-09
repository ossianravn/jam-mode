from __future__ import annotations

import copy
from typing import Any

from ..routing import build_requested_routing
from .registry import get_adapter, validate_harness
from .types import HarnessError


def resolve_native_routing(harness: str, requested: dict, *, validate: bool = True) -> tuple[dict, list]:
    adapter = get_adapter(harness)
    if validate:
        support = adapter.inspect()
        if not support.get("available") or not support.get("supported"):
            reason = "; ".join(support.get("limitations") or []) or "Required executable/capabilities unavailable."
            raise HarnessError(f"{harness}: {reason}")
    if requested.get("policy") not in {"inherit", "custom"}:
        raise HarnessError(f"{harness} supports inherit/custom routing; Codex presets do not apply.")
    if requested.get("validation") == "fallback":
        raise HarnessError("Cross-model fallback is not supported by signed-in harness adapters.")
    if requested.get("allow_child_ultra") or requested.get("allow_parent_ultra"):
        raise HarnessError("Codex Ultra routing options do not apply to this harness.")
    resolved = copy.deepcopy(requested)
    resolved.update(harness=harness, catalog_status="runtime-verification" if validate else "skipped",
                    warnings=["Account model access is verified by the native harness during execution; "
                              "no authentication or model inference was performed during configuration."])
    return resolved, []


def prepare_native_routing(*, harness: str, workspace=None, model_policy=None, model_validation=None,
                          parent_model=None, parent_effort=None, role_models=None, role_efforts=None,
                          allow_child_ultra=None, allow_parent_ultra=None) -> tuple[dict, dict, list, dict]:
    validate_harness(harness)
    requested = build_requested_routing(policy=model_policy or "inherit", validation=model_validation or "strict",
                                        parent_model=parent_model, parent_effort=parent_effort,
                                        role_models=role_models, role_efforts=role_efforts,
                                        allow_child_ultra=bool(allow_child_ultra),
                                        allow_parent_ultra=bool(allow_parent_ultra))
    requested["harness"] = harness
    resolved, catalog = resolve_native_routing(harness, requested)
    return requested, resolved, catalog, {}


def configure_native_routing(store, campaign: dict, *, validate: bool = True,
                             reset: bool = False, **changes: Any) -> dict:
    from ..service_boundaries import _assert_agent_update_safe
    from ..service_refresh import _persist_campaign_routing
    _assert_agent_update_safe(store, campaign=campaign)
    prior = {} if reset else campaign.get("requested_routing") or {}
    overrides = prior.get("overrides") or {}
    parent = overrides.get("parent") or {}
    roles = overrides.get("roles") or {}
    models = {role: item["model"] for role, item in roles.items() if item.get("model")}
    efforts = {role: item["effort"] for role, item in roles.items() if item.get("effort")}
    models.update(changes.get("role_models") or {})
    efforts.update(changes.get("role_efforts") or {})
    requested = build_requested_routing(
        policy=changes.get("model_policy") or prior.get("policy") or "inherit",
        validation=changes.get("model_validation") or prior.get("validation") or "strict",
        parent_model=changes.get("model") if changes.get("model") is not None else parent.get("model"),
        parent_effort=changes.get("effort") if changes.get("effort") is not None else parent.get("effort"),
        role_models=models, role_efforts=efforts,
        allow_child_ultra=bool(changes.get("allow_child_ultra")),
        allow_parent_ultra=bool(changes.get("allow_parent_ultra")),
    )
    requested["harness"] = campaign["harness"]
    resolved, catalog = resolve_native_routing(campaign["harness"], requested, validate=validate)
    updated = _persist_campaign_routing(store, campaign, requested=requested, resolved=resolved,
                                       catalog=catalog, managed_agents={})
    return {"scope": "campaign", "campaign": updated, "requested": requested, "resolved": resolved,
            "catalog": catalog, "managed_agents": {}, "warnings": resolved["warnings"],
            "routing_warnings": resolved["warnings"]}
