from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, Iterable

from .paths import codex_home_path, jam_home_path
from .util import atomic_write, json_dumps, utc_now


ROUTING_SCHEMA_VERSION: Final[int] = 1
ROUTING_CONFIG_SCHEMA_VERSION: Final[int] = 1
MANAGED_AGENT_MARKER: Final[str] = "# JAM_MODE_MANAGED=1"

MODEL_POLICIES: Final[tuple[str, ...]] = (
    "inherit",
    "economy",
    "balanced",
    "quality",
    "custom",
)

MODEL_VALIDATION_MODES: Final[tuple[str, ...]] = (
    "strict",
    "fallback",
    "off",
)

EFFORT_ORDER: Final[tuple[str, ...]] = (
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)

CHILD_ROLES: Final[tuple[str, ...]] = (
    "explorer",
    "bulk_worker",
    "planner",
    "implementer",
    "producer",
    "reviewer",
    "validator",
    "critic",
    "closer",
)
ALL_ROUTING_ROLES: Final[tuple[str, ...]] = ("parent",) + CHILD_ROLES
ROLE_AGENT_NAMES: Final[dict[str, str]] = {
    role: f"jam_{role}" for role in CHILD_ROLES
}

ROLE_SPECS: Final[dict[str, dict[str, str]]] = {
    "explorer": {
        "description": (
            "Fast, read-heavy JAM explorer for codebase mapping, document inspection, "
            "targeted searches, evidence gathering, and bounded option discovery."
        ),
        "sandbox": "read-only",
        "instructions": """
Perform only the bounded delegated exploration assignment.

Prefer targeted search, file reads, extraction, classification, and concrete
references over broad speculation. Return a compact result to the parent with
paths, symbols, evidence references, uncertainty, and boundary concerns.

Do not modify files. Do not expand the assignment. Do not invoke JAM campaign
controls. Do not spawn additional agents. Do not decide whether another JAM
episode should start.
""".strip(),
    },
    "bulk_worker": {
        "description": (
            "JAM worker for clear, separable, repeatable, or high-volume read-heavy "
            "subtasks that return structured results for aggregation."
        ),
        "sandbox": "read-only",
        "instructions": """
Complete only the assigned shard or batch. Follow the requested output shape,
retain provenance, and distinguish completed items from failures or ambiguity.
Return concise structured results suitable for deterministic aggregation.

Do not modify shared workspace files. Do not expand scope. Do not invoke JAM
campaign controls. Do not spawn additional agents.
""".strip(),
    },
    "planner": {
        "description": (
            "JAM planning specialist for decomposing bounded work, identifying "
            "dependencies, sequencing actions, and defining verification criteria."
        ),
        "sandbox": "read-only",
        "instructions": """
Create a bounded, executable plan for the delegated objective. Identify concrete
steps, dependencies, decision points, acceptance criteria, risks, and validation.
Prefer the smallest plan that can satisfy the objective.

Do not implement the plan unless explicitly asked. Do not modify files. Do not
invoke JAM campaign controls. Do not spawn additional agents.
""".strip(),
    },
    "implementer": {
        "description": (
            "JAM's single engineering writer for producing or modifying code, tests, "
            "configuration, migrations, tooling, or data-processing artifacts."
        ),
        "sandbox": "workspace-write",
        "instructions": """
Own the bounded implementation assignment as the only writer. Make the smallest
defensible change, preserve unrelated work, and satisfy the stated acceptance
criteria. Run focused checks when permitted and return exact files, commands,
outputs, and remaining uncertainty.

Do not edit outside the authorized workspace. Do not broaden the assignment.
Do not invoke JAM campaign controls. Do not spawn additional agents. Never edit
concurrently with another writer.
""".strip(),
    },
    "producer": {
        "description": (
            "JAM's single production writer for documents, plans, reports, content, "
            "structured outputs, and other non-code deliverables."
        ),
        "sandbox": "workspace-write",
        "instructions": """
Produce the bounded requested deliverable as the only writer. Follow the stated
audience, format, style, requirements, and acceptance criteria. Preserve unrelated
workspace content and report the exact artifact location and validation performed.

Do not broaden the assignment. Do not publish or deploy externally. Do not invoke
JAM campaign controls. Do not spawn additional agents. Never edit concurrently
with another writer.
""".strip(),
    },
    "reviewer": {
        "description": (
            "Independent JAM reviewer for correctness, security, regressions, edge "
            "cases, missing tests, unsupported conclusions, and acceptance criteria."
        ),
        "sandbox": "read-only",
        "instructions": """
Review the delegated artifact or result independently. Prioritize correctness,
security, behavioral regressions, unsupported claims, hidden assumptions,
missing validation, and incomplete acceptance criteria. Lead with concrete,
prioritized findings and cite evidence.

Do not edit files. Do not merely agree with the producer. Do not invoke JAM
campaign controls. Do not spawn additional agents.
""".strip(),
    },
    "validator": {
        "description": (
            "JAM validation specialist for reproductions, tests, checks, measurements, "
            "and independent confirmation or falsification of claimed outcomes."
        ),
        "sandbox": "read-only",
        "instructions": """
Independently validate the assigned claim, implementation, output, or operation.
Use discriminating checks and report exact commands, inputs, observed results,
and limitations. Prefer falsification-capable tests over superficial confirmation.

Do not alter the deliverable under review. Do not invoke JAM campaign controls.
Do not spawn additional agents.
""".strip(),
    },
    "critic": {
        "description": (
            "Adversarial JAM critic for challenging proposals, assumptions, drafts, "
            "interpretations, and research directions before synthesis."
        ),
        "sandbox": "read-only",
        "instructions": """
Challenge the assigned proposal or interpretation independently. Search for
counterexamples, alternative explanations, trade-offs, omissions, and failure
modes. Distinguish decisive objections from lower-confidence concerns and state
what evidence would resolve disagreement.

Do not modify files. Do not invoke JAM campaign controls. Do not spawn agents.
""".strip(),
    },
    "closer": {
        "description": (
            "JAM closure specialist for consolidating final deliverables, completion "
            "evidence, limitations, unresolved items, and a clean campaign conclusion."
        ),
        "sandbox": "read-only",
        "instructions": """
Assess whether the campaign objective and success criteria are actually met.
Consolidate final deliverables, validation, limitations, residual risks, and
unresolved items without inventing work merely to continue. Produce a concise,
auditable closure recommendation for the parent.

Do not modify files. Do not invoke JAM controls. Do not spawn additional agents.
""".strip(),
    },
}

