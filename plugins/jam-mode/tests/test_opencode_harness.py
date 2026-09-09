from __future__ import annotations

import json
import queue
import tempfile
import time
import threading
import unittest
from fnmatch import fnmatchcase
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jam.collaboration import CollaborationError, verify_contributions
from jam.harnesses.opencode import Adapter, SUPPORTED_VERSION
from jam.harnesses.opencode_config import configuration, isolated_environment
from jam.harnesses.opencode_events import normalize
from jam.harnesses.opencode_server import Server
from jam.harnesses.types import HarnessError, HarnessRequest


MODEL = "github-copilot/claude-sonnet-4.6"


def message(session, role, at, text="Independent findings"):
    return {"info": {"role": "assistant", "sessionID": session, "finish": "stop", "agent": role,
                     "providerID": "github-copilot", "modelID": "claude-sonnet-4.6", "time": {"completed": at}},
            "parts": [{"type": "text", "text": text}]}


def fixture():
    parent = message("parent", "jam_parent", 10, "Final handoff")
    children, child_messages = [], {}
    for number, role in enumerate(("jam_explorer", "jam_critic")):
        ident = f"child{number}"
        children.append({"id": ident, "parentID": "parent", "time": {"created": 1 + number}})
        child_messages[ident] = [message(ident, role, 5 + number)]
        parent["parts"].insert(0, {"type": "tool", "tool": "task", "state": {
            "status": "completed", "metadata": {"sessionId": ident},
            "input": {"subagent_type": role}, "time": {"end": 7 + number}}})
    return [parent], children, child_messages


def campaign(directory):
    return {"workspace": str(directory), "sandbox": "workspace-write",
            "resolved_routing": {"overrides": {"parent": {"model": MODEL}}}}


class OpenCodeHarnessTests(unittest.TestCase):
    def test_parent_can_delegate_only_to_read_only_role_agents(self):
        config, _ = configuration(campaign("."))
        agents = config["agent"]
        task = agents["jam_parent"]["permission"]["task"]
        for name in (*agents, "jam_unknown", "general"):
            with self.subTest(agent=name):
                matching = [value for pattern, value in task.items() if fnmatchcase(name, pattern)]
                allowed = name in agents and name != "jam_parent"
                self.assertEqual(matching[-1], "allow" if allowed else "deny")
                if allowed:
                    self.assertEqual(agents[name]["permission"], {
                        "*": "deny", "read": "allow", "glob": "allow", "grep": "allow"})
        self.assertEqual(agents["jam_parent"]["permission"]["edit"], "allow")

    def test_correlated_native_child_results_pass_existing_verifier(self):
        text, events, _ = normalize("parent", *fixture(), dict.fromkeys(("parent", "jam_explorer", "jam_critic"), MODEL))
        verify_contributions(events, thread_id="parent", turn_id=None, final_text=text, strategy="duo_independent")

    def test_late_child_or_wrong_model_cannot_count(self):
        for changed in ("late", "model"):
            with self.subTest(changed=changed):
                messages, children, details = fixture()
                info = details["child0"][0]["info"]
                if changed == "late":
                    info["time"]["completed"] = 20
                else:
                    info["modelID"] = "substitute"
                with self.assertRaises(HarnessError):
                    normalize("parent", messages, children, details, dict.fromkeys(("parent", "jam_explorer", "jam_critic"), MODEL))

    def test_missing_child_result_is_not_replaced_by_parent_claim(self):
        messages, children, details = fixture()
        children.pop()
        text, events, _ = normalize("parent", messages, children, details, dict.fromkeys(("parent", "jam_explorer", "jam_critic"), MODEL))
        with self.assertRaises(CollaborationError):
            verify_contributions(events, thread_id="parent", turn_id=None, final_text=text, strategy="duo_independent")

    def test_oauth_only_environment_and_child_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / "data" / "opencode"
            auth.mkdir(parents=True)
            config, _ = configuration(campaign(root))
            with patch.dict("os.environ", {"XDG_DATA_HOME": str(root / "data")}):
                (auth / "auth.json").write_text(json.dumps({"github-copilot": {"type": "api"}}))
                with self.assertRaises(HarnessError):
                    isolated_environment(root / "isolated", config)
                (auth / "auth.json").write_text(json.dumps({"github-copilot": {"type": "oauth"}}))
                environment = isolated_environment(root / "isolated", config)
            self.assertEqual(environment["OPENCODE_PURE"], "true")
            self.assertEqual(environment["OPENCODE_DISABLE_PROJECT_CONFIG"], "true")
            self.assertEqual(config["agent"]["jam_parent"]["permission"]["edit"], "allow")
            self.assertEqual(config["agent"]["jam_critic"]["permission"]["*"], "deny")
            self.assertNotIn("edit", config["agent"]["jam_critic"]["permission"])

    def test_adapter_drives_native_server_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = campaign(root)
            config, _ = configuration(data)
            messages, children, details = fixture()
            request = HarnessRequest(data, {}, "Original objective", root / "events.jsonl", root / "err", 10)
            class FakeServer:
                def __init__(self, *args):
                    pass
                def call(self, method, path, payload=None, **kwargs):
                    if path == "/global/health":
                        return {"version": SUPPORTED_VERSION}
                    if path == "/config":
                        return config
                    if path == "/session":
                        return {"id": "parent"}
                    if path.endswith("/prompt_async"):
                        assert payload["model"]["providerID"] == "github-copilot"
                        return None
                    if path.endswith("/children"):
                        return children
                    return messages if path == "/session/parent/message" else details[path.split("/")[2]]
                def subscribe(self):
                    pass
                def wait_session(self, session, maximum):
                    pass
                def close(self):
                    pass
            with patch.object(Adapter, "inspect", return_value={"supported": True, "executable": "opencode"}), patch("jam.harnesses.opencode.Server", FakeServer), patch("jam.harnesses.opencode.isolated_environment", return_value={}):
                result = Adapter().run(request)
            self.assertEqual(result.final_text, "Final handoff")
            self.assertIn("Independent findings", request.events_path.read_text())

    def test_live_event_limit_rejects_excess_children(self):
        server = object.__new__(Server)
        server.deadline = time.monotonic() + 5
        server.raw = StringIO()
        server.events = queue.Queue()
        for number in range(3):
            server.events.put({"type": "session.created", "properties": {"info": {
                "id": str(number), "parentID": "parent"}}})
        with self.assertRaisesRegex(HarnessError, "active subagent limit"):
            server.wait_session("parent", 2)

    def test_http_deadline_bounds_dribbling_response_read(self):
        release = threading.Event()
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, maximum):
                self.maximum = maximum
                release.wait(2)
                return b"{}"
        class Http:
            def open(self, *args, **kwargs):
                return Response()
        server = object.__new__(Server)
        server.deadline = time.monotonic() + 0.05
        server.url, server.authorization, server.http = "http://127.0.0.1:1234", "fixture", Http()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(HarnessError, "episode deadline"):
                server.call("GET", "/session")
            self.assertLess(time.monotonic() - started, 1)
        finally:
            release.set()
