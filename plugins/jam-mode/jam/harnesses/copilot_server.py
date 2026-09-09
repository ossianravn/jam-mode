"""Bounded stdio JSON-RPC transport for Copilot's native SDK server."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path

from .process_tree import launch, stop
from .types import HarnessError


class Server:
    def __init__(self, executable: str, request, environment: dict, on_event):
        self.request = request
        self.on_event = on_event
        self.deadline = time.monotonic() + request.timeout_seconds
        self.incoming = queue.Queue(maxsize=256)
        self.counter = 0
        self.responses: dict[int, dict] = {}
        self.session_id = None
        self.writer = None
        self.closed = threading.Event()
        self.stderr = request.stderr_path.open("wb")
        self.raw = request.events_path.with_suffix(".native.jsonl").open("w", encoding="utf-8")
        try:
            self.process = launch(
                [executable, "--headless", "--stdio", "--no-auto-update"],
                cwd=request.campaign["workspace"], env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            )
        except OSError as exc:
            self.stderr.close()
            self.raw.close()
            raise HarnessError("Could not start Copilot SDK server.") from exc
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        try:
            while True:
                length = None
                while True:
                    line = self.process.stdout.readline(8193)
                    if not line:
                        raise EOFError("Copilot closed its protocol stream")
                    if len(line) > 8192:
                        raise ValueError("Copilot header exceeds its size limit")
                    if line in {b"\r\n", b"\n"}:
                        break
                    key, value = line.decode("ascii").split(":", 1)
                    if key.lower() == "content-length":
                        length = int(value.strip())
                if length is None or not 0 < length <= 16 * 1024 * 1024:
                    raise ValueError("Invalid Copilot frame length")
                payload = self.process.stdout.read(length)
                if len(payload) != length:
                    raise EOFError("Incomplete Copilot frame")
                value = json.loads(payload)
                if not isinstance(value, dict):
                    raise ValueError("Copilot frame is not an object")
                self._put(value)
        except (OSError, EOFError, ValueError) as exc:
            self._put(exc)
        finally:
            self.process.stdout.close()

    def _put(self, value) -> None:
        while not self.closed.is_set():
            try:
                self.incoming.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def send(self, message: dict) -> None:
        data = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
        completed = threading.Event()
        errors = []
        def write():
            try:
                self.process.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                errors.append(exc)
            finally:
                completed.set()
        self.writer = threading.Thread(target=write, daemon=True)
        self.writer.start()
        if not completed.wait(max(0, self.deadline - time.monotonic())):
            raise HarnessError("Copilot protocol write exceeded the episode deadline.")
        if errors:
            raise HarnessError("Copilot protocol connection closed.") from errors[0]

    def request_rpc(self, method: str, params: dict) -> dict:
        self.counter += 1
        ident = self.counter
        self.send({"id": ident, "method": method, "params": params})
        while ident not in self.responses:
            self.pump()
        response = self.responses.pop(ident)
        if "error" in response:
            raise HarnessError(f"Copilot rejected {method}; inspect native diagnostics.")
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def pump(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError("Copilot episode deadline exceeded.")
        try:
            message = self.incoming.get(timeout=remaining)
        except queue.Empty as exc:
            raise HarnessError("Copilot episode deadline exceeded.") from exc
        if isinstance(message, Exception):
            raise HarnessError("Copilot returned an incomplete protocol stream.") from message
        if "method" not in message:
            self.responses[message.get("id")] = message
            return
        if message["method"] == "session.event":
            params = message.get("params") or {}
            if params.get("sessionId") != self.session_id:
                return
            event = params.get("event") or {}
            self.raw.write(json.dumps(event) + "\n")
            self.raw.flush()
            if event.get("type") == "permission.requested":
                data = event.get("data") or {}
                result = self.permission(data.get("permissionRequest") or {})
                self.counter += 1
                self.send({"id": self.counter,
                           "method": "session.permissions.handlePendingPermissionRequest",
                           "params": {"sessionId": self.session_id,
                                      "requestId": data.get("requestId"), "result": result}})
            self.on_event(event)
        elif message["method"] == "hooks.invoke" and "id" in message:
            params = message.get("params") or {}
            value = params.get("input") or {}
            arguments = value.get("toolArgs") or {}
            output = {}
            if (params.get("hookType") == "preToolUse" and value.get("toolName") == "task"
                    and (not isinstance(arguments, dict) or arguments.get("mode", "sync") != "sync")):
                output = {"permissionDecision": "deny", "permissionDecisionReason": "JAM requires synchronous task receipts."}
            self.send({"id": message["id"], "result": {"output": output}})
        elif "id" in message:
            self.send({"id": message["id"], "error": {
                "code": -32601, "message": "JAM does not authorize this callback"}})

    def permission(self, permission: dict) -> dict:
        kind = permission.get("kind")
        allowed = kind == "read" or (
            kind == "write" and self.request.campaign.get("sandbox") == "workspace-write")
        allowed = allowed and not permission.get("managedApprovalRequired") and not permission.get("requestSandboxBypass")
        path = permission.get("path") or permission.get("fileName")
        if allowed and isinstance(path, str):
            workspace = Path(self.request.campaign["workspace"]).resolve()
            target = Path(path)
            target = (workspace / target).resolve() if not target.is_absolute() else target.resolve()
            allowed = target == workspace or workspace in target.parents
        else:
            allowed = False
        return {"kind": "approved" if allowed else "denied-no-approval-rule-and-could-not-request-from-user"}

    def close(self) -> None:
        self.closed.set()
        try:
            stop(self.process)
        finally:
            if self.writer is not None:
                self.writer.join(timeout=0.2)
            self.reader.join(timeout=0.2)
            if self.writer is None or not self.writer.is_alive():
                self.process.stdin.close()
            for stream in (self.stderr, self.raw):
                stream.close()
