from __future__ import annotations

from typing import Final


TASK_PROFILES: Final[tuple[str, ...]] = (
    "adaptive",
    "general",
    "research",
    "security_research",
    "engineering",
    "review",
    "documentation",
    "planning",
    "data",
    "operations",
    "content",
    "mixed",
)

# Profiles an episode may report after inspecting the actual work. ``adaptive``
# remains valid because an episode can genuinely span several profiles, but
# ``mixed`` is preferred once that is known.
EPISODE_TASK_PROFILES: Final[tuple[str, ...]] = TASK_PROFILES

TASK_PROFILE_DESCRIPTIONS: Final[dict[str, str]] = {
    "adaptive": "Select or change the profile after reviewing the current objective and campaign state.",
    "general": "A bounded task that does not need a more specialized contract.",
    "research": "Investigate questions, compare explanations, and build supportable conclusions.",
    "security_research": "Authorized security investigation or validation under explicit target and action boundaries.",
    "engineering": "Create, modify, refactor, migrate, or repair code, configuration, tests, or tooling.",
    "review": "Audit or critique an existing artifact and produce prioritized findings or approval evidence.",
    "documentation": "Plan, draft, revise, or verify technical or user-facing documentation.",
    "planning": "Develop decisions, designs, milestones, dependencies, or an executable project plan.",
    "data": "Inspect, transform, validate, analyze, or report on structured or unstructured data.",
    "operations": "Perform or prepare bounded operational work with explicit verification and rollback/approval handling.",
    "content": "Produce or refine prose, structured content, creative material, or communication deliverables.",
    "mixed": "A campaign or episode that intentionally combines multiple task profiles.",
}


STRATEGIES: Final[tuple[str, ...]] = (
    "duo_independent",
    "parallel_explore",
    "critique_synthesize",
    "map_reduce",
    "builder_reviewer",
    "planner_executor",
    "producer_critic",
    "execute_validate",
    "discover_reproduce",
    "evidence_arbitration",
    "reorientation",
    "closure",
)

STRATEGY_DESCRIPTIONS: Final[dict[str, str]] = {
    "parallel_explore": "Independent agents explore alternatives or facets before the parent synthesizes.",
    "critique_synthesize": "One or more proposals are challenged, compared, and consolidated into a stronger result.",
    "map_reduce": "Separable work is distributed to specialists and then aggregated.",
    "builder_reviewer": "Exactly one writer creates or changes an artifact, followed by independent review.",
    "planner_executor": "A planning pass defines the work before one executor performs the bounded plan.",
    "producer_critic": "A producer creates a draft or deliverable and a critic improves or verifies it.",
    "execute_validate": "Perform a deterministic action, then independently validate its outcome.",
    "duo_independent": "Default: two independent investigator-and-skeptic analyses followed by parent synthesis.",
    "discover_reproduce": "Legacy/specialized discoverer-and-reproducer workflow for independently validating a claim.",
    "evidence_arbitration": "Conflicting observations or recommendations are independently audited and reconciled.",
    "reorientation": "Repeated low progress or stale assumptions require a materially different direction.",
    "closure": "Consolidate final deliverables, limitations, and completion evidence without speculative continuation.",
}


STATE_KINDS: Final[tuple[str, ...]] = (
    "finding",
    "claim",
    "hypothesis",
    "assumption",
    "decision",
    "requirement",
    "acceptance_criterion",
    "change",
    "test",
    "review_finding",
    "milestone",
    "dependency",
    "input",
    "transformation",
    "quality_check",
    "output",
    "metric",
    "action",
    "observation",
    "rollback",
    "draft",
    "feedback",
    "risk",
    "blocker",
    "open_item",
    "dead_end",
    "other",
)

STATE_STATUSES: Final[tuple[str, ...]] = (
    "new",
    "active",
    "in_progress",
    "complete",
    "validated",
    "rejected",
    "blocked",
    "superseded",
    "deferred",
    "not_applicable",
)

CONFIDENCE_LEVELS: Final[tuple[str, ...]] = (
    "low",
    "medium",
    "high",
    "not_applicable",
)


def normalize_task_profile(value: object, *, default: str = "general") -> str:
    profile = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "security": "security_research",
        "securityresearch": "security_research",
        "software": "engineering",
        "coding": "engineering",
        "docs": "documentation",
        "writing": "content",
        "creative": "content",
        "analysis": "research",
        "auto": "adaptive",
    }
    profile = aliases.get(profile, profile)
    return profile if profile in TASK_PROFILES else default


def normalize_strategy(value: object, *, default: str = "duo_independent") -> str:
    strategy = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "duo": "duo_independent",
        "parallel": "parallel_explore",
        "builderreviewer": "builder_reviewer",
        "producercritic": "producer_critic",
        "executevalidate": "execute_validate",
        "plannerexecutor": "planner_executor",
    }
    strategy = aliases.get(strategy, strategy)
    return strategy if strategy in STRATEGIES else default
