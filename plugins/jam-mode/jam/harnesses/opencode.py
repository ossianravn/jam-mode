"""OpenCode native server adapter using an existing GitHub Copilot OAuth login."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from .opencode_config import configuration, isolated_environment, model_parts
from .opencode_events import normalize
from .opencode_server import Server
from .process import find_executable, signed_in_environment
from .types import HarnessError, HarnessRequest, HarnessResult


# Pin the primary-source contract until another version has fixture coverage.
SUPPORTED_VERSION = "1.18.30"
SOURCE = "https://github.com/anomalyco/opencode/tree/f69beceaffca94bed05a7669af93602125c37248/packages/opencode"


class Adapter:
    def inspect(self) -> dict:
        executable, version = None, None
        limitations = ["No live model execution verified; account access remains unverified.",
                       "Existing GitHub Copilot OAuth only; specify github-copilot/<model>.",
                       "Shell execution, effort variants, and resumed/background children are unsupported."]
        limitations.append("Task network tools are unavailable.")
        try:
            executable = find_executable("opencode")
            result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                    timeout=10, env=signed_in_environment("opencode"),
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            match = re.search(r"\b\d+\.\d+\.\d+\b", result.stdout)
            version = match.group() if match and result.returncode == 0 else None
            supported = version == SUPPORTED_VERSION
            if not supported:
                limitations.insert(0, f"JAM's server contract requires OpenCode {SUPPORTED_VERSION}; found {version or 'unknown'}.")
        except (HarnessError, OSError, subprocess.TimeoutExpired) as exc:
            supported = False
            limitations.insert(0, str(exc))
        return {"available": executable is not None, "executable": executable,
                "version": version, "supported": supported, "limitations": limitations,
                "source": SOURCE}

    def models(self) -> dict:
        return {"models": [], "catalog_status": "unavailable", "warnings": [
            "OpenCode's signed-in provider catalogue is not queried during offline inspection. "
            "Choose an explicit github-copilot/<model>; execution verifies observed identity."]}

    def run(self, request: HarnessRequest) -> HarnessResult:
        started = time.monotonic()
        support = self.inspect()
        if not support["supported"]:
            raise HarnessError(support["limitations"][0])
        config, requested = configuration(request.campaign)
        request.events_path.parent.mkdir(parents=True, exist_ok=True)
        request.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="jam-opencode-") as directory:
            environment = isolated_environment(Path(directory), config)
            remaining = request.timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise HarnessError("OpenCode episode deadline expired during preflight.")
            request = replace(request, timeout_seconds=remaining)
            server = Server(support["executable"], request, environment)
            try:
                health = server.call("GET", "/global/health", record=False)
                if not isinstance(health, dict) or health.get("version") != SUPPORTED_VERSION:
                    raise HarnessError("OpenCode server version does not match the inspected contract.")
                actual = server.call("GET", "/config", record=False)
                self._verify_config(actual, config)
                session = server.call("POST", "/session", {"title": "JAM episode"})
                if not isinstance(session, dict) or not isinstance(session.get("id"), str):
                    raise HarnessError("OpenCode did not return a session identity.")
                session_id = session["id"]
                path = "/session/" + quote(session_id, safe="")
                server.subscribe()
                server.call("POST", path + "/prompt_async", {
                    "agent": "jam_parent", "model": model_parts(requested["parent"]),
                    "parts": [{"type": "text", "text": request.prompt}],
                })
                server.wait_session(session_id, int(request.campaign.get("max_subagents", 2)))
                messages = server.call("GET", path + "/message")
                children = server.call("GET", path + "/children")
                if not isinstance(messages, list) or not isinstance(children, list):
                    raise HarnessError("OpenCode returned an invalid session history.")
                child_messages = {}
                for child in children:
                    if child.get("parentID") == session_id:
                        child_path = "/session/" + quote(child["id"], safe="") + "/message"
                        child_messages[child["id"]] = server.call("GET", child_path)
                text, events, models = normalize(session_id, messages, children, child_messages, requested)
                request.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
                return HarnessResult(session_id, "completed", text, agent_activity=events, model_events=models)
            finally:
                server.close()

    @staticmethod
    def _verify_config(actual: dict, expected: dict) -> None:
        if not isinstance(actual, dict):
            raise HarnessError("OpenCode did not expose its effective configuration.")
        for field in ("enabled_providers", "share", "permission", "formatter", "lsp"):
            if actual.get(field) != expected[field]:
                raise HarnessError(f"OpenCode effective {field} differs from the campaign contract.")
        if actual.get("mcp") or actual.get("plugin"):
            raise HarnessError("OpenCode loaded ambient MCP or plugin configuration.")
        for name, agent in expected["agent"].items():
            current = (actual.get("agent") or {}).get(name) or {}
            if current.get("permission") != agent["permission"] or current.get("model") != agent["model"]:
                raise HarnessError(f"OpenCode effective agent {name} differs from its permission/model contract.")
