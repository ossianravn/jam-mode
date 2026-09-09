"""Verify OpenCode child sessions against native parent task receipts."""
from __future__ import annotations

from .types import HarnessError


def _final(messages: list, session_id: str) -> tuple[str, dict]:
    assistants = [message for message in messages if (message.get("info") or {}).get("role") == "assistant"]
    if not assistants:
        raise HarnessError("OpenCode session has no assistant result.")
    message = assistants[-1]
    info = message["info"]
    if info.get("sessionID") != session_id or info.get("error") or info.get("finish") != "stop":
        raise HarnessError("OpenCode session lacks a successful terminal assistant result.")
    text = "\n".join(part["text"] for part in message.get("parts", [])
                     if part.get("type") == "text" and isinstance(part.get("text"), str)).strip()
    if not text or not (info.get("time") or {}).get("completed"):
        raise HarnessError("OpenCode terminal result is empty or lacks completion timing.")
    return text, info


def normalize(session_id: str, messages: list, children: list, child_messages: dict,
              requested: dict) -> tuple[str, list, list]:
    final_text, final = _final(messages, session_id)
    timeline, models = [], []
    by_id = {child["id"]: child for child in children if child.get("parentID") == session_id}
    seen = set()

    def emit(at: int, item: dict) -> None:
        timeline.append((at, {"method": "item/completed", "params": {
            "threadId": session_id, "item": item}}))

    def check_model(info: dict, role: str) -> None:
        model = f"{info.get('providerID')}/{info.get('modelID')}"
        expected_agent = "jam_parent" if role == "parent" else role
        if model != requested.get(role) or info.get("agent") != expected_agent:
            raise HarnessError(f"OpenCode actual model for {role} does not match the requested route.")
        models.append({"role": role, "model": model, "source": "opencode"})

    for message in messages:
        info = message.get("info") or {}
        if info.get("role") == "assistant":
            check_model(info, "parent")
        for part in message.get("parts", []):
            if part.get("type") != "tool" or part.get("tool") != "task":
                continue
            state = part.get("state") or {}
            metadata = state.get("metadata") or {}
            child_id = metadata.get("sessionId")
            if child_id not in by_id or state.get("status") != "completed":
                continue
            if child_id in seen or metadata.get("background"):
                raise HarnessError("OpenCode resumed/background child receipts are not supported by this evidence contract.")
            seen.add(child_id)
            role = (state.get("input") or {}).get("subagent_type")
            if role not in requested or role == "parent":
                raise HarnessError("OpenCode used an unconfigured child agent.")
            text, child_final = _final(child_messages.get(child_id, []), child_id)
            for child_message in child_messages[child_id]:
                child_info = child_message.get("info") or {}
                if child_info.get("role") == "assistant":
                    check_model(child_info, role)
            started = (by_id[child_id].get("time") or {}).get("created")
            completed = child_final["time"]["completed"]
            receipt = (state.get("time") or {}).get("end")
            if not all(isinstance(value, (int, float)) for value in (started, completed, receipt)):
                raise HarnessError("OpenCode child evidence lacks trustworthy lifecycle timestamps.")
            if not started <= completed <= receipt <= final["time"]["completed"]:
                raise HarnessError("OpenCode child completion was not delivered before the parent final.")
            common = {"type": "collabAgentToolCall", "status": "completed",
                      "senderThreadId": session_id, "receiverThreadIds": [child_id]}
            emit(started, {**common, "tool": "spawnAgent"})
            emit(receipt, {**common, "tool": "wait", "agentsStates": {
                child_id: {"status": "completed", "message": text}}})
    emit(final["time"]["completed"], {"type": "agentMessage", "phase": "final_answer", "text": final_text})
    # Equal millisecond timestamps cannot establish a spawn before a receipt.
    priority = {"wait": 0, "spawnAgent": 1}
    ordered = sorted(timeline, key=lambda entry: (entry[0], priority.get(entry[1]["params"]["item"].get("tool"), 2)))
    return final_text, [event for _, event in ordered], models
