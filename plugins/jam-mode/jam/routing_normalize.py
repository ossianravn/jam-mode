from __future__ import annotations

from typing import Any

from .routing_defs import (
    CHILD_ROLES,
    EFFORT_ORDER,
    MODEL_POLICIES,
    MODEL_VALIDATION_MODES,
    RoutingError,
)


def normalize_model(value: object | None) -> str | None:
    if value is None:
        return None
    model = str(value).strip()
    if model.lower() in {"", "inherit", "default", "none", "null"}:
        return None
    return model


def normalize_effort(value: object | None) -> str | None:
    if value is None:
        return None
    effort = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases: dict[str, str | None] = {
        "extra_high": "xhigh",
        "extra_highest": "xhigh",
        "xh": "xhigh",
        "maximum": "max",
        "default": None,
        "inherit": None,
        "none": None,
        "": None,
    }
    effort = aliases.get(effort, effort)
    if effort is None:
        return None
    if effort not in EFFORT_ORDER:
        raise RoutingError(
            f"Unsupported reasoning effort {value!r}; use one of: "
            + ", ".join(EFFORT_ORDER)
        )
    return effort


def normalize_policy(value: object | None, *, default: str = "balanced") -> str:
    policy = str(value or default).strip().lower().replace("-", "_")
    if policy not in MODEL_POLICIES:
        raise RoutingError(
            f"model_policy must be one of: {', '.join(MODEL_POLICIES)}"
        )
    return policy


def normalize_validation_mode(value: object | None, *, default: str = "fallback") -> str:
    mode = str(value or default).strip().lower().replace("-", "_")
    aliases = {"none": "off", "disabled": "off", "validate": "strict"}
    mode = aliases.get(mode, mode)
    if mode not in MODEL_VALIDATION_MODES:
        raise RoutingError(
            "model_validation must be one of: "
            + ", ".join(MODEL_VALIDATION_MODES)
        )
    return mode


def _normalize_override_map(
    values: dict[str, Any] | None,
    *,
    kind: str,
) -> dict[str, str | None]:
    output: dict[str, str | None] = {}
    for raw_role, raw_value in (values or {}).items():
        role = str(raw_role).strip().lower().replace("-", "_")
        if role == "parent":
            parent_field = "effort" if kind == "effort" else "model"
            raise RoutingError(
                f"Parent {parent_field} must use the dedicated {parent_field!r} "
                f"argument, not role_{kind}s['parent']."
            )
        if role not in CHILD_ROLES:
            raise RoutingError(
                f"Unknown model-routing role {raw_role!r}; use one of: "
                + ", ".join(CHILD_ROLES)
            )
        if kind == "effort":
            output[role] = normalize_effort(raw_value)
        else:
            output[role] = normalize_model(raw_value)
    return output
