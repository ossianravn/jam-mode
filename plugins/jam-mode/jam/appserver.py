from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from .prompts import HANDOFF_SCHEMA
from .util import json_dumps


class AppServerError(RuntimeError):
    pass


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


def _codex_command() -> list[str]:
    executable = shutil.which("codex")
    if not executable:
        raise AppServerError(
            "The 'codex' executable is not on PATH. Install/update Codex CLI and "
            "make sure the plugin host can see it."
        )
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", executable, "app-server"]
    return [executable, "app-server"]


class AppServerClient:
    """Minimal synchronous JSONL client for ``codex app-server``."""

    def __init__(
        self,
        *,
        stderr_path: Path,
        environment: dict[str, str] | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        experimental_api: bool = False,
    ) -> None:
        self.stderr_path = stderr_path
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr: TextIO = self.stderr_path.open("a", encoding="utf-8")
        env = os.environ.copy()
        if environment:
            env.update(environment)
        try:
            self.process = subprocess.Popen(
                _codex_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            if self.process.stdin is None or self.process.stdout is None:
                raise AppServerError("Unable to open app-server stdio pipes.")
            self._inbox: queue.Queue[str | None] = queue.Queue()
            self._reader = threading.Thread(target=self._read_stdout, daemon=True)
            self._reader.start()
            self._next_id = 1
            self._event_callback = event_callback
            self._pending_notifications: list[dict[str, Any]] = []
            self._experimental_api = bool(experimental_api)
            self._initialize()
        except Exception:
            process = getattr(self, "process", None)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            self._stderr.close()
            raise

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self._inbox.put(line)
        finally:
            self._inbox.put(None)

    def _write(self, message: dict[str, Any]) -> None:
        if self.process.poll() is not None:
            raise AppServerError(
                f"codex app-server exited unexpectedly with code {self.process.returncode}. "
                f"See {self.stderr_path}."
            )
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _read_message(self, *, timeout: float) -> dict[str, Any]:
        try:
            line = self._inbox.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("Timed out waiting for codex app-server.") from exc
        if line is None:
            code = self.process.poll()
            raise AppServerError(
                f"codex app-server closed stdout (exit code {code}). See {self.stderr_path}."
            )
        try:
            message = json.loads(line)
        except ValueError as exc:
            raise AppServerError(f"Invalid JSON from app-server: {line[:500]!r}") from exc
        if self._event_callback:
            self._event_callback(message)
        return message

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        if request_id is None:
            return
        # Background JAM episodes cannot present interactive approval or input UI.
        # Approval policy is ``never``, so these are defensive fallbacks.
        if "requestApproval" in method:
            self._write({"id": request_id, "result": {"decision": "decline"}})
            return
        if method.endswith("requestUserInput"):
            self._write({"id": request_id, "result": {"answers": {}}})
            return
        if "elicitation/request" in method:
            self._write(
                {
                    "id": request_id,
                    "result": {"action": "cancel", "content": None},
                }
            )
            return
        if method == "currentTime/read":
            self._write(
                {
                    "id": request_id,
                    "result": {"currentTimeAt": int(time.time())},
                }
            )
            return
        self._write(
            {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"JAM controller does not implement server request {method}",
                },
            }
        )

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        self._write(message)
        deadline = time.monotonic() + timeout
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f"Timed out waiting for app-server response to {method}.")
            incoming = self._read_message(timeout=max(0.01, deadline - now))
            if incoming.get("id") == request_id and (
                "result" in incoming or "error" in incoming
            ):
                if "error" in incoming:
                    raise AppServerError(
                        f"app-server {method} failed: {json_dumps(incoming['error'], pretty=True)}"
                    )
                return incoming.get("result") or {}
            if incoming.get("id") is not None and incoming.get("method"):
                self._handle_server_request(incoming)
            else:
                self._pending_notifications.append(incoming)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def _initialize(self) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "jam_mode",
                    "title": "JAM Mode",
                    "version": "0.3.0",
                },
                "capabilities": {
                    "experimentalApi": self._experimental_api,
                    "optOutNotificationMethods": ["item/agentMessage/delta"],
                },
            },
            timeout=60,
        )
        self.notify("initialized", {})

    def list_models(
        self,
        *,
        include_hidden: bool = False,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the account/client model catalog using the stable ``model/list`` API."""

        data: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "limit": max(1, min(int(page_size), 500)),
                "includeHidden": bool(include_hidden),
            }
            if cursor:
                params["cursor"] = cursor
            result = self.request("model/list", params, timeout=120)
            page = result.get("data") or []
            if not isinstance(page, list):
                raise AppServerError(f"model/list returned invalid data: {result!r}")
            data.extend(item for item in page if isinstance(item, dict))
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise AppServerError("model/list returned a repeated pagination cursor.")
            seen_cursors.add(cursor)
        return data

    def start_thread(
        self,
        *,
        cwd: str,
        model: str | None,
        sandbox: str,
        name: str,
    ) -> str:
        sandbox_value = "workspaceWrite" if sandbox == "workspace-write" else "readOnly"
        params: dict[str, Any] = {
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": sandbox_value,
            "serviceName": "jam_mode",
        }
        if model:
            params["model"] = model
        result = self.request("thread/start", params, timeout=120)
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not thread_id:
            raise AppServerError(f"thread/start returned no thread id: {result!r}")
        try:
            self.request(
                "thread/name/set",
                {"threadId": thread_id, "name": name},
                timeout=30,
            )
        except AppServerError:
            # Naming is cosmetic and may differ across app-server versions.
            pass
        return str(thread_id)

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
        if sandbox == "workspace-write":
            sandbox_policy: dict[str, Any] = {
                "type": "workspaceWrite",
                "writableRoots": [cwd],
                "readOnlyAccess": {"type": "fullAccess"},
                "networkAccess": bool(allow_network),
            }
        else:
            sandbox_policy = {
                "type": "readOnly",
                "access": {"type": "fullAccess"},
            }
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandboxPolicy": sandbox_policy,
            "summary": "concise",
            "outputSchema": HANDOFF_SCHEMA,
        }
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
                if item.get("type") == "agentMessage" and method == "item/completed":
                    text = str(item.get("text") or "")
                    if text:
                        fallback_messages.append(text)
                        if item.get("phase") in {None, "final_answer"}:
                            final_messages.append(text)
                elif item.get("type") == "collabToolCall":
                    item_id = str(item.get("id") or f"collab-{len(agent_activity_order) + 1}")
                    if item_id not in agent_activity_by_id:
                        agent_activity_order.append(item_id)
                    record = dict(item)
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

    def close(self) -> None:
        try:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self._reader.join(timeout=2)
        try:
            if self.process.stdout and not self.process.stdout.closed:
                self.process.stdout.close()
        except OSError:
            pass
        try:
            self._stderr.close()
        except OSError:
            pass

    def __enter__(self) -> "AppServerClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


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
            experimental_api=False,
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