# These routes are a deterministic baseline. The parent can omit unnecessary
# roles, but it should not silently replace a routed role with an unnamed worker.
STRATEGY_AGENT_ROUTES: Final[dict[str, tuple[str, ...]]] = {
    "solo": (),
    "parallel_explore": ("explorer",),
    "critique_synthesize": ("critic", "reviewer"),
    "map_reduce": ("bulk_worker",),
    "builder_reviewer": ("implementer", "reviewer"),
    "planner_executor": ("planner", "implementer", "producer"),
    "producer_critic": ("producer", "critic"),
    "execute_validate": ("implementer", "producer", "validator"),
    "duo_independent": ("explorer", "critic"),
    "discover_reproduce": ("explorer", "validator"),
    "evidence_arbitration": ("reviewer", "critic"),
    "reorientation": ("planner", "critic"),
    "closure": ("closer",),
}

# Presets deliberately separate orchestration/synthesis from bounded child work.
# Every value remains subject to the installed model catalog and validation mode.
PRESET_ROUTING: Final[dict[str, dict[str, dict[str, str | None]]]] = {
    "inherit": {
        "parent": {"model": None, "effort": None},
        **{role: {"model": None, "effort": None} for role in CHILD_ROLES},
    },
    "economy": {
        "parent": {"model": "gpt-5.6-terra", "effort": "medium"},
        "explorer": {"model": "gpt-5.6-luna", "effort": "low"},
        "bulk_worker": {"model": "gpt-5.6-luna", "effort": "low"},
        "planner": {"model": "gpt-5.6-terra", "effort": "medium"},
        "implementer": {"model": "gpt-5.6-terra", "effort": "medium"},
        "producer": {"model": "gpt-5.6-terra", "effort": "medium"},
        "reviewer": {"model": "gpt-5.6-terra", "effort": "high"},
        "validator": {"model": "gpt-5.6-luna", "effort": "medium"},
        "critic": {"model": "gpt-5.6-terra", "effort": "high"},
        "closer": {"model": "gpt-5.6-terra", "effort": "high"},
    },
    "balanced": {
        "parent": {"model": "gpt-5.6-sol", "effort": "high"},
        "explorer": {"model": "gpt-5.6-luna", "effort": "medium"},
        "bulk_worker": {"model": "gpt-5.6-luna", "effort": "low"},
        "planner": {"model": "gpt-5.6-sol", "effort": "high"},
        "implementer": {"model": "gpt-5.6-terra", "effort": "high"},
        "producer": {"model": "gpt-5.6-terra", "effort": "high"},
        "reviewer": {"model": "gpt-5.6-sol", "effort": "high"},
        "validator": {"model": "gpt-5.6-terra", "effort": "medium"},
        "critic": {"model": "gpt-5.6-sol", "effort": "high"},
        "closer": {"model": "gpt-5.6-sol", "effort": "high"},
    },
    "quality": {
        "parent": {"model": "gpt-5.6-sol", "effort": "max"},
        "explorer": {"model": "gpt-5.6-terra", "effort": "high"},
        "bulk_worker": {"model": "gpt-5.6-terra", "effort": "medium"},
        "planner": {"model": "gpt-5.6-sol", "effort": "high"},
        "implementer": {"model": "gpt-5.6-sol", "effort": "high"},
        "producer": {"model": "gpt-5.6-sol", "effort": "high"},
        "reviewer": {"model": "gpt-5.6-sol", "effort": "max"},
        "validator": {"model": "gpt-5.6-terra", "effort": "high"},
        "critic": {"model": "gpt-5.6-sol", "effort": "max"},
        "closer": {"model": "gpt-5.6-sol", "effort": "max"},
    },
    "custom": {
        "parent": {"model": None, "effort": None},
        **{role: {"model": None, "effort": None} for role in CHILD_ROLES},
    },
}

