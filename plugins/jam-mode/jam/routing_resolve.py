from __future__ import annotations

import json
from typing import Any, Iterable

from .routing_catalog import (
    _catalog_map,
    _default_model,
    _fallback_model_for_role,
    _nearest_effort,
    _supported_efforts,
    normalize_catalog,
)
from .routing_defs import (
    ALL_ROUTING_ROLES,
    CHILD_ROLES,
    EFFORT_ORDER,
    ROLE_AGENT_NAMES,
    ROLE_SPECS,
    ROUTING_SCHEMA_VERSION,
    STRATEGY_AGENT_ROUTES,
    RoutingError,
)
from .routing_normalize import (
    normalize_effort,
    normalize_model,
    normalize_policy,
    normalize_validation_mode,
)
from .util import utc_now


def resolve_routing(
    requested: dict[str, Any],
    *,
    catalog_entries: Iterable[dict[str, Any]] | None,
    catalog_error: str | None = None,
) -> dict[str, Any]:
    """Resolve requested model/effort settings against an installed Codex catalog."""

    requested = json.loads(json.dumps(requested))
    validation = normalize_validation_mode(requested.get("validation"))
    allow_child_ultra = bool(requested.get("allow_child_ultra"))
    allow_parent_ultra = bool(requested.get("allow_parent_ultra"))
    catalog = normalize_catalog(catalog_entries or [])
    catalog_by_id = _catalog_map(catalog)
    warnings: list[str] = []

    if catalog_error:
        if validation == "strict":
            raise RoutingError(
                "Strict model validation could not read the installed Codex model catalog: "
                + catalog_error
            )
        warnings.append(
            "Installed model catalog was unavailable; routing remains unvalidated: "
            + catalog_error
        )

    if validation == "strict" and not catalog:
        raise RoutingError(
            "Strict model validation requires a non-empty installed Codex model catalog."
        )

    resolved: dict[str, Any] = {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "policy": normalize_policy(requested.get("policy")),
        "validation": validation,
        "allow_child_ultra": allow_child_ultra,
        "allow_parent_ultra": allow_parent_ultra,
        "catalog_status": (
            "validated"
            if catalog and validation != "off"
            else ("not_requested" if validation == "off" else "unavailable")
        ),
        "catalog_checked_at": utc_now(),
        "parent": {},
        "roles": {},
        "strategy_routes": {
            strategy: list(roles)
            for strategy, roles in STRATEGY_AGENT_ROUTES.items()
        },
        "warnings": warnings,
        "resolved_at": utc_now(),
    }

    def resolve_entry(
        role: str, source: dict[str, Any], *, child: bool
    ) -> dict[str, Any]:
        requested_model = normalize_model(source.get("model"))
        requested_effort = normalize_effort(source.get("effort"))
        ultra_allowed = allow_child_ultra if child else allow_parent_ultra
        if requested_effort == "ultra" and not ultra_allowed:
            if validation == "strict":
                target = "child" if child else "parent"
                raise RoutingError(
                    f"Role {role} requests ultra, but {target} Ultra is disabled. "
                    f"Enable allow_{target}_ultra or select max/xhigh/high."
                )
            requested_effort = "max"
            warnings.append(
                f"Role {role}: ultra was reduced to max because Ultra is disabled for this role type."
            )

        model = requested_model
        effort = requested_effort
        model_entry: dict[str, Any] | None = None

        if validation != "off" and catalog:
            if model:
                model_entry = catalog_by_id.get(model)
                if model_entry is None:
                    if validation == "strict":
                        raise RoutingError(
                            f"Role {role} requests model {model!r}, which is not available in the installed Codex catalog."
                        )
                    replacement = _fallback_model_for_role(
                        role, catalog, catalog_by_id
                    )
                    if replacement:
                        warnings.append(
                            f"Role {role}: model {model!r} is unavailable; using {replacement['id']!r}."
                        )
                        model = str(replacement["id"])
                        model_entry = replacement
                elif model_entry.get("hidden"):
                    warnings.append(
                        f"Role {role}: model {model!r} is available but hidden from the default picker."
                    )
            elif role == "parent":
                # An inherited parent still runs on Codex's catalog default. Keep
                # ``model`` unset so Codex retains normal inheritance, but use the
                # advertised default entry to validate an explicit effort.
                model_entry = _default_model(catalog)
            else:
                parent_model = str(
                    resolved.get("parent", {}).get("model") or ""
                ).strip()
                model_entry = (
                    catalog_by_id.get(parent_model)
                    if parent_model
                    else _default_model(catalog)
                )

            if effort and model_entry:
                supported = list(model_entry.get("supported_efforts") or [])
                if effort not in supported:
                    if validation == "strict":
                        raise RoutingError(
                            f"Role {role} requests effort {effort!r} for {model_entry['id']!r}; "
                            f"supported efforts are: {', '.join(supported) or 'not advertised'}."
                        )
                    replacement_effort = _nearest_effort(
                        effort,
                        supported,
                        model_entry.get("default_effort"),
                    )
                    if replacement_effort:
                        warnings.append(
                            f"Role {role}: effort {effort!r} is unsupported by {model_entry['id']!r}; "
                            f"using {replacement_effort!r}."
                        )
                        effort = replacement_effort
                    else:
                        warnings.append(
                            f"Role {role}: effort {effort!r} could not be validated for {model_entry['id']!r}; "
                            "the model default will be used."
                        )
                        effort = None
            elif effort and not model_entry and validation == "strict":
                raise RoutingError(
                    f"Role {role} specifies effort {effort!r} without a resolvable model."
                )

        return {
            "role": role,
            "agent": source.get("agent"),
            "sandbox": source.get("sandbox"),
            "model": model,
            "effort": effort,
            "requested_model": requested_model,
            "requested_effort": normalize_effort(source.get("effort")),
            "model_display_name": (
                model_entry.get("display_name") if model_entry else None
            ),
            "validated_against_model": (
                model_entry.get("id") if model_entry else None
            ),
            "supported_efforts": (
                list(model_entry.get("supported_efforts") or [])
                if model_entry
                else []
            ),
        }

    resolved["parent"] = resolve_entry(
        "parent", requested.get("parent") or {}, child=False
    )
    for role in CHILD_ROLES:
        source = (requested.get("roles") or {}).get(role) or {
            "role": role,
            "agent": ROLE_AGENT_NAMES[role],
            "sandbox": ROLE_SPECS[role]["sandbox"],
            "model": None,
            "effort": None,
        }
        resolved["roles"][role] = resolve_entry(role, source, child=True)

    resolved["warnings"] = list(
        dict.fromkeys(str(item) for item in warnings if str(item).strip())
    )
    return resolved
