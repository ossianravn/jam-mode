"""Translate Copilot SDK lifecycle evidence; never trust the parent's claims."""
from __future__ import annotations

from .types import HarnessError


class Evidence:
    def __init__(self, session_id: str, requested: dict[str, str | None], max_subagents: int = 2):
        self.session_id = session_id
        self.requested = requested
        self.children: dict[str, dict] = {}
        self.calls: dict[str, str] = {}
        self.events: list[dict] = []
        self.models: list[dict] = []
        self.final_text = ""
        self.idle = False
        self.parent_models: set[str] = set()
        self.max_subagents = max_subagents
        self.active: set[str] = set()

    def emit(self, item: dict) -> None:
        self.events.append({"method": "item/completed", "params": {
            "threadId": self.session_id, "item": item}})

    def collab(self, tool: str, child_id: str, **extra) -> None:
        self.emit({"type": "collabAgentToolCall", "tool": tool,
                   "senderThreadId": self.session_id, "receiverThreadIds": [child_id],
                   "status": "completed", **extra})

    def observe(self, event: dict) -> None:
        kind, data = event.get("type"), event.get("data") or {}
        agent = event.get("agentId")
        if kind in {"session.error", "abort"} and not agent:
            raise HarnessError("Copilot session failed or was aborted; inspect native events.")
        if kind == "subagent.started":
            call = data.get("toolCallId")
            if not agent or not call or data.get("parentId"):
                return
            role = data.get("agentName")
            if role not in self.requested:
                raise HarnessError(f"Copilot launched an unconfigured agent: {role}")
            self.active.add(agent)
            if len(self.active) > self.max_subagents:
                raise HarnessError("Copilot exceeded the campaign's active subagent limit.")
            self.calls = {key: value for key, value in self.calls.items() if value != agent}
            self.children[agent] = {"role": role, "text": "", "done": False, "call": call}
            self.calls[call] = agent
            self.collab("spawnAgent", agent)
            # Reusing an identity starts fresh work, invalidating prior evidence.
            self.collab("followupTask", agent)
        elif kind == "assistant.turn_start" and agent in self.children:
            self.children[agent].update(text="", done=False)
            self.collab("followupTask", agent)
            self.active.add(agent)
            if len(self.active) > self.max_subagents:
                raise HarnessError("Copilot exceeded the campaign's active subagent limit.")
        elif kind == "assistant.message":
            text = data.get("content")
            if not isinstance(text, str) or not text.strip() or data.get("toolRequests"):
                return
            if agent in self.children:
                self.children[agent]["text"] = text
            elif not agent:
                self.final_text = text
                self.emit({"type": "agentMessage", "phase": "final_answer", "text": text})
        elif kind == "subagent.completed" and agent in self.children:
            child = self.children[agent]
            if data.get("toolCallId") != child["call"]:
                return
            self.active.discard(agent)
            child["done"] = not data.get("cancelled", False)
            model = data.get("firstDispatchedModel") or data.get("model")
            self.check_model(child["role"], model)
        elif kind == "subagent.failed" and agent in self.children:
            if data.get("toolCallId") != self.children[agent]["call"]:
                return
            self.active.discard(agent)
            self.children[agent]["done"] = False
            self.collab("followupTask", agent)
        elif kind == "tool.execution_complete" and not agent:
            child_id = self.calls.get(data.get("toolCallId"))
            if child_id:
                child = self.children[child_id]
                if data.get("success") is True and child["done"] and child["text"]:
                    self.collab("wait", child_id, agentsStates={child_id: {
                        "status": "completed", "message": child["text"]}})
        elif kind == "assistant.usage":
            if data.get("isByok"):
                raise HarnessError("Copilot reported direct-provider execution, outside signed-in scope.")
            model = data.get("model")
            if agent in self.children:
                self.check_model(self.children[agent]["role"], model)
            elif not agent and not data.get("initiator"):
                self.check_model("parent", model)
                if model:
                    self.parent_models.add(model)
        elif kind == "session.idle" and not agent:
            self.idle = True

    def check_model(self, role: str, model: str | None) -> None:
        expected = self.requested.get(role)
        if expected and model != expected:
            raise HarnessError(f"Copilot model evidence for {role} does not match {expected}.")
        if model:
            self.models.append({"role": role, "model": model, "source": "copilot"})

    def finish(self) -> None:
        if not self.idle or not self.final_text:
            raise HarnessError("Copilot did not provide a final answer and session idle event.")
        if self.requested.get("parent") and not self.parent_models:
            raise HarnessError("Copilot did not report the actual parent model.")
