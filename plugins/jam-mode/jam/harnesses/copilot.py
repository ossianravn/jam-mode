"""Signed-in Copilot SDK adapter, pinned to the inspected runtime contract."""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
import time
from dataclasses import replace

from ..routing_defs import ROLE_AGENT_NAMES, ROLE_SPECS
from .copilot_events import Evidence
from .copilot_server import Server
from .process import find_executable, signed_in_environment
from .types import HarnessError, HarnessRequest, HarnessResult

# The upstream SDK package pins this CLI version. Unknown versions must not
# silently ignore permission or event-forwarding options on session.create.
SUPPORTED_VERSION = "1.0.83"
SOURCE = "https://github.com/github/copilot-sdk/tree/cd8cf15dc3f9e762615790aaed0a771a0f392755/nodejs"
READ_TOOLS = ["view", "glob", "grep"]


def _probe(executable: str, argument: str) -> str:
    result = subprocess.run([executable, argument], capture_output=True, text=True,
                            timeout=10, env=signed_in_environment("copilot"),
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise HarnessError(f"Copilot {argument} inspection failed.")
    return result.stdout.strip()


def session_options(campaign: dict, session_id: str) -> tuple[dict, dict]:
    if campaign.get("allow_network"):
        raise HarnessError("Copilot task network tools are not supported by this adapter.")
    overrides = (campaign.get("resolved_routing") or {}).get("overrides") or {}
    parent = overrides.get("parent") or {}
    roles = overrides.get("roles") or {}
    agents, requested = [], {"parent": parent.get("model")}
    for role, spec in ROLE_SPECS.items():
        route = roles.get(role) or {}
        if route.get("effort"):
            raise HarnessError("Copilot SDK custom agents do not expose per-role reasoning effort.")
        name = ROLE_AGENT_NAMES[role]
        model = route.get("model") or parent.get("model")
        requested[name] = model
        agent = {"name": name, "description": spec["description"], "tools": READ_TOOLS,
                 "prompt": spec["instructions"] + "\nReturn findings; only the parent may edit files.",
                 "infer": True, "mcpServers": {}}
        if model:
            agent["model"] = model
        agents.append(agent)
    tools = READ_TOOLS + ["task"]
    if campaign.get("sandbox") == "workspace-write":
        tools += ["create", "edit", "apply_patch"]
    options = {
        "sessionId": session_id, "workingDirectory": campaign["workspace"],
        "clientName": "jam-mode", "availableTools": tools, "customAgents": agents,
        "enableConfigDiscovery": False, "enableFileHooks": False,
        "enableSkills": False, "enableSessionStore": False, "enableHostGitOperations": False,
        "enableOnDemandInstructionDiscovery": False, "customAgentsLocalOnly": True,
        "pluginDirectories": [], "skillDirectories": [], "instructionDirectories": [],
        "mcpServers": {}, "disabledMcpServers": ["github-mcp-server"],
        "memory": {"enabled": False}, "remoteSession": "off", "streaming": True,
        "includeSubAgentStreamingEvents": True, "requestPermission": True,
        "requestUserInput": False,
        "hooks": True,
    }
    if parent.get("model"):
        options["model"] = parent["model"]
    if parent.get("effort"):
        if parent["effort"] not in {"low", "medium", "high", "xhigh"}:
            raise HarnessError("Copilot parent effort must be low, medium, high, or xhigh.")
        options["reasoningEffort"] = parent["effort"]
    return options, requested


class Adapter:
    def inspect(self) -> dict:
        executable, version = None, None
        limitations = ["No live model execution verified; signed-in account access remains unverified.",
                       "Shell execution is disabled; children have read tools only.",
                       "Per-role reasoning effort is unsupported."]
        limitations.append("Task network tools and background delegation are unavailable.")
        try:
            executable = find_executable("copilot")
            raw = _probe(executable, "--version")
            match = re.search(r"\b\d+\.\d+\.\d+\b", raw)
            version = match.group() if match else None
            supported = version == SUPPORTED_VERSION
            if not supported:
                limitations.insert(0, f"JAM's SDK contract requires Copilot {SUPPORTED_VERSION}; found {version or 'unknown'}.")
        except (HarnessError, OSError, subprocess.TimeoutExpired) as exc:
            supported = False
            limitations.insert(0, str(exc))
        return {"available": executable is not None, "executable": executable,
                "version": version, "supported": supported, "limitations": limitations,
                "source": SOURCE}

    def models(self) -> dict:
        try:
            help_text = _probe(find_executable("copilot"), "--help")
            section = help_text.split("--model", 1)[1].split("--", 1)[0]
            identifiers = re.findall(r'"([^"\s]+)"', section)
        except (HarnessError, OSError, subprocess.TimeoutExpired, IndexError) as exc:
            return {"models": [], "catalog_status": "unavailable", "warnings": [str(exc)]}
        return {"models": [{"id": value, "availability": "unverified"} for value in identifiers],
                "catalog_status": "advertised" if identifiers else "unavailable",
                "warnings": ["CLI-advertised models; signed-in account availability is unverified."]}

    def run(self, request: HarnessRequest) -> HarnessResult:
        started = time.monotonic()
        support = self.inspect()
        if not support["supported"]:
            raise HarnessError(support["limitations"][0])
        session_id = str(uuid.uuid4())
        options, requested = session_options(request.campaign, session_id)
        evidence = Evidence(session_id, requested, int(request.campaign.get("max_subagents", 2)))
        request.events_path.parent.mkdir(parents=True, exist_ok=True)
        request.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        remaining = request.timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise HarnessError("Copilot episode deadline expired during preflight.")
        request = replace(request, timeout_seconds=remaining)
        server = Server(support["executable"], request, signed_in_environment("copilot"), evidence.observe)
        server.session_id = session_id
        try:
            connection = server.request_rpc("connect", {})
            if connection.get("protocolVersion") != 3 or connection.get("version") != SUPPORTED_VERSION:
                raise HarnessError("Copilot SDK runtime version/protocol does not match the inspected contract.")
            result = server.request_rpc("session.create", options)
            if result.get("sessionId") != session_id:
                raise HarnessError("Copilot returned an unexpected session identity.")
            server.request_rpc("session.send", {"sessionId": session_id,
                                                "prompt": request.prompt + "\nUse task(mode='sync') for delegation. "
                                                "Submit both independent task calls together before waiting; background mode is disabled.",
                                                "mode": "immediate"})
            while not evidence.idle:
                server.pump()
            evidence.finish()
        finally:
            server.close()
            request.events_path.write_text("".join(json.dumps(e) + "\n" for e in evidence.events), encoding="utf-8")
        return HarnessResult(session_id, "completed", evidence.final_text,
                             agent_activity=evidence.events, model_events=evidence.models)
