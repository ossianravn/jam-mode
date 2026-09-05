from __future__ import annotations

from typing import Final


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
        "parent": {"model": "gpt-6-astra", "effort": "medium"},
        "explorer": {"model": "gpt-6-astra", "effort": "low"},
        "bulk_worker": {"model": "gpt-6-astra", "effort": "low"},
        "planner": {"model": "gpt-6-astra", "effort": "medium"},
        "implementer": {"model": "gpt-6-astra", "effort": "medium"},
        "producer": {"model": "gpt-6-astra", "effort": "medium"},
        "reviewer": {"model": "gpt-6-astra", "effort": "high"},
        "validator": {"model": "gpt-6-astra", "effort": "medium"},
        "critic": {"model": "gpt-6-astra", "effort": "high"},
        "closer": {"model": "gpt-6-astra", "effort": "high"},
    },
    "balanced": {
        "parent": {"model": "gpt-6-astra", "effort": "high"},
        "explorer": {"model": "gpt-6-astra", "effort": "medium"},
        "bulk_worker": {"model": "gpt-6-astra", "effort": "low"},
        "planner": {"model": "gpt-6-astra", "effort": "high"},
        "implementer": {"model": "gpt-6-astra", "effort": "high"},
        "producer": {"model": "gpt-6-astra", "effort": "high"},
        "reviewer": {"model": "gpt-6-astra", "effort": "high"},
        "validator": {"model": "gpt-6-astra", "effort": "medium"},
        "critic": {"model": "gpt-6-astra", "effort": "high"},
        "closer": {"model": "gpt-6-astra", "effort": "high"},
    },
    "quality": {
        "parent": {"model": "gpt-6-astra", "effort": "max"},
        "explorer": {"model": "gpt-6-astra", "effort": "high"},
        "bulk_worker": {"model": "gpt-6-astra", "effort": "medium"},
        "planner": {"model": "gpt-6-astra", "effort": "high"},
        "implementer": {"model": "gpt-6-astra", "effort": "high"},
        "producer": {"model": "gpt-6-astra", "effort": "high"},
        "reviewer": {"model": "gpt-6-astra", "effort": "max"},
        "validator": {"model": "gpt-6-astra", "effort": "high"},
        "critic": {"model": "gpt-6-astra", "effort": "max"},
        "closer": {"model": "gpt-6-astra", "effort": "max"},
    },
    "custom": {
        "parent": {"model": None, "effort": None},
        **{role: {"model": None, "effort": None} for role in CHILD_ROLES},
    },
}

ROLE_MODEL_PREFERENCES: Final[dict[str, tuple[str, ...]]] = {
    role: ("gpt-6-astra",) for role in ("parent", *CHILD_ROLES)
}


class RoutingError(ValueError):
    pass
