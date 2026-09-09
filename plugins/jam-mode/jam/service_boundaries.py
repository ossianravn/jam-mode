from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .lifecycle import LIVE_CAMPAIGN_STATUSES
from .store import Store, StoreError


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
        "Run local commands and validation permitted by the selected harness's execution controls.",
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
    campaign = store.live_campaign(exclude_id=exclude_id)
    if campaign is not None:
        raise StoreError(
            "JAM permits one live campaign at a time. "
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
            campaign.get("status") in LIVE_CAMPAIGN_STATUSES
        ):
            raise StoreError(
                "Pause the campaign and let its current episode finish before changing "
                "its model-routing roster."
            )

    live = store.live_campaign(exclude_id=target_id)
    if live is not None:
        raise StoreError(
            "Pause the active JAM campaign before changing model-routing settings; "
            "JAM custom-agent names are shared by the single live campaign."
        )
