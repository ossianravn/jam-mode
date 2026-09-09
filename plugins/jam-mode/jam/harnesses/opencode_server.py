"""Local authenticated OpenCode HTTP server with a single episode deadline."""
from __future__ import annotations

import base64
import json
import queue
import re
import secrets
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .process_tree import launch, stop
from .types import HarnessError


class Server:
    def __init__(self, executable: str, request, environment: dict):
        self.deadline = time.monotonic() + request.timeout_seconds
        self.stderr = request.stderr_path.open("wb")
        self.raw = request.events_path.with_suffix(".native.jsonl").open("w", encoding="utf-8")
        password = secrets.token_urlsafe(32)
        self.authorization = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()
        self.http = build_opener(ProxyHandler({}))
        self.incoming = queue.Queue(maxsize=64)
        self.events = queue.Queue(maxsize=256)
        self.closed = threading.Event()
        self.environment = {**environment, "OPENCODE_SERVER_PASSWORD": password}
        try:
            self.process = launch(
                [executable, "serve", "--hostname", "127.0.0.1", "--port", "0"],
                cwd=request.campaign["workspace"], env=self.environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=self.stderr,
            )
        except OSError as exc:
            self.raw.close()
            self.stderr.close()
            raise HarnessError("Could not start OpenCode server.") from exc
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.url = self._ready()
        except Exception:
            self.close()
            raise

    def _read(self) -> None:
        try:
            while line := self.process.stdout.readline(8192):
                self._put(self.incoming, line.decode("utf-8", errors="replace"))
        finally:
            self.process.stdout.close()
            self._put(self.incoming, None)

    def _put(self, target, value) -> None:
        while not self.closed.is_set():
            try:
                target.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def _ready(self) -> str:
        until = min(self.deadline, time.monotonic() + 15)
        while time.monotonic() < until:
            try:
                line = self.incoming.get(timeout=max(0.01, until - time.monotonic()))
            except queue.Empty as exc:
                raise HarnessError("OpenCode server did not become ready before its startup deadline.") from exc
            if line is None:
                raise HarnessError("OpenCode server exited before announcing its local address.")
            match = re.search(r"opencode server listening on (http://127\.0\.0\.1:\d+)", line)
            if match:
                return match.group(1)
        raise HarnessError("OpenCode server startup deadline exceeded.")

    def call(self, method: str, path: str, payload=None, *, record: bool = True):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError("OpenCode episode deadline exceeded.")
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.url + path, data=body, method=method,
                          headers={"Authorization": self.authorization, "Content-Type": "application/json"})
        completed, values, errors = threading.Event(), [], []
        def receive():
            try:
                with self.http.open(request, timeout=remaining) as response:
                    content = response.read(32 * 1024 * 1024 + 1)
                    if len(content) > 32 * 1024 * 1024:
                        raise ValueError("OpenCode response exceeds 32 MiB")
                    values.append(json.loads(content) if content else None)
            except (OSError, ValueError, HTTPError, URLError) as exc:
                errors.append(exc)
            finally:
                completed.set()
        threading.Thread(target=receive, daemon=True).start()
        if not completed.wait(max(0, self.deadline - time.monotonic())):
            raise HarnessError("OpenCode HTTP response exceeded the episode deadline.")
        if errors:
            raise HarnessError(f"OpenCode {method} {path} failed; inspect its stderr diagnostics.") from errors[0]
        result = values[0]
        if record:
            self.raw.write(json.dumps({"method": method, "path": path, "result": result}) + "\n")
            self.raw.flush()
        return result

    def subscribe(self) -> None:
        ready = threading.Event()
        errors = []
        def read():
            try:
                request = Request(self.url + "/event", headers={"Authorization": self.authorization})
                with self.http.open(request, timeout=max(0.01, self.deadline - time.monotonic())) as response:
                    ready.set()
                    while True:
                        line = response.readline(1024 * 1024 + 1)
                        if not line:
                            raise EOFError("OpenCode event stream closed")
                        if len(line) > 1024 * 1024:
                            raise ValueError("OpenCode event exceeds size limit")
                        if line.startswith(b"data:"):
                            self._put(self.events, json.loads(line[5:]))
            except (OSError, ValueError, EOFError) as exc:
                errors.append(exc)
                self._put(self.events, exc)
            finally:
                ready.set()
        threading.Thread(target=read, daemon=True).start()
        if not ready.wait(max(0, self.deadline - time.monotonic())):
            raise HarnessError("OpenCode event subscription exceeded the episode deadline.")
        if errors:
            raise HarnessError("OpenCode event subscription failed before execution.") from errors[0]

    def wait_session(self, session_id: str, max_subagents: int) -> None:
        children, active = set(), set()
        terminal = False
        while True:
            try:
                event = self.events.get(timeout=max(0.001, self.deadline - time.monotonic()))
            except queue.Empty as exc:
                raise HarnessError("OpenCode episode deadline exceeded.") from exc
            if isinstance(event, Exception):
                raise HarnessError("OpenCode event stream failed.") from event
            if not isinstance(event, dict):
                raise HarnessError("OpenCode emitted an invalid event.")
            self.raw.write(json.dumps({"event": event}) + "\n")
            self.raw.flush()
            kind, properties = event.get("type"), event.get("properties") or {}
            info = properties.get("info") or {}
            if kind == "session.created" and info.get("parentID") == session_id:
                children.add(info["id"])
                active.add(info["id"])
            elif kind == "session.status" and properties.get("sessionID") in children:
                child = properties["sessionID"]
                if (properties.get("status") or {}).get("type") == "idle":
                    active.discard(child)
                else:
                    active.add(child)
            elif kind == "message.updated" and info.get("sessionID") == session_id:
                terminal = info.get("role") == "assistant" and info.get("finish") == "stop" and bool((info.get("time") or {}).get("completed"))
                if info.get("error"):
                    raise HarnessError("OpenCode parent failed; inspect native events.")
            elif kind == "session.error" and properties.get("sessionID") == session_id:
                raise HarnessError("OpenCode parent failed; inspect native events.")
            elif kind == "session.status" and properties.get("sessionID") == session_id:
                if terminal and (properties.get("status") or {}).get("type") == "idle":
                    return
            if len(active) > max_subagents:
                raise HarnessError("OpenCode exceeded the campaign's active subagent limit.")
            if time.monotonic() >= self.deadline:
                raise HarnessError("OpenCode episode deadline exceeded.")

    def close(self) -> None:
        self.closed.set()
        try:
            stop(self.process)
        finally:
            self.stderr.close()
            self.raw.close()
