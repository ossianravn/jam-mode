from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


COLLABORATION_ITEM_TYPES = {"collabAgentToolCall", "collabToolCall", "subAgentActivity"}


class CollaborationError(ValueError):
    pass


@dataclass
class ChildContribution:
    """Correlate a child's result, successful turn, and delivery to its parent."""

    final_turn: str | None = None
    succeeded: bool = False
    delivered: bool = False

    def observe(self, event: dict[str, Any]) -> None:
        params = event.get("params") or {}
        item = params.get("item") or {}
        method = event.get("method")
        if method == "turn/started":
            self.final_turn = None
            self.succeeded = self.delivered = False
        elif method == "item/completed" and item.get("type") == "agentMessage":
            if item.get("phase") in {None, "final_answer"}:
                text = item.get("text")
                self.final_turn = params.get("turnId") if isinstance(text, str) and text.strip() else None
                self.succeeded = self.delivered = False
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            self.succeeded = bool(
                self.final_turn and turn.get("id") == self.final_turn
                and turn.get("status") in {"completed", "complete"} and not turn.get("error")
            )
            self.delivered = False


def verify_contributions(
    events: Iterable[dict[str, Any]], *, thread_id: str, turn_id: str | None,
    final_text: str, strategy: str,
) -> None:
    """Require observed direct-child results before the parent's final answer.

    Accept legacy waits with completed results, or current child final messages
    corroborated by successful child turns and parent completion notifications.
    Participation and ordering are verified; reasoning quality remains a model duty.
    """
    spawned: set[str] = set()
    returned: set[str] = set()
    children: dict[str, ChildContribution] = {}
    early_wait = False
    final_evidence: tuple[int, bool] | None = None
    for event in events:
        params = event.get("params") or {}
        if event.get("method") == "turn/started":
            returned.discard(params.get("threadId"))
        child = children.get(params.get("threadId"))
        if child is not None:
            child.observe(event)
            continue
        if params.get("threadId") != thread_id:
            continue
        if turn_id and params.get("turnId") != turn_id:
            continue
        item = params.get("item") or {}
        if event.get("method") != "item/completed":
            continue
        if item.get("type") == "agentMessage":
            if item.get("text") == final_text and item.get("phase") in {None, "final_answer"}:
                modern_results = {key for key, value in children.items() if value.succeeded and value.delivered}
                final_evidence = (len(returned | modern_results), early_wait)
            continue
        if item.get("type") == "subAgentActivity":
            child_id = item.get("agentThreadId")
            if not isinstance(child_id, str) or not child_id or child_id == thread_id:
                continue
            kind = item.get("kind")
            if kind == "started":
                spawned.add(child_id)
                returned.discard(child_id)
                children[child_id] = ChildContribution()
            elif kind == "completed" and child_id in children:
                children[child_id].delivered = children[child_id].succeeded
            # Informational interactions do not start work. A child's next
            # turn/started event invalidates its previous contribution.
            continue
        if item.get("type") not in COLLABORATION_ITEM_TYPES:
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
        elif item.get("tool") in {"sendInput", "resumeAgent", "followupTask"}:
            returned.difference_update(receivers)
            for child_id in receivers & children.keys():
                children[child_id] = ChildContribution()
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
