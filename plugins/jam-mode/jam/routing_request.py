from __future__ import annotations

from typing import Any

from .routing_config import load_routing_config, merge_routing_config
from .routing_defs import (
    CHILD_ROLES,
    PRESET_ROUTING,
    ROLE_AGENT_NAMES,
    ROLE_SPECS,
    ROUTING_SCHEMA_VERSION,
    STRATEGY_AGENT_ROUTES,
)
from .routing_normalize import (
    _normalize_override_map,
    normalize_effort,
    normalize_model,
    normalize_policy,
    normalize_validation_mode,
)


def build_requested_routing(
    *,
    policy: str = "balanced",
    validation: str = "strict",
    parent_model: str | None = None,
    parent_effort: str | None = None,
    role_models: dict[str, Any] | None = None,
    role_efforts: dict[str, Any] | None = None,
    allow_child_ultra: bool = False,
    allow_parent_ultra: bool = False,
) -> dict[str, Any]:
    policy = normalize_policy(policy)
    validation = normalize_validation_mode(validation)
    model_overrides = _normalize_override_map(role_models, kind="model")
    effort_overrides = _normalize_override_map(role_efforts, kind="effort")
    normalized_parent_model = normalize_model(parent_model)
    normalized_parent_effort = normalize_effort(parent_effort)

    base = PRESET_ROUTING[policy]
    parent = dict(base["parent"])
    roles: dict[str, dict[str, Any]] = {}
    if normalized_parent_model is not None:
        parent["model"] = normalized_parent_model
    if normalized_parent_effort is not None:
        parent["effort"] = normalized_parent_effort
    parent.update({"role": "parent", "agent": None, "sandbox": None})

    for role in CHILD_ROLES:
        entry = dict(base[role])
        if model_overrides.get(role) is not None:
            entry["model"] = model_overrides[role]
        if effort_overrides.get(role) is not None:
            entry["effort"] = effort_overrides[role]
        entry.update(
            {
                "role": role,
                "agent": ROLE_AGENT_NAMES[role],
                "sandbox": ROLE_SPECS[role]["sandbox"],
            }
        )
        roles[role] = entry

    explicit_overrides = {
        "parent": {
            key: value
            for key, value in {
                "model": normalized_parent_model,
                "effort": normalized_parent_effort,
            }.items()
            if value is not None
        },
        "roles": {
            role: {
                key: value
                for key, value in {
                    "model": model_overrides.get(role),
                    "effort": effort_overrides.get(role),
                }.items()
                if value is not None
            }
            for role in CHILD_ROLES
        },
    }

    return {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "policy": policy,
        "validation": validation,
        "allow_child_ultra": bool(allow_child_ultra),
        "allow_parent_ultra": bool(allow_parent_ultra),
        "overrides": explicit_overrides,
        "parent": parent,
        "roles": roles,
        "strategy_routes": {
            strategy: list(roles_for_strategy)
            for strategy, roles_for_strategy in STRATEGY_AGENT_ROUTES.items()
        },
    }


def requested_routing_from_config(
    config: dict[str, Any],
    *,
    policy: str | None = None,
    validation: str | None = None,
    parent_model: str | None = None,
    parent_effort: str | None = None,
    role_models: dict[str, Any] | None = None,
    role_efforts: dict[str, Any] | None = None,
    allow_child_ultra: bool | None = None,
    allow_parent_ultra: bool | None = None,
) -> dict[str, Any]:
    merged = merge_routing_config(
        config,
        policy=policy,
        validation=validation,
        parent_model=parent_model,
        parent_effort=parent_effort,
        role_models=role_models,
        role_efforts=role_efforts,
        allow_child_ultra=allow_child_ultra,
        allow_parent_ultra=allow_parent_ultra,
    )
    models = {
        role: entry.get("model")
        for role, entry in merged["roles"].items()
        if entry.get("model") is not None
    }
    efforts = {
        role: entry.get("effort")
        for role, entry in merged["roles"].items()
        if entry.get("effort") is not None
    }
    return build_requested_routing(
        policy=merged["policy"],
        validation=merged["validation"],
        parent_model=merged["parent"].get("model"),
        parent_effort=merged["parent"].get("effort"),
        role_models=models,
        role_efforts=efforts,
        allow_child_ultra=bool(merged["allow_child_ultra"]),
        allow_parent_ultra=bool(merged["allow_parent_ultra"]),
    )
