from __future__ import annotations

from typing import Any

from jam.service import get_status


def _public_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "name",
        "objective",
        "task_profile",
        "workspace",
        "harness",
        "operating_boundaries",
        "success_criteria",
        "status",
        "enabled",
        "stop_after_current",
        "termination_requested",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "active_episode_id",
        "last_thread_id",
        "sandbox",
        "allow_network",
        "max_episodes",
        "max_elapsed_minutes",
        "continuation_threshold",
        "max_subagents",
        "model",
        "effort",
        "model_policy",
        "model_validation",
        "allow_child_ultra",
        "allow_parent_ultra",
        "requested_routing",
        "resolved_routing",
        "routing_warnings",
        "episode_count",
        "last_error",
    )
    return {key: campaign.get(key) for key in fields}


def _public_episode(episode: dict[str, Any] | None) -> dict[str, Any] | None:
    if not episode:
        return None
    handoff = episode.get("handoff") or {}
    return {
        "id": episode.get("id"),
        "number": episode.get("number"),
        "objective": episode.get("objective"),
        "task_profile": (
            episode.get("task_profile_used")
            or episode.get("task_profile_hint")
            or handoff.get("task_profile")
        ),
        "strategy": episode.get("strategy_used") or episode.get("strategy_hint"),
        "status": episode.get("status"),
        "turn_status": episode.get("turn_status"),
        "thread_id": episode.get("thread_id"),
        "started_at": episode.get("started_at"),
        "ended_at": episode.get("ended_at"),
        "report_path": episode.get("final_path"),
        "handoff_path": episode.get("handoff_path"),
        "summary": handoff.get("summary"),
        "progress_score": handoff.get("progress_score"),
        "needs_user_input": handoff.get("needs_user_input"),
        "user_question": handoff.get("user_question"),
        "next_options": handoff.get("next_options") or [],
        "routing_snapshot": episode.get("routing_snapshot") or {},
        "agent_activity": episode.get("agent_activity") or [],
        "model_events": episode.get("model_events") or [],
        "token_usage": episode.get("token_usage"),
        "error": episode.get("error"),
    }


def _status_payload(identifier: str | None) -> dict[str, Any]:
    result = get_status(identifier)
    return {
        "campaign": _public_campaign(result["campaign"]),
        "controller_alive": result["controller_alive"],
        "last_episode": _public_episode(result.get("last_episode")),
        "episodes": [_public_episode(item) for item in result.get("episodes", [])[:20]],
        "campaign_directory": result["campaign_directory"],
    }


def _campaign_message(campaign: dict[str, Any], message: str = "") -> dict[str, Any]:
    return {"campaign": _public_campaign(campaign), "message": message}
