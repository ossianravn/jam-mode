from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.collaboration import CollaborationError, verify_contributions
from jam.harnesses.copilot import Adapter, SUPPORTED_VERSION, session_options
from jam.harnesses.copilot_events import Evidence
from jam.harnesses.copilot_server import Server
from jam.harnesses.types import HarnessError, HarnessRequest
from jam.harnesses.process_tree import launch


def events():
    result = []
    for number, role in enumerate(("jam_explorer", "jam_critic")):
        result.append({"type": "subagent.started", "agentId": role, "data": {
            "agentName": role, "toolCallId": str(number)}})
    for number, role in enumerate(("jam_explorer", "jam_critic")):
        result.extend([
            {"type": "assistant.message", "agentId": role, "data": {"content": "Independent findings"}},
            {"type": "subagent.completed", "agentId": role,
             "data": {"model": "claude-sonnet-4.6", "toolCallId": str(number)}},
            {"type": "tool.execution_complete", "data": {"toolCallId": str(number), "success": True}},
        ])
    result.extend([
        {"type": "assistant.usage", "data": {"model": "claude-sonnet-4.6"}},
        {"type": "assistant.message", "data": {"content": "Final handoff"}},
        {"type": "session.idle", "data": {}},
    ])
    return result


class CopilotHarnessTests(unittest.TestCase):
    def evidence(self):
        return Evidence("parent", dict.fromkeys(("parent", "jam_explorer", "jam_critic"), "claude-sonnet-4.6"))

    def verify(self, evidence):
        verify_contributions(evidence.events, thread_id="parent", turn_id=None,
                             final_text=evidence.final_text, strategy="duo_independent")

    def test_native_pair_requires_completion_delivery_and_fresh_results(self):
        evidence = self.evidence()
        for event in events():
            evidence.observe(event)
        evidence.finish()
        self.verify(evidence)
        evidence.observe({"type": "subagent.started", "agentId": "jam_critic", "data": {
            "agentName": "jam_critic", "toolCallId": "new"}})
        evidence.observe({"type": "assistant.message", "data": {"content": "New final"}})
        with self.assertRaises(CollaborationError):
            self.verify(evidence)

    def test_cancelled_child_cannot_count_as_completed(self):
        evidence = self.evidence()
        for event in events():
            if event["type"] == "subagent.completed" and event["agentId"] == "jam_critic":
                event["data"]["cancelled"] = True
            evidence.observe(event)
        with self.assertRaises(CollaborationError):
            self.verify(evidence)

    def test_actual_model_substitution_is_rejected(self):
        evidence = self.evidence()
        with self.assertRaises(HarnessError):
            evidence.observe({"type": "assistant.usage", "data": {"model": "another-model"}})

    def test_workspace_writes_and_bypass_are_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            server = object.__new__(Server)
            server.request = HarnessRequest({"workspace": directory, "sandbox": "workspace-write"}, {}, "", Path(), Path(), 10)
            self.assertEqual(server.permission({"kind": "write", "fileName": "output.md"})["kind"], "approved")
            for permission in ({"kind": "write", "fileName": "../outside.md"},
                               {"kind": "read", "path": "a", "requestSandboxBypass": True},
                               {"kind": "read", "path": "a", "managedApprovalRequired": True},
                               {"kind": "shell", "command": "echo hi"}):
                self.assertNotEqual(server.permission(permission)["kind"], "approved")

    def test_editing_tools_are_available_only_to_writable_parent(self):
        write_tools = {"create", "edit", "apply_patch"}
        for sandbox in ("workspace-write", "read-only"):
            with self.subTest(sandbox=sandbox):
                options, _ = session_options({"workspace": ".", "sandbox": sandbox}, "session")
                expected = write_tools if sandbox == "workspace-write" else set()
                self.assertEqual(write_tools.intersection(options["availableTools"]), expected)
                for agent in options["customAgents"]:
                    self.assertEqual(set(agent["tools"]), {"view", "glob", "grep"})

    def test_adapter_uses_native_server_without_ambient_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            request = HarnessRequest({"workspace": directory, "sandbox": "workspace-write",
                                      "resolved_routing": {"overrides": {"parent": {"model": "claude-sonnet-4.6"}}}},
                                     {}, "Original objective", Path(directory) / "events.jsonl", Path(directory) / "err", 10)
            class FakeServer:
                def __init__(self, executable, request, environment, callback):
                    self.callback = callback
                def request_rpc(self, method, params):
                    if method == "connect":
                        return {"version": SUPPORTED_VERSION, "protocolVersion": 3}
                    if method == "session.create":
                        self.options = params
                        assert params["enableFileHooks"] is False
                        assert params["enableConfigDiscovery"] is False
                        assert all("edit" not in item["tools"] for item in params["customAgents"])
                        return {"sessionId": self.session_id}
                    for event in events():
                        self.callback(event)
                    return {}
                def close(self):
                    pass
            with patch.object(Adapter, "inspect", return_value={"supported": True, "executable": "copilot"}), patch("jam.harnesses.copilot.Server", FakeServer):
                result = Adapter().run(request)
            self.assertEqual(result.final_text, "Final handoff")
            self.assertIn("Independent findings", request.events_path.read_text())

    def test_role_effort_refused_before_launch(self):
        with self.assertRaises(HarnessError):
            session_options({"workspace": ".", "resolved_routing": {"overrides": {
                "roles": {"critic": {"effort": "high"}}}}}, "session")

    def test_old_receipt_cannot_deliver_reassigned_child(self):
        evidence = self.evidence()
        for event in events():
            evidence.observe(event)
        for event in [
            {"type": "subagent.started", "agentId": "jam_critic", "data": {
                "agentName": "jam_critic", "toolCallId": "new"}},
            {"type": "assistant.message", "agentId": "jam_critic", "data": {"content": "Fresh result"}},
            {"type": "subagent.completed", "agentId": "jam_critic", "data": {
                "toolCallId": "new", "model": "claude-sonnet-4.6"}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "1", "success": True}},
            {"type": "assistant.message", "data": {"content": "New final"}},
        ]:
            evidence.observe(event)
        with self.assertRaises(CollaborationError):
            self.verify(evidence)

    def test_real_stdio_framing_and_blocked_write_deadline(self):
        scripts = [
            "import sys,json\n"
            "line=sys.stdin.buffer.readline()\n"
            "size=int(line.split(b':')[1])\n"
            "sys.stdin.buffer.readline()\n"
            "req=json.loads(sys.stdin.buffer.read(size))\n"
            "data=json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{'ok':True}}).encode()\n"
            "sys.stdout.buffer.write(('Content-Length: %d\\r\\n\\r\\n'%len(data)).encode()+data)\n"
            "sys.stdout.buffer.flush()\n",
            "import time; time.sleep(30)",
        ]
        with tempfile.TemporaryDirectory() as directory:
            for number, script in enumerate(scripts):
                with self.subTest(case=number):
                    root = Path(directory)
                    request = HarnessRequest({"workspace": directory}, {}, "", root / "events", root / "err", 1)
                    def fake_launch(command, **kwargs):
                        return launch([sys.executable, "-u", "-c", script], **kwargs)
                    with patch("jam.harnesses.copilot_server.launch", side_effect=fake_launch):
                        server = Server("fixture", request, {}, lambda event: None)
                    try:
                        if number == 0:
                            self.assertEqual(server.request_rpc("ping", {}), {"ok": True})
                        else:
                            with self.assertRaisesRegex(HarnessError, "deadline"):
                                server.request_rpc("ping", {"message": "x" * 1_000_000})
                    finally:
                        server.close()
                    self.assertIsNotNone(server.process.poll())
