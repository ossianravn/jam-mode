from __future__ import annotations

from typing import Any

from .routing import CHILD_ROLES


def _parse_assignments(values: list[str] | None, *, label: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"{label} must use ROLE=VALUE syntax: {raw!r}")
        role, value = raw.split("=", 1)
        role = role.strip().lower().replace("-", "_")
        if role == "parent":
            option = "--role-effort" if "effort" in label else "--role-model"
            dedicated = "--effort" if "effort" in label else "--model"
            raise ValueError(
                f"{option} does not accept the parent role; use {dedicated}."
            )
        if role not in CHILD_ROLES:
            raise ValueError(
                f"Unknown routing role {role!r}; use one of: "
                + ", ".join(CHILD_ROLES)
            )
        if not value.strip():
            raise ValueError(f"{label} has an empty value for role {role!r}.")
        output[role] = value.strip()
    return output


def _print_roster(resolved: dict[str, Any]) -> None:
    parent = resolved.get("parent") or {}
    print(
        "Parent:       "
        f"{parent.get('model') or 'inherit'} · {parent.get('effort') or 'default'}"
    )
    for role, item in (resolved.get("roles") or {}).items():
        print(
            f"{role + ':':<14} {item.get('agent') or 'unknown'} · "
            f"{item.get('model') or 'inherit'} · {item.get('effort') or 'default'} · "
            f"{item.get('sandbox') or 'inherit'}"
        )


def _print_status(payload: dict[str, Any]) -> None:
    campaign = payload["campaign"]
    last = payload.get("last_episode")
    print(f"JAM campaign: {campaign['name']}")
    print(f"ID:           {campaign['id']}")
    print(f"Status:       {campaign['status']}")
    print(f"Enabled:      {campaign['enabled']}")
    print(f"Workspace:    {campaign['workspace']}")
    print(f"Profile:      {campaign.get('task_profile') or 'adaptive'}")
    print(f"Episodes:     {campaign['episode_count']} / {campaign['max_episodes']}")
    print(f"Sandbox:      {campaign['sandbox']}")
    print(f"Model policy: {campaign.get('model_policy') or 'inherit'}")
    print(f"Validation:   {campaign.get('model_validation') or 'fallback'}")
    parent = (campaign.get("resolved_routing") or {}).get("parent") or {}
    print(
        f"Parent model: {parent.get('model') or campaign.get('model') or 'inherit'} · "
        f"{parent.get('effort') or campaign.get('effort') or 'default'}"
    )
    print(f"Controller:   {'running' if payload.get('controller_alive') else 'not running'}")
    if campaign.get("active_episode_id"):
        print(f"Active:       {campaign['active_episode_id']}")
    if last:
        print(f"Last episode: {last['number']} — {last['status']}")
        handoff = last.get("handoff") or {}
        if handoff.get("task_profile"):
            print(f"Last profile: {handoff['task_profile']}")
        if handoff.get("summary"):
            print(f"Last result:  {handoff['summary']}")
        if handoff.get("user_question"):
            print(f"Question:     {handoff['user_question']}")
        if last.get("thread_id"):
            print(f"Thread:       {last['thread_id']}")
        if last.get("agent_activity"):
            print(f"Subagents:    {len(last['agent_activity'])} collaboration call(s) recorded")
    warnings = campaign.get("routing_warnings") or []
    if warnings:
        print("Routing warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    if campaign.get("last_error"):
        print(f"Attention:    {campaign['last_error']}")
    print(f"Files:        {payload['campaign_directory']}")
