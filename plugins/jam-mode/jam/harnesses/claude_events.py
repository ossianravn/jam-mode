"""Translate native Claude messages; parent prose never proves delegation."""
from __future__ import annotations

import json

from .types import HarnessError


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
    return ""


class ClaudeEvents:
    def __init__(self, roles: dict, strict: bool):
        self.roles = roles
        self.strict = strict
        self.session_id = ""
        self.events: list[dict] = []
        self.calls: dict[str, dict] = {}
        self.tasks: dict[str, str] = {}
        self.models: list[dict] = []
        self.final_text = ""
        self.result: dict | None = None

    def emit(self, item: dict) -> None:
        self.events.append({"method": "item/completed", "params": {
            "threadId": self.session_id, "item": item,
        }})

    def collaboration(self, tool: str, child: str, message: str = "") -> None:
        self.emit({"type": "collabAgentToolCall", "tool": tool,
                   "senderThreadId": self.session_id, "status": "completed",
                   "receiverThreadIds": [child], "agentsStates": {
                       child: {"status": "completed", "message": message}}})

    def expected_model(self, role: str) -> str | None:
        return (self.roles.get(role) or {}).get("model") or (self.roles.get("parent") or {}).get("model")

    def observe_model(self, model: object, role: str) -> None:
        if not isinstance(model, str) or not model:
            return
        requested = (self.roles.get(role) or {}).get("model")
        expected = self.expected_model(role)
        if self.strict and expected and model != expected:
            raise HarnessError(f"Claude model mismatch for {role}: expected {expected}, observed {model}.")
        self.models.append({"role": role, "model": model, "requested_model": requested, "expected_model": expected})

    def complete(self, call_id: str, success: bool) -> None:
        call = self.calls.get(call_id)
        if not call or call["done"]:
            return
        call["done"] = True
        if success and call["text"]:
            self.collaboration("wait", call_id, call["text"])

    def observe(self, event: dict) -> None:
        session = event.get("session_id")
        if session and not event.get("parent_tool_use_id"):
            if self.session_id and self.session_id != session:
                raise HarnessError("Claude stream changed its parent session identity.")
            self.session_id = session
        if self.result is not None:
            raise HarnessError("Claude emitted events after its terminal result.")
        kind = event.get("type")
        message = event.get("message") or {}
        parent = event.get("parent_tool_use_id")
        if kind == "assistant":
            if parent:
                call = self.calls.get(parent)
                if call:
                    self.observe_model(message.get("model"), call["role"])
                    call["model_observed"] = bool(message.get("model")) or call["model_observed"]
                    text = content_text(message.get("content"))
                    if text:
                        call["text"] = text
                return
            self.observe_model(message.get("model"), "parent")
            for block in message.get("content") or []:
                if block.get("type") != "tool_use" or block.get("name") not in {"Agent", "Task"}:
                    continue
                args = block.get("input") or {}
                role = next((key for key, value in self.roles.items()
                             if value.get("agent") == args.get("subagent_type")), None)
                if not role or role == "parent" or args.get("resume"):
                    raise HarnessError("Claude used an unmanaged or resumed child; fresh managed children are required.")
                call_id = block.get("id")
                if not call_id or call_id in self.calls:
                    raise HarnessError("Claude emitted a missing or repeated child invocation identity.")
                self.calls[call_id] = {"role": role, "text": "", "done": False, "model_observed": False,
                                       "synchronous": args.get("run_in_background") is False}
                self.collaboration("spawnAgent", call_id)
        elif kind == "user" and not parent:
            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = block.get("tool_use_id")
                call = self.calls.get(call_id)
                if call and call["synchronous"]:
                    self.complete(call_id, not block.get("is_error") and bool(content_text(block.get("content"))))
        elif kind == "system":
            if event.get("subtype") == "task_started" and event.get("tool_use_id") in self.calls:
                self.tasks[event["task_id"]] = event["tool_use_id"]
            elif event.get("subtype") == "task_notification":
                call_id = self.tasks.get(event.get("task_id"))
                if call_id and event.get("tool_use_id", call_id) == call_id:
                    self.complete(call_id, event.get("status") == "completed")
        elif kind == "result":
            self.result = event
            if event.get("subtype") != "success" or event.get("is_error"):
                raise HarnessError(f"Claude episode failed ({event.get('subtype', 'unknown')}).")
            payload = event.get("structured_output")
            if not isinstance(payload, dict) or not isinstance(payload.get("report_markdown"), str) or not isinstance(payload.get("handoff"), dict):
                raise HarnessError("Claude returned no valid structured report and handoff.")
            self.final_text = json.dumps(payload, ensure_ascii=False)
            self.emit({"type": "agentMessage", "phase": "final_answer", "text": self.final_text})

    def finish(self) -> None:
        if self.result is None or not self.session_id:
            raise HarnessError("Claude stream ended without a terminal result and session identity.")
        if self.strict:
            for call in self.calls.values():
                if self.expected_model(call["role"]) and not call["model_observed"]:
                    raise HarnessError(f"Claude did not expose the observed model for child {call['role']}.")
            observed = {item["role"] for item in self.models}
            required = {"parent"} | {call["role"] for call in self.calls.values()}
            for role in required:
                if self.expected_model(role) and role not in observed:
                    raise HarnessError(f"Claude did not expose the observed model for {role}.")
