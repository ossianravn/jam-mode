from __future__ import annotations

from typing import Any

from .episode_strategy import validate_agent_budget
from .store import Store


RESUME_OPTIONS = {
    "guidance": {
        "type": "string",
        "description": "Optional new user guidance appended before replanning.",
    },
    "max_subagents": {
        "type": "integer", "minimum": 2, "maximum": 16,
        "description": "Optional replacement agent limit for this campaign; at least 2 for Duo.",
    },
}


def add_resume_parser(subparsers: Any) -> None:
    resume = subparsers.add_parser("resume", help="Resume with a fresh planning pass")
    resume.add_argument("campaign", nargs="?")
    resume.add_argument("--guidance", help=RESUME_OPTIONS["guidance"]["description"])
    resume.add_argument("--max-subagents", type=int, help=RESUME_OPTIONS["max_subagents"]["description"])


def prepare_resumption(
    store: Store, campaign: dict[str, Any], *, max_subagents: int | None,
    guidance: str | None,
) -> dict[str, Any]:
    """Validate before changing state; routing refresh then writes the updated charter.

    The caller must first verify that this campaign and the shared agents are idle.
    Existing history, episode counts, and unrelated limits remain intact.
    """
    candidate = dict(campaign)
    if max_subagents is not None:
        candidate["max_subagents"] = max_subagents
    validate_agent_budget(candidate)
    if max_subagents is not None:
        campaign = store.update_campaign(campaign["id"], max_subagents=int(max_subagents))
    if guidance:
        campaign = store.append_guidance(campaign["id"], guidance)
    return campaign
