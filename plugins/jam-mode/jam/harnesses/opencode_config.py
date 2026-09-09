"""Isolated OpenCode configuration retaining only existing OAuth login data."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..routing_defs import ROLE_AGENT_NAMES, ROLE_SPECS
from .process import signed_in_environment
from .types import HarnessError


PROVIDER = "github-copilot"


def model_parts(model: str | None) -> dict:
    if not isinstance(model, str) or not model.startswith(PROVIDER + "/") or not model.split("/", 1)[1]:
        raise HarnessError("OpenCode requires an explicit github-copilot/<model> using existing OAuth sign-in.")
    return {"providerID": PROVIDER, "modelID": model.split("/", 1)[1]}


def configuration(campaign: dict) -> tuple[dict, dict]:
    if campaign.get("allow_network"):
        raise HarnessError("OpenCode task network tools are not supported by this adapter.")
    overrides = (campaign.get("resolved_routing") or {}).get("overrides") or {}
    parent = overrides.get("parent") or {}
    model_parts(parent.get("model"))
    if parent.get("effort") or any(item.get("effort") for item in (overrides.get("roles") or {}).values()):
        raise HarnessError("OpenCode effort variants are provider-specific and not yet supported by JAM.")
    read = {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow"}
    # Primary agents can also be task targets; allow only the read-only roles.
    task_permissions = {"*": "deny", **{ROLE_AGENT_NAMES[role]: "allow" for role in ROLE_SPECS}}
    parent_permissions = {**read, "task": task_permissions}
    if campaign.get("sandbox") == "workspace-write":
        parent_permissions["edit"] = "allow"
    agents = {"jam_parent": {"mode": "primary", "model": parent["model"],
                              "permission": parent_permissions,
                              "prompt": "Coordinate the JAM agents. Only you may edit files."}}
    requested = {"parent": parent["model"]}
    for role, spec in ROLE_SPECS.items():
        name = ROLE_AGENT_NAMES[role]
        model = ((overrides.get("roles") or {}).get(role) or {}).get("model") or parent["model"]
        model_parts(model)
        requested[name] = model
        agents[name] = {"mode": "subagent", "model": model, "description": spec["description"],
                        "permission": read,
                        "prompt": spec["instructions"] + "\nOnly return findings; parent owns all edits."}
    return {"model": parent["model"], "small_model": parent["model"],
            "default_agent": "jam_parent", "enabled_providers": [PROVIDER],
            "share": "disabled", "autoupdate": False, "snapshot": False,
            "permission": read, "agent": agents, "mcp": {}, "plugin": [],
            "formatter": False, "lsp": False}, requested


def isolated_environment(directory: Path, config: dict) -> dict:
    environment = signed_in_environment("opencode")
    data_home = Path(environment.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    try:
        credentials = json.loads((data_home / "opencode" / "auth.json").read_text(encoding="utf-8"))
        signed_in = (credentials.get(PROVIDER) or {}).get("type") == "oauth"
        if any(isinstance(value, dict) and value.get("type") == "wellknown" for value in credentials.values()):
            raise HarnessError("OpenCode remote organization authentication configuration cannot be isolated.")
    except (OSError, ValueError, AttributeError) as exc:
        raise HarnessError("OpenCode existing OAuth login could not be confirmed; sign in separately.") from exc
    if not signed_in:
        raise HarnessError("OpenCode requires existing GitHub Copilot OAuth sign-in; API credentials are unsupported.")
    # Managed configuration overrides inline configuration and cannot be isolated.
    managed = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "opencode" if os.name == "nt" else Path("/etc/opencode")
    if managed.exists():
        raise HarnessError("OpenCode managed configuration prevents isolated campaign permissions on this host.")
    for key in list(environment):
        if key.startswith("OPENCODE_"):
            del environment[key]
    environment.update({
        "HOME": str(directory), "USERPROFILE": str(directory),
        "XDG_DATA_HOME": str(data_home), "XDG_CONFIG_HOME": str(directory / "config"),
        "XDG_CACHE_HOME": str(directory / "cache"), "XDG_STATE_HOME": str(directory / "state"),
        "OPENCODE_CONFIG_DIR": str(directory / "config" / "opencode"),
        "OPENCODE_CONFIG_CONTENT": json.dumps(config), "OPENCODE_PURE": "true",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true", "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "true", "OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER": "true",
    })
    return environment
