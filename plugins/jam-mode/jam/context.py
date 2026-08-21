from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .handoff import normalize_handoff, public_handoff
from .handoff_fields import GENERATED_ID_ORIGIN, STATE_ID_ORIGIN_FIELD
from .memory import collect_memories
from .store import Store
from .util import json_dumps, truncate_text


def extract_event_transcript(events_path: str | None, *, max_chars: int = 50000) -> str:
    if not events_path:
        return ""
    path = Path(events_path)
    if not path.exists():
        return ""
    chunks: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            method = msg.get("method")
            params = msg.get("params") or {}
            if method == "item/completed":
                item = params.get("item") or {}
                item_type = item.get("type")
                if item_type == "userMessage":
                    content = item.get("content") or []
                    texts = [part.get("text", "") for part in content if part.get("type") == "text"]
                    if texts:
                        chunks.append("USER\n" + "\n".join(texts))
                elif item_type == "agentMessage":
                    text = item.get("text") or ""
                    phase = item.get("phase") or "message"
                    if text:
                        chunks.append(f"AGENT ({phase})\n{text}")
                elif item_type == "plan":
                    text = item.get("text") or ""
                    if text:
                        chunks.append("PLAN\n" + text)
                elif item_type in {"commandExecution", "fileChange", "mcpToolCall"}:
                    summary = {
                        key: item.get(key)
                        for key in ("type", "command", "status", "exitCode", "tool", "name")
                        if item.get(key) is not None
                    }
                    chunks.append("TOOL\n" + json_dumps(summary, pretty=True))
            elif method == "error":
                chunks.append("ERROR\n" + json_dumps(params, pretty=True))
    except OSError:
        return ""
    return truncate_text("\n\n".join(chunks), max_chars)


def build_campaign_ledger(store: Store, campaign_id: str) -> dict[str, Any]:
    """Build a task-neutral cumulative view from prior structured handoffs."""
    episodes = list(reversed(store.list_episodes(campaign_id, limit=30)))
    latest_state: dict[tuple[str, ...], dict[str, Any]] = {}
    completed_actions: list[str] = []
    decisions: list[dict[str, Any]] = []
    deliverables: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    blockers: list[str] = []
    risks: list[dict[str, Any]] = []
    open_items: list[str] = []
    artifacts: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    profile_history: list[dict[str, Any]] = []

    for episode in episodes:
        raw_handoff = episode.get("handoff")
        if not isinstance(raw_handoff, dict):
            continue
        handoff = normalize_handoff(raw_handoff, preserve_internal=True)
        episode_scope = str(episode.get("id") or episode.get("number"))
        for item in handoff.get("state_updates") or []:
            state_id = str(item["id"])
            if item.get(STATE_ID_ORIGIN_FIELD) == GENERATED_ID_ORIGIN:
                key = ("episode", episode_scope, state_id)
            else:
                key = ("campaign", state_id)
            latest_state.pop(key, None)
            latest_state[key] = {
                field: value
                for field, value in item.items()
                if field != STATE_ID_ORIGIN_FIELD
            }
        completed_actions.extend(handoff.get("completed_actions") or [])
        decisions.extend(handoff.get("decisions") or [])
        deliverables.extend(handoff.get("deliverables") or [])
        validation.extend(handoff.get("validation") or [])
        blockers.extend(handoff.get("blockers") or [])
        risks.extend(handoff.get("risks") or [])
        open_items.extend(handoff.get("open_items") or [])
        artifacts.extend(handoff.get("artifacts") or [])
        summaries.append(
            {
                "episode": episode.get("number"),
                "objective": episode.get("objective"),
                "status": handoff.get("status"),
                "summary": handoff.get("summary"),
                "task_profile": handoff.get("task_profile"),
                "strategy": handoff.get("strategy_used"),
                "progress_score": handoff.get("progress_score"),
            }
        )
        profile_history.append(
            {
                "episode": episode.get("number"),
                "task_profile": handoff.get("task_profile"),
                "reason": handoff.get("profile_reason"),
            }
        )

    state_updates = list(latest_state.values())[-240:]
    state_by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in state_updates:
        kind = str(item.get("kind") or "other")
        state_by_kind.setdefault(kind, []).append(item)

    return {
        "episode_summaries": summaries,
        "profile_history": profile_history,
        "state_updates": state_updates,
        "state_by_kind": state_by_kind,
        "completed_actions": completed_actions[-160:],
        "decisions": decisions[-100:],
        "deliverables": deliverables[-120:],
        "validation": validation[-120:],
        "blockers": blockers[-80:],
        "risks": risks[-80:],
        "open_items": open_items[-100:],
        "artifacts": artifacts[-120:],
    }


# Compatibility for integrations that imported the 0.1 helper directly.
def build_research_ledger(store: Store, campaign_id: str) -> dict[str, Any]:
    return build_campaign_ledger(store, campaign_id)


def build_context_pack(
    store: Store,
    campaign: dict[str, Any],
    current_objective: str,
) -> dict[str, Any]:
    last = store.last_episode(campaign["id"])
    raw_handoff = last.get("handoff") if last else None
    previous_handoff = (
        public_handoff(normalize_handoff(raw_handoff, preserve_internal=True))
        if isinstance(raw_handoff, dict)
        else None
    )
    previous_final = truncate_text(str(last.get("final_text") or ""), 30000) if last else ""
    previous_transcript = extract_event_transcript(last.get("events_path") if last else None)
    boundaries = campaign.get("operating_boundaries") or campaign.get("authorized_scope") or {}
    return {
        "campaign": {
            "id": campaign["id"],
            "name": campaign["name"],
            "objective": campaign["objective"],
            "workspace": campaign["workspace"],
            "task_profile": campaign.get("task_profile") or "adaptive",
            "operating_boundaries": boundaries,
            "success_criteria": campaign["success_criteria"],
            "user_guidance": campaign.get("user_guidance") or "",
        },
        "current_episode_objective": current_objective,
        "previous_episode": {
            "number": last.get("number") if last else None,
            "objective": last.get("objective") if last else None,
            "task_profile": (
                last.get("task_profile_used")
                or last.get("task_profile_hint")
                or (previous_handoff or {}).get("task_profile")
                if last
                else None
            ),
            "thread_id": last.get("thread_id") if last else None,
            "transcript_path": last.get("events_path") if last else None,
            "handoff": previous_handoff,
            "final_response": previous_final,
            "transcript_excerpt": previous_transcript,
        },
        "campaign_ledger": build_campaign_ledger(store, campaign["id"]),
        "subject_memories": collect_memories(campaign, current_objective),
    }