ROLE_MODEL_PREFERENCES: Final[dict[str, tuple[str, ...]]] = {
    "parent": ("gpt-5.6-sol", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna"),
    "explorer": ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6", "gpt-5.6-sol"),
    "bulk_worker": ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6", "gpt-5.6-sol"),
    "planner": ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6", "gpt-5.6-luna"),
    "implementer": ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6", "gpt-5.6-luna"),
    "producer": ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6", "gpt-5.6-luna"),
    "reviewer": ("gpt-5.6-sol", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna"),
    "validator": ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6"),
    "critic": ("gpt-5.6-sol", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna"),
    "closer": ("gpt-5.6-sol", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna"),
}


class RoutingError(ValueError):
    pass


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
        if role not in ALL_ROUTING_ROLES:
            raise RoutingError(
                f"Unknown model-routing role {raw_role!r}; use one of: "
                + ", ".join(ALL_ROUTING_ROLES)
            )
        if kind == "effort":
            output[role] = normalize_effort(raw_value)
        else:
            output[role] = normalize_model(raw_value)
    return output


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


def _parse_toml_value(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw in {"true", "false"}:
        return raw == "true"
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise RoutingError(f"Invalid quoted TOML value: {raw}") from exc
    if re.fullmatch(r"[-+]?\d+", raw):
        return int(raw)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)", raw):
        return float(raw)
    return raw


def _minimal_toml_load(text: str) -> dict[str, Any]:
    """Parse the small TOML subset emitted by JAM on Python 3.10."""

    root: dict[str, Any] = {}
    current = root
    for number, original in enumerate(text.splitlines(), start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section:
                raise RoutingError(f"Empty TOML section on line {number}.")
            current = root
            for part in section.split("."):
                key = part.strip()
                if not key:
                    raise RoutingError(f"Invalid TOML section on line {number}.")
                child = current.setdefault(key, {})
                if not isinstance(child, dict):
                    raise RoutingError(f"TOML section conflicts with a value on line {number}.")
                current = child
            continue
        if "=" not in line:
            raise RoutingError(f"Invalid TOML assignment on line {number}: {original}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise RoutingError(f"Empty TOML key on line {number}.")
        current[key] = _parse_toml_value(raw_value)
    return root


def _read_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return _minimal_toml_load(text)
    try:
        value = tomllib.loads(text)
    except Exception as exc:
        raise RoutingError(f"Invalid JAM routing configuration at {path}: {exc}") from exc
    return value if isinstance(value, dict) else {}


def _toml_string(value: str) -> str:
    # JSON quoted strings are valid TOML basic strings for these values.
    return json.dumps(value, ensure_ascii=False)


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
        if role == "parent":
            config["parent"]["model"] = value
        else:
            config["roles"][role]["model"] = value
    for role, value in efforts.items():
        if role == "parent":
            config["parent"]["effort"] = value
        else:
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


def build_requested_routing(
    *,
    policy: str = "balanced",
    validation: str = "fallback",
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
    if parent_model is not None:
        model_overrides["parent"] = normalize_model(parent_model)
    if parent_effort is not None:
        effort_overrides["parent"] = normalize_effort(parent_effort)

    base = PRESET_ROUTING[policy]
    parent = dict(base["parent"])
    roles: dict[str, dict[str, Any]] = {}
    if model_overrides.get("parent") is not None:
        parent["model"] = model_overrides["parent"]
    if effort_overrides.get("parent") is not None:
        parent["effort"] = effort_overrides["parent"]
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
                "model": model_overrides.get("parent"),
                "effort": effort_overrides.get("parent"),
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


def _supported_efforts(entry: dict[str, Any]) -> list[str]:
    raw = (
        entry.get("supportedReasoningEfforts")
        or entry.get("supported_reasoning_efforts")
        or []
    )
    efforts: list[str] = []
    for item in raw:
        value = item.get("reasoningEffort") if isinstance(item, dict) else item
        try:
            normalized = normalize_effort(value)
        except RoutingError:
            continue
        if normalized and normalized not in efforts:
            efforts.append(normalized)
    default = entry.get("defaultReasoningEffort") or entry.get(
        "default_reasoning_effort"
    )
    try:
        default_normalized = normalize_effort(default)
    except RoutingError:
        default_normalized = None
    if default_normalized and default_normalized not in efforts:
        efforts.append(default_normalized)
    return efforts


def normalize_catalog(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or raw.get("model") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        try:
            default_effort = normalize_effort(
                raw.get("defaultReasoningEffort")
                or raw.get("default_reasoning_effort")
            )
        except RoutingError:
            default_effort = None
        normalized.append(
            {
                "id": model_id,
                "model": str(raw.get("model") or model_id),
                "display_name": str(
                    raw.get("displayName") or raw.get("display_name") or model_id
                ),
                "hidden": bool(raw.get("hidden", False)),
                "is_default": bool(raw.get("isDefault") or raw.get("is_default")),
                "default_effort": default_effort,
                "supported_efforts": _supported_efforts(raw),
                "input_modalities": list(
                    raw.get("inputModalities")
                    or raw.get("input_modalities")
                    or ["text", "image"]
                ),
            }
        )
    return normalized


def _catalog_map(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in catalog:
        for candidate in (entry.get("id"), entry.get("model")):
            value = str(candidate or "").strip()
            if value:
                result[value] = entry
    return result


def _default_model(catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    visible = [entry for entry in catalog if not entry.get("hidden")]
    for entry in visible:
        if entry.get("is_default"):
            return entry
    if visible:
        return visible[0]
    return catalog[0] if catalog else None


def _fallback_model_for_role(
    role: str,
    catalog: list[dict[str, Any]],
    catalog_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for model_id in ROLE_MODEL_PREFERENCES.get(role, ()):
        if model_id in catalog_by_id and not catalog_by_id[model_id].get("hidden"):
            return catalog_by_id[model_id]
    return _default_model(catalog)


def _nearest_effort(
    requested: str, supported: list[str], default: str | None
) -> str | None:
    if requested in supported:
        return requested
    if not supported:
        return default
    requested_index = EFFORT_ORDER.index(requested)
    normalized_supported = [item for item in supported if item in EFFORT_ORDER]
    ranked = sorted(
        normalized_supported,
        key=lambda item: (
            # Prefer the nearest supported effort; on a tie prefer lower usage.
            abs(EFFORT_ORDER.index(item) - requested_index),
            EFFORT_ORDER.index(item) > requested_index,
            EFFORT_ORDER.index(item),
        ),
    )
    return ranked[0] if ranked else default


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
        "strategy_routes": requested.get("strategy_routes")
        or {
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


def model_catalog_snapshot(
    catalog_entries: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return normalize_catalog(catalog_entries or [])


def fetch_installed_model_catalog(
    *, include_hidden: bool = True
) -> list[dict[str, Any]]:
    """Read the current account/client model catalog through `codex app-server`."""

    from .appserver import AppServerClient  # Lazy import avoids prompt/appserver cycles.

    import tempfile

    state_home = jam_home_path()
    if state_home.exists():
        log_dir = state_home / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / "model-catalog.stderr.log"
        with AppServerClient(stderr_path=stderr_path) as client:
            return client.list_models(include_hidden=include_hidden)

    with tempfile.TemporaryDirectory(prefix="jam-model-catalog-") as temp_dir:
        stderr_path = Path(temp_dir) / "app-server.stderr.log"
        with AppServerClient(stderr_path=stderr_path) as client:
            return client.list_models(include_hidden=include_hidden)


def resolve_requested_with_installed_catalog(
    requested: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation = normalize_validation_mode(requested.get("validation"))
    if validation == "off":
        resolved = resolve_routing(requested, catalog_entries=[])
        return resolved, []
    try:
        raw_catalog = fetch_installed_model_catalog(include_hidden=True)
    except Exception as exc:
        resolved = resolve_routing(
            requested,
            catalog_entries=[],
            catalog_error=f"{type(exc).__name__}: {exc}",
        )
        return resolved, []
    snapshot = model_catalog_snapshot(raw_catalog)
    resolved = resolve_routing(requested, catalog_entries=raw_catalog)
    return resolved, snapshot


def render_agent_toml(
    role: str, entry: dict[str, Any], *, allow_nested_agents: bool = False
) -> str:
    if role not in CHILD_ROLES:
        raise RoutingError(f"Cannot render unknown child role: {role}")
    spec = ROLE_SPECS[role]
    agent_name = str(entry.get("agent") or ROLE_AGENT_NAMES[role])
    lines = [
        MANAGED_AGENT_MARKER,
        "# Generated by JAM Mode 0.3. Edit JAM routing settings instead of this file.",
        f"# role = {role}",
        f"name = {_toml_string(agent_name)}",
        f"description = {_toml_string(spec['description'])}",
    ]
    model = str(entry.get("model") or "").strip()
    effort = normalize_effort(entry.get("effort"))
    if model:
        lines.append(f"model = {_toml_string(model)}")
    if effort:
        lines.append(f"model_reasoning_effort = {_toml_string(effort)}")
    lines.append(f"sandbox_mode = {_toml_string(spec['sandbox'])}")
    instructions = spec["instructions"]
    if allow_nested_agents:
        instructions = instructions.replace("Do not spawn additional agents.", "")
        instructions = instructions.replace("Do not spawn agents.", "")
        instructions = instructions.rstrip() + """

Ultra nested delegation is explicitly enabled for this role. You may delegate at
most one read-only helper at a time, one generation deep, and only for a clearly
bounded part of the parent's assignment. Do not delegate writes, invoke JAM
campaign controls, broaden scope, or let a helper decide campaign continuation.
You remain responsible for validating and returning the combined result.
"""
    instructions = instructions.replace('"""', '\\"\\"\\"')
    lines.extend(
        [
            'developer_instructions = """',
            instructions,
            '"""',
            "",
        ]
    )
    return "\n".join(lines)


def managed_agent_paths(codex_home: Path | None = None) -> dict[str, Path]:
    base = (codex_home or codex_home_path()) / "agents"
    return {
        role: base / f"{ROLE_AGENT_NAMES[role]}.toml" for role in CHILD_ROLES
    }


def project_agent_collisions(workspace: str | Path) -> list[str]:
    agent_dir = Path(workspace).expanduser().resolve() / ".codex" / "agents"
    if not agent_dir.is_dir():
        return []
    collisions: list[str] = []
    for role, agent_name in ROLE_AGENT_NAMES.items():
        candidate = agent_dir / f"{agent_name}.toml"
        if candidate.exists():
            collisions.append(f"{role}: {candidate}")
    return collisions


def ensure_managed_agents(
    resolved_routing: dict[str, Any],
    *,
    codex_home: Path | None = None,
    workspace: str | Path | None = None,
) -> dict[str, str]:
    """Install/update JAM-prefixed custom agents without touching unrelated config."""

    if workspace is not None:
        collisions = project_agent_collisions(workspace)
        if collisions:
            raise RoutingError(
                "Project-scoped custom agents would override JAM's managed agents. "
                "Rename or remove these files before starting the campaign: "
                + "; ".join(collisions)
            )

    paths = managed_agent_paths(codex_home)
    output: dict[str, str] = {}
    for role, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_text(encoding="utf-8", errors="replace")
            if MANAGED_AGENT_MARKER not in existing:
                raise RoutingError(
                    f"Refusing to overwrite non-JAM custom agent file: {path}. "
                    "Rename it or choose a different Codex home."
                )
        entry = (resolved_routing.get("roles") or {}).get(role) or {
            "agent": ROLE_AGENT_NAMES[role],
            "model": None,
            "effort": None,
        }
        atomic_write(
            path,
            render_agent_toml(
                role,
                entry,
                allow_nested_agents=(
                    bool(resolved_routing.get("allow_child_ultra"))
                    and normalize_effort(entry.get("effort")) == "ultra"
                ),
            ),
        )
        output[role] = str(path)

    manifest_path = (codex_home or codex_home_path()) / "jam-mode" / "agents-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        manifest_path,
        json_dumps(
            {
                "schema_version": 1,
                "generated_at": utc_now(),
                "policy": resolved_routing.get("policy"),
                "validation": resolved_routing.get("validation"),
                "agents": output,
            },
            pretty=True,
        ),
    )
    return output


def inspect_managed_agents(codex_home: Path | None = None) -> dict[str, Any]:
    paths = managed_agent_paths(codex_home)
    agents: dict[str, Any] = {}
    for role, path in paths.items():
        exists = path.exists()
        managed = False
        if exists:
            try:
                managed = MANAGED_AGENT_MARKER in path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                managed = False
        agents[role] = {
            "agent": ROLE_AGENT_NAMES[role],
            "path": str(path),
            "exists": exists,
            "managed": managed,
        }
    return {
        "codex_home": str((codex_home or codex_home_path()).resolve()),
        "agents": agents,
        "ok": all(
            item["exists"] and item["managed"] for item in agents.values()
        ),
    }


def remove_managed_agents(codex_home: Path | None = None) -> list[str]:
    removed: list[str] = []
    for path in managed_agent_paths(codex_home).values():
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if MANAGED_AGENT_MARKER in text:
            path.unlink()
            removed.append(str(path))
    return removed


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
    routes = resolved.get("strategy_routes") or STRATEGY_AGENT_ROUTES
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
        elif strategy in {"parallel_explore", "map_reduce"}:
            description = f"one or more independent instances of {names[0]} within the concurrency limit"
        elif names:
            description = " → ".join(names)
        else:
            description = "parent only"
        lines.append(f"- {strategy}: {description}")
    lines.extend(
        [
            "Do not substitute Codex's unnamed default/worker/explorer agents for a routed JAM role unless the named agent is genuinely unavailable; record any substitution in the report.",
            "The parent thread remains the orchestrator and final synthesizer. Child agents must not decide campaign continuation or spawn nested agents.",
            "Never run jam_implementer and jam_producer concurrently. There is exactly one writer for a shared checkout.",
        ]
    )
    return "\n".join(lines)
