from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, TextIO

from .util import json_dumps


class AppServerError(RuntimeError):
    pass

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

class AppServerTransport:
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
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
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
            self.close()
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
                    "version": "0.3.2",
                },
                "capabilities": {
                    "experimentalApi": self._experimental_api,
                    "optOutNotificationMethods": ["item/agentMessage/delta"],
                },
            },
            timeout=60,
        )
        self.notify("initialized", {})

    def close(self) -> None:
        process = getattr(self, "process", None)
        try:
            if process is not None and process.stdin and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader = getattr(self, "_reader", None)
        if reader is not None:
            reader.join(timeout=2)
        try:
            if process is not None and process.stdout and not process.stdout.closed:
                process.stdout.close()
        except OSError:
            pass
        try:
            stderr = getattr(self, "_stderr", None)
            if stderr is not None and not stderr.closed:
                stderr.close()
        except OSError:
            pass

    def __enter__(self) -> "AppServerClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
