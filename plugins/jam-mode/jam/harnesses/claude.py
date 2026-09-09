"""Claude Code print-mode adapter using the user's existing subscription login."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from ..handoff_schema import HANDOFF_SCHEMA
from ..routing_defs import CHILD_ROLES, ROLE_AGENT_NAMES, ROLE_SPECS
from . import process
from .claude_events import ClaudeEvents
from .types import HarnessError, HarnessRequest, HarnessResult


LIMITATIONS = [
    "Account login and model availability are unverified until a signed-in run.",
    "Tool permissions are enforced by Claude Code; this is not an OS sandbox.",
    "No shell, external MCP, hooks, nested agents, or resumed child assignments.",
    "Strict routing requires full model IDs and observed model evidence; aliases are unverified.",
    "Protocol fixtures are tested; no live account-backed campaign has been verified.",
    "Requires personal Pro/Max sign-in and an unmanaged native Windows/Linux host; macOS/WSL policy discovery is unsupported.",
]


def _assert_unmanaged_host() -> None:
    # Managed policy outranks CLI flags and can add hooks or force plugins.
    # Reject it rather than attempting to override an administrator's policy.
    if sys.platform not in {"win32", "linux"} or "microsoft" in platform.release().lower():
        raise HarnessError("Claude policy isolation currently supports native Windows/Linux only; macOS/WSL require effective managed-policy discovery.")
    if sys.platform == "win32":
        import winreg
        try:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(root, r"SOFTWARE\Policies\ClaudeCode", 0, winreg.KEY_READ | view):
                            raise HarnessError("Claude managed registry policy is unsupported by JAM's isolated tool contract.")
                    except FileNotFoundError:
                        continue
        except OSError as exc:
            raise HarnessError("Could not establish absence of Claude managed registry policy.") from exc
        directory = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode"
    else:
        directory = Path("/etc/claude-code")
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    paths = [directory / name for name in ("managed-settings.json", "managed-settings.d", "managed-mcp.json")]
    paths.append(config / "remote-settings.json")
    for path in paths:
        try:
            path.stat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise HarnessError("Could not establish absence of Claude managed policy files.") from exc
        raise HarnessError("Claude managed policy files are unsupported by JAM's isolated tool contract.")


class Adapter:
    def inspect(self) -> dict:
        try:
            executable = process.find_executable("claude")
            result = subprocess.run([executable, "--version"], capture_output=True,
                                    text=True, timeout=10, check=True)
            version = result.stdout.strip()
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
            supported = bool(match and tuple(map(int, match.groups())) >= (2, 1, 219))
            try:
                _assert_unmanaged_host()
            except HarnessError as exc:
                return {"available": True, "executable": executable, "version": version,
                        "supported": False, "limitations": [str(exc), *LIMITATIONS]}
            return {"available": True, "executable": executable, "version": version,
                    "supported": supported, "limitations": LIMITATIONS}
        except (HarnessError, OSError, subprocess.SubprocessError):
            return {"available": False, "executable": None, "version": None,
                    "supported": False, "limitations": LIMITATIONS}

    def models(self) -> dict:
        return {"models": [{"id": name, "availability": "unverified", "alias": True}
                           for name in ("sonnet", "opus", "haiku", "fable")],
                "catalog_status": "advertised", "warnings": LIMITATIONS}

    def run(self, request: HarnessRequest) -> HarnessResult:
        deadline = time.monotonic() + request.timeout_seconds
        support = self.inspect()
        if not support["supported"]:
            raise HarnessError("Claude Code >=2.1.219 on an unmanaged supported host is required for bounded native subagents.")
        _assert_unmanaged_host()
        campaign = request.campaign
        if campaign.get("sandbox", "read-only") not in {"read-only", "workspace-write"}:
            raise HarnessError("Claude supports read-only or workspace-write tool permissions only.")
        routing = campaign.get("resolved_routing") or {}
        if routing.get("allow_child_ultra") or routing.get("policy", "inherit") not in {"inherit", "custom"}:
            raise HarnessError("Claude supports inherit/custom routing without nested agents.")
        roles = {key: dict(value) for key, value in (routing.get("roles") or {}).items()}
        roles["parent"] = dict(routing.get("parent") or {})
        strict = routing.get("validation") == "strict"
        tools = ["Read", "Glob", "Grep"]
        if campaign.get("allow_network"):
            tools += ["WebSearch", "WebFetch"]
        agents = {}
        for role in CHILD_ROLES:
            entry = roles.setdefault(role, {})
            entry.setdefault("agent", ROLE_AGENT_NAMES[role])
            agents[entry["agent"]] = {
                "description": ROLE_SPECS[role]["description"],
                "prompt": ROLE_SPECS[role]["instructions"] +
                "\nYou are read-only. Return findings to the parent, who owns all edits.",
                "tools": tools, "model": entry.get("model") or "inherit",
            }
            if entry.get("effort"):
                agents[entry["agent"]]["effort"] = entry["effort"]
        for entry in roles.values():
            if entry.get("effort") and entry["effort"] not in {"low", "medium", "high", "xhigh", "max"}:
                raise HarnessError("Claude routing contains an unsupported effort.")
            if strict and entry.get("model") and not entry["model"].startswith("claude-"):
                raise HarnessError("Strict Claude routing requires full model IDs, not aliases.")
        parent_tools = tools + ["Agent"]
        if campaign.get("sandbox") == "workspace-write":
            parent_tools += ["Edit", "Write"]
        # Only named read-only agents may be invoked, including in writable campaigns.
        allowed = tools + [f"Agent({name})" for name in agents]
        if campaign.get("sandbox") == "workspace-write":
            allowed += ["Edit(./**)", "Write(./**)"]
        command = [support["executable"], "--print", "--verbose", "--output-format", "stream-json",
                   "--input-format", "text", "--forward-subagent-text", "--no-session-persistence",
                   "--setting-sources", "", "--settings", json.dumps({"disableAllHooks": True,
                   "enabledPlugins": {}}), "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--disable-slash-commands", "--no-chrome", "--permission-mode", "dontAsk",
                   "--tools", ",".join(parent_tools), "--allowedTools", ",".join(allowed),
                   "--agents", json.dumps(agents), "--json-schema", json.dumps(HANDOFF_SCHEMA)]
        parent = roles.get("parent") or {}
        for field in ("model", "effort"):
            if parent.get(field):
                command.extend([f"--{field}", parent[field]])
        environment = process.signed_in_environment("claude-code")
        environment.update({"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
                            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(campaign.get("max_subagents", 2)),
                            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1"})
        try:
            auth = subprocess.run([support["executable"], "--setting-sources", "", "auth", "status", "--json"],
                                  env=environment, cwd=campaign["workspace"], capture_output=True,
                                  text=True, timeout=10, check=True)
            status = json.loads(auth.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise HarnessError("Could not verify Claude subscription sign-in; run claude auth login.") from exc
        if not isinstance(status, dict) or not status.get("loggedIn") or status.get("authMethod") != "claude.ai" or status.get("apiProvider") != "firstParty":
            raise HarnessError("Claude requires an existing first-party Claude subscription sign-in; API credentials are unsupported.")
        if status.get("subscriptionType") not in {"pro", "max"}:
            raise HarnessError("Claude requires personal Pro/Max sign-in; remote managed policy cannot be excluded for this account.")
        collector = ClaudeEvents(roles, strict)
        raw_path = request.events_path.with_suffix(".native.jsonl")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError("Claude preflight exceeded the episode deadline.")
        try:
            prompt = request.prompt + "\nFor native Agent calls, explicitly set run_in_background=false. Launch independent children in the same assistant turn before receiving either result."
            process.run_jsonl(command, prompt=prompt, cwd=campaign["workspace"],
                              environment=environment, events_path=raw_path,
                              stderr_path=request.stderr_path, timeout_seconds=remaining,
                              on_event=collector.observe)
            collector.finish()
        finally:
            request.events_path.parent.mkdir(parents=True, exist_ok=True)
            request.events_path.write_text("".join(json.dumps(event) + "\n" for event in collector.events), encoding="utf-8")
        return HarnessResult(session_id=collector.session_id, status="completed",
                             final_text=collector.final_text, agent_activity=collector.events,
                             model_events=collector.models, token_usage=collector.result.get("usage"))
