from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .appserver_session import AppServerSessionMixin, permission_profile_for_sandbox
from .appserver_transport import AppServerError, AppServerTransport
from .collaboration import COLLABORATION_ITEM_TYPES
from .handoff_schema import HANDOFF_SCHEMA
from .util import json_dumps


@dataclass
class TurnResult:
    thread_id: str
    turn_id: str | None
    status: str
    final_text: str
    events_path: str
    stderr_path: str
    error: str | None = None
    agent_activity: list[dict[str, Any]] = field(default_factory=list)
    model_events: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, Any] | None = None

class AppServerClient(AppServerSessionMixin, AppServerTransport):
    @staticmethod
    def _agent_name_from_item(item: dict[str, Any]) -> str | None:
        for key in ("agent", "agentName", "agentType", "receiverAgent"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        prompt = str(item.get("prompt") or "")
        match = re.search(r"\b(jam_[a-z][a-z0-9_]*)\b", prompt)
        return match.group(1) if match else None

    def run_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        cwd: str,
        model: str | None,
        effort: str | None,
        sandbox: str,
        allow_network: bool,
        timeout_seconds: int,
    ) -> tuple[
        str | None,
        str,
        str,
        str | None,
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any] | None,
    ]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": cwd,
            "approvalPolicy": "never",
            "summary": "concise",
            "outputSchema": HANDOFF_SCHEMA,
        }
        if allow_network:
            if sandbox == "workspace-write":
                params["sandboxPolicy"] = {
                    "type": "workspaceWrite",
                    "writableRoots": [cwd],
                    "networkAccess": True,
                }
            else:
                params["sandboxPolicy"] = {
                    "type": "readOnly",
                    "networkAccess": True,
                }
        else:
            params["permissions"] = permission_profile_for_sandbox(sandbox)
        if model:
            params["model"] = model
        if effort:
            params["effort"] = effort
        try:
            result = self.request("turn/start", params, timeout=120)
        except AppServerError as exc:
            # Older app-server builds may reject outputSchema. Retry the not-yet-
            # started turn without it, while retaining the prompt's JSON contract.
            if "outputSchema" not in str(exc):
                raise
            params.pop("outputSchema", None)
            result = self.request("turn/start", params, timeout=120)

        turn = result.get("turn") or {}
        turn_id = turn.get("id")
        final_messages: list[str] = []
        fallback_messages: list[str] = []
        turn_status = str(turn.get("status") or "inProgress")
        turn_error: str | None = None
        agent_activity_by_id: dict[str, dict[str, Any]] = {}
        agent_activity_order: list[str] = []
        model_events: list[dict[str, Any]] = []
        token_usage: dict[str, Any] | None = None

        pending = list(self._pending_notifications)
        self._pending_notifications.clear()
        deadline = time.monotonic() + timeout_seconds
        while True:
            if pending:
                message = pending.pop(0)
            else:
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for Codex turn {turn_id or '<pending>'} to complete."
                    )
                message = self._read_message(timeout=max(0.01, deadline - now))

            if message.get("id") is not None and message.get("method"):
                self._handle_server_request(message)
                continue

            method = message.get("method")
            event_params = message.get("params") or {}
            if method in {"item/started", "item/completed"}:
                item = event_params.get("item") or {}
                if item.get("type") == "agentMessage" and method == "item/completed" and event_params.get("threadId") == thread_id:
                    text = str(item.get("text") or "")
                    if text:
                        fallback_messages.append(text)
                        if item.get("phase") in {None, "final_answer"}:
                            final_messages.append(text)
                elif item.get("type") in COLLABORATION_ITEM_TYPES:
                    item_id = str(item.get("id") or f"collab-{len(agent_activity_order) + 1}")
                    if item_id not in agent_activity_by_id:
                        agent_activity_order.append(item_id)
                    record = dict(item)
                    record["threadId"] = event_params.get("threadId")
                    record["turnId"] = event_params.get("turnId")
                    record["event"] = "completed" if method == "item/completed" else "started"
                    record["agent_name"] = self._agent_name_from_item(item)
                    agent_activity_by_id[item_id] = record
            elif method in {"model/rerouted", "model/verification", "model/safetyBuffering/updated"}:
                model_events.append({"method": method, **dict(event_params)})
            elif method == "thread/tokenUsage/updated":
                token_usage = dict(event_params)
            elif method == "error":
                error_payload = event_params.get("error") or event_params
                turn_error = json_dumps(error_payload, pretty=True)
            elif method == "turn/completed":
                completed_turn = event_params.get("turn") or event_params
                if turn_id and completed_turn.get("id") not in {None, turn_id}:
                    continue
                turn_status = str(completed_turn.get("status") or "completed")
                if completed_turn.get("error"):
                    turn_error = json_dumps(completed_turn.get("error"), pretty=True)
                break

        final_text = (
            final_messages[-1]
            if final_messages
            else (fallback_messages[-1] if fallback_messages else "")
        )
        agent_activity = [agent_activity_by_id[key] for key in agent_activity_order]
        return (
            str(turn_id) if turn_id else None,
            turn_status,
            final_text,
            turn_error,
            agent_activity,
            model_events,
            token_usage,
        )


def run_episode_turn(
    *,
    campaign: dict[str, Any],
    episode: dict[str, Any],
    prompt: str,
    events_path: Path,
    stderr_path: Path,
    timeout_seconds: int = 4 * 60 * 60,
) -> TurnResult:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event_file = events_path.open("a", encoding="utf-8")

    def log_event(message: dict[str, Any]) -> None:
        event_file.write(json.dumps(message, ensure_ascii=False) + "\n")
        event_file.flush()

    try:
        with AppServerClient(
            stderr_path=stderr_path,
            environment={
                "JAM_CHILD_SESSION": "1",
                "JAM_CONTROLLER_CAMPAIGN_ID": campaign["id"],
            },
            event_callback=log_event,
            experimental_api=True,
        ) as client:
            thread_id = client.start_thread(
                cwd=campaign["workspace"],
                model=campaign.get("model"),
                sandbox=campaign.get("sandbox", "read-only"),
                name=f"JAM · {campaign['name']} · Episode {episode['number']}",
            )
            (
                turn_id,
                status,
                final_text,
                error,
                agent_activity,
                model_events,
                token_usage,
            ) = client.run_turn(
                thread_id=thread_id,
                prompt=prompt,
                cwd=campaign["workspace"],
                model=campaign.get("model"),
                effort=campaign.get("effort"),
                sandbox=campaign.get("sandbox", "read-only"),
                allow_network=bool(campaign.get("allow_network")),
                timeout_seconds=timeout_seconds,
            )
            return TurnResult(
                thread_id=thread_id,
                turn_id=turn_id,
                status=status,
                final_text=final_text,
                events_path=str(events_path),
                stderr_path=str(stderr_path),
                error=error,
                agent_activity=agent_activity,
                model_events=model_events,
                token_usage=token_usage,
            )
    finally:
        event_file.close()
