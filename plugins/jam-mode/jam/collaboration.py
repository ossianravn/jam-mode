from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class CollaborationError(ValueError):
    pass


def verify_contributions(
    events: Iterable[dict[str, Any]], *, thread_id: str, turn_id: str | None,
    final_text: str, strategy: str,
) -> None:
    """Require observed direct-child results before the parent's final answer.

    Tool completion is not agent completion. Only successful waits returning
    nonempty completed child messages count. This verifies participation and
    ordering; the substantive independence/quality of reasoning remains a model duty.
    """
    spawned: set[str] = set()
    returned: set[str] = set()
    early_wait = False
    final_evidence: tuple[int, bool] | None = None
    for event in events:
        params = event.get("params") or {}
        if params.get("threadId") != thread_id:
            continue
        if turn_id and params.get("turnId") != turn_id:
            continue
        item = params.get("item") or {}
        if event.get("method") != "item/completed":
            continue
        if item.get("type") == "agentMessage":
            if item.get("text") == final_text and item.get("phase") in {None, "final_answer"}:
                final_evidence = (len(returned), early_wait)
            continue
        if item.get("type") not in {"collabAgentToolCall", "collabToolCall"}:
            continue
        if item.get("senderThreadId") != thread_id or item.get("status") != "completed":
            continue
        receivers = set(item.get("receiverThreadIds") or []) - {thread_id}
        if item.get("tool") == "spawnAgent":
            spawned.update(receivers)
        elif item.get("tool") == "wait":
            if len(spawned) < 2:
                early_wait = True
            for child_id, state in (item.get("agentsStates") or {}).items():
                if child_id not in spawned or child_id not in receivers:
                    continue
                if state.get("status") == "completed":
                    if str(state.get("message") or "").strip():
                        returned.add(child_id)
                else:
                    returned.discard(child_id)
        elif item.get("tool") in {"sendInput", "resumeAgent", "sendMessage", "followupTask"}:
            returned.difference_update(receivers)
    if final_evidence is None or final_evidence[0] < 2:
        raise CollaborationError(
            "JAM requires completed contributions from at least two distinct direct child agents "
            "before the parent final answer. The recorded events do not establish this; "
            "the episode cannot be accepted as completed."
        )
    if strategy == "duo_independent" and final_evidence[1]:
        raise CollaborationError(
            "Duo requires both independent agents to be spawned before waiting for either. "
            "The recorded episode waited before starting the pair."
        )
