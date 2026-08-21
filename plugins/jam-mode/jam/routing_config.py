from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import jam_home_path
from .routing_defs import (
    CHILD_ROLES,
    PRESET_ROUTING,
    ROUTING_CONFIG_SCHEMA_VERSION,
)
from .routing_normalize import (
    _normalize_override_map,
    normalize_effort,
    normalize_model,
    normalize_policy,
    normalize_validation_mode,
)
from .util import atomic_write


def default_routing_config() -> dict[str, Any]:
    return {
        "schema_version": ROUTING_CONFIG_SCHEMA_VERSION,
        "policy": "balanced",
        "validation": "fallback",
        "allow_child_ultra": False,
        "allow_parent_ultra": False,
        "parent": {"model": None, "effort": None},
        "roles": {
            role: {"model": None, "effort": None} for role in CHILD_ROLES
        },
    }


def routing_config_path() -> Path:
    return jam_home_path() / "config.toml"


from .routing_toml import _read_toml, _toml_string


def render_routing_config(config: dict[str, Any]) -> str:
    normalized = normalize_routing_config(config)
    lines = [
        "# JAM Mode model-routing configuration.",
        "# Managed agents are generated in $CODEX_HOME/agents/jam_*.toml.",
        f"schema_version = {ROUTING_CONFIG_SCHEMA_VERSION}",
        f"policy = {_toml_string(normalized['policy'])}",
        f"validation = {_toml_string(normalized['validation'])}",
        f"allow_child_ultra = {str(bool(normalized['allow_child_ultra'])).lower()}",
        f"allow_parent_ultra = {str(bool(normalized['allow_parent_ultra'])).lower()}",
        "",
        "[parent]",
    ]
    parent = normalized["parent"]
    if parent.get("model"):
        lines.append(f"model = {_toml_string(str(parent['model']))}")
    if parent.get("effort"):
        lines.append(f"effort = {_toml_string(str(parent['effort']))}")
    for role in CHILD_ROLES:
        lines.extend(["", f"[roles.{role}]"])
        entry = normalized["roles"][role]
        if entry.get("model"):
            lines.append(f"model = {_toml_string(str(entry['model']))}")
        if entry.get("effort"):
            lines.append(f"effort = {_toml_string(str(entry['effort']))}")
    lines.append("")
    return "\n".join(lines)


def normalize_routing_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    config = default_routing_config()
    config["policy"] = normalize_policy(raw.get("policy"), default=config["policy"])
    config["validation"] = normalize_validation_mode(
        raw.get("validation"), default=config["validation"]
    )
    config["allow_child_ultra"] = bool(
        raw.get("allow_child_ultra", config["allow_child_ultra"])
    )
    config["allow_parent_ultra"] = bool(
        raw.get("allow_parent_ultra", config["allow_parent_ultra"])
    )
    parent = raw.get("parent") if isinstance(raw.get("parent"), dict) else {}
    config["parent"] = {
        "model": normalize_model(parent.get("model")),
        "effort": normalize_effort(parent.get("effort")),
    }
    roles_raw = raw.get("roles") if isinstance(raw.get("roles"), dict) else {}
    for role in CHILD_ROLES:
        entry = roles_raw.get(role) if isinstance(roles_raw.get(role), dict) else {}
        config["roles"][role] = {
            "model": normalize_model(entry.get("model")),
            "effort": normalize_effort(entry.get("effort")),
        }
    return config


def load_routing_config(*, create: bool = True) -> dict[str, Any]:
    path = routing_config_path()
    if not path.exists():
        config = default_routing_config()
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, render_routing_config(config))
        return config
    return normalize_routing_config(_read_toml(path))


def save_routing_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_routing_config(config)
    path = routing_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, render_routing_config(normalized))
    return normalized


def reset_routing_config() -> dict[str, Any]:
    return save_routing_config(default_routing_config())


def merge_routing_config(
    base: dict[str, Any],
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
    config = normalize_routing_config(base)
    if policy is not None:
        config["policy"] = normalize_policy(policy)
    if validation is not None:
        config["validation"] = normalize_validation_mode(validation)
    if parent_model is not None:
        config["parent"]["model"] = normalize_model(parent_model)
    if parent_effort is not None:
        config["parent"]["effort"] = normalize_effort(parent_effort)
    models = _normalize_override_map(role_models, kind="model")
    efforts = _normalize_override_map(role_efforts, kind="effort")
    for role, value in models.items():
        config["roles"][role]["model"] = value
    for role, value in efforts.items():
        config["roles"][role]["effort"] = value
    if allow_child_ultra is not None:
        config["allow_child_ultra"] = bool(allow_child_ultra)
    if allow_parent_ultra is not None:
        config["allow_parent_ultra"] = bool(allow_parent_ultra)
    return normalize_routing_config(config)


def routing_config_from_requested(requested: dict[str, Any]) -> dict[str, Any]:
    """Convert a persisted requested roster back into editable config form.

    Preset-derived values are not treated as explicit overrides. This matters
    when a paused campaign changes policy: moving from ``balanced`` to
    ``quality`` should select the quality preset while retaining only genuine
    per-role overrides.
    """

    requested = requested or {}
    policy = normalize_policy(requested.get("policy"), default="inherit")
    parent = requested.get("parent") if isinstance(requested.get("parent"), dict) else {}
    roles_raw = requested.get("roles") if isinstance(requested.get("roles"), dict) else {}
    overrides = requested.get("overrides") if isinstance(requested.get("overrides"), dict) else None

    if overrides is not None:
        parent_overrides = (
            overrides.get("parent")
            if isinstance(overrides.get("parent"), dict)
            else {}
        )
        role_overrides_raw = (
            overrides.get("roles")
            if isinstance(overrides.get("roles"), dict)
            else {}
        )
    else:
        # Compatibility for early 0.3 development builds that persisted the
        # fully expanded requested roster without explicit override metadata.
        preset = PRESET_ROUTING[policy]
        parent_overrides = {}
        for key in ("model", "effort"):
            value = parent.get(f"requested_{key}", parent.get(key))
            if value is not None and value != preset["parent"].get(key):
                parent_overrides[key] = value
        role_overrides_raw: dict[str, dict[str, Any]] = {}
        for role in CHILD_ROLES:
            source = roles_raw.get(role) if isinstance(roles_raw.get(role), dict) else {}
            role_overrides: dict[str, Any] = {}
            for key in ("model", "effort"):
                value = source.get(f"requested_{key}", source.get(key))
                if value is not None and value != preset[role].get(key):
                    role_overrides[key] = value
            role_overrides_raw[role] = role_overrides

    return normalize_routing_config(
        {
            "schema_version": ROUTING_CONFIG_SCHEMA_VERSION,
            "policy": policy,
            "validation": requested.get("validation") or "fallback",
            "allow_child_ultra": bool(requested.get("allow_child_ultra")),
            "allow_parent_ultra": bool(requested.get("allow_parent_ultra")),
            "parent": {
                "model": parent_overrides.get("model"),
                "effort": parent_overrides.get("effort"),
            },
            "roles": {
                role: {
                    "model": (
                        role_overrides_raw.get(role) or {}
                    ).get("model"),
                    "effort": (
                        role_overrides_raw.get(role) or {}
                    ).get("effort"),
                }
                for role in CHILD_ROLES
            },
        }
    )
