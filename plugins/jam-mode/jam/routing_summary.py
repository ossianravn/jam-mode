from __future__ import annotations

from typing import Any

from .routing_defs import (
    CHILD_ROLES,
    ROLE_AGENT_NAMES,
    ROLE_SPECS,
    STRATEGY_AGENT_ROUTES,
)


def routing_prompt_summary(resolved: dict[str, Any]) -> str:
    parent = resolved.get("parent") or {}
    lines = [
        f"Policy: {resolved.get('policy') or 'inherit'}",
        f"Validation: {resolved.get('validation') or 'off'} ({resolved.get('catalog_status') or 'unknown'})",
        f"Parent Ultra allowed: {bool(resolved.get('allow_parent_ultra'))}",
        f"Child Ultra allowed: {bool(resolved.get('allow_child_ultra'))}",
        "Parent / synthesizer: "
        + f"{parent.get('model') or 'inherit'} · {parent.get('effort') or 'default'}",
        "Named child agents:",
    ]
    for role in CHILD_ROLES:
        item = (resolved.get("roles") or {}).get(role) or {}
        lines.append(
            f"- {role}: {item.get('agent') or ROLE_AGENT_NAMES[role]} · "
            f"{item.get('model') or 'inherit'} · {item.get('effort') or 'default'} · "
            f"{item.get('sandbox') or ROLE_SPECS[role]['sandbox']}"
        )
    warnings = resolved.get("warnings") or []
    if warnings:
        lines.append("Resolution warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def strategy_routing_instructions(resolved: dict[str, Any]) -> str:
    routes = STRATEGY_AGENT_ROUTES
    role_entries = resolved.get("roles") or {}
    lines = [
        "Use the following exact named custom agents when the selected strategy calls for them:",
    ]
    for strategy, roles in routes.items():
        names = [
            str((role_entries.get(role) or {}).get("agent") or ROLE_AGENT_NAMES.get(role, role))
            for role in roles
        ]
        if strategy == "planner_executor":
            description = (
                f"{names[0]} first, then choose exactly one writer: {names[1]} for engineering/data/operations "
                f"or {names[2]} for documentation/content/planning outputs"
            )
        elif strategy == "execute_validate":
            description = (
                f"choose exactly one writer ({names[0]} or {names[1]}), then {names[2]}"
            )
        elif strategy == "duo_independent":
            description = f"{names[0]} and {names[1]} independently in parallel, then parent synthesis"
        elif strategy in {"parallel_explore", "map_reduce"}:
            description = f"at least two independent instances of {names[0]} within the concurrency limit"
        else:
            description = " → ".join(names)
        lines.append(f"- {strategy}: {description}")
    lines.extend(
        [
            "Use the routed JAM roles. If a required named agent is unavailable, stop with needs_user_input and explain the missing contribution.",
            "The parent thread remains the orchestrator and final synthesizer. Child agents must not decide campaign continuation or spawn nested agents.",
            "Never run jam_implementer and jam_producer concurrently. There is exactly one writer for a shared checkout.",
        ]
    )
    return "\n".join(lines)
