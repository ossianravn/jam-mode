from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jam.collaboration import CollaborationError, verify_contributions
from jam.harnesses.claude import Adapter, _assert_unmanaged_host
from jam.harnesses.claude_events import ClaudeEvents
from jam.harnesses.types import HarnessError, HarnessRequest
from jam.routing import build_requested_routing


ROLES = {"explorer": {"agent": "jam_explorer"}, "critic": {"agent": "jam_critic"}}
PAYLOAD = {"report_markdown": "Reviewed", "handoff": {"status": "complete"}}


def assistant(blocks, parent=None, model="claude-test"):
    return {"type": "assistant", "session_id": "session", "parent_tool_use_id": parent,
            "message": {"model": model, "content": blocks}}


def spawn(call_id, role, background=False):
    return {"type": "tool_use", "name": "Agent", "id": call_id,
            "input": {"subagent_type": role, "run_in_background": background}}


def result(call_id, error=False):
    return {"type": "user", "session_id": "session", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": "Finished", "is_error": error}]}}


def successful_events():
    return [assistant([spawn("a", "jam_explorer"), spawn("b", "jam_critic")]),
            assistant([{"type": "text", "text": "Explorer evidence"}], "a"), result("a"),
            assistant([{"type": "text", "text": "Critic evidence"}], "b"), result("b"),
            {"type": "result", "subtype": "success", "session_id": "session",
             "structured_output": PAYLOAD, "usage": {"input_tokens": 10}}]


def verify(collector):
    collector.finish()
    verify_contributions(collector.events, thread_id="session", turn_id=None,
                         final_text=collector.final_text, strategy="duo_independent")


class ClaudeHarnessTests(unittest.TestCase):
    def test_native_pair_and_launch_permissions_through_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            request = HarnessRequest(campaign={"workspace": directory, "sandbox": "workspace-write",
                "resolved_routing": build_requested_routing(policy="custom", validation="strict",
                    parent_model="claude-test", parent_effort="high")}, episode={}, prompt="Investigate",
                events_path=Path(directory) / "events.jsonl", stderr_path=Path(directory) / "stderr",
                timeout_seconds=20)

            def run(command, **kwargs):
                self.assertIn("dontAsk", command)
                self.assertNotIn("--bare", command)
                self.assertEqual(command[command.index("--model") + 1], "claude-test")
                self.assertEqual(command[command.index("--effort") + 1], "high")
                allowed = command[command.index("--allowedTools") + 1]
                self.assertIn("Agent(jam_critic)", allowed)
                self.assertNotIn("Bash", allowed)
                self.assertIn("Edit(./**)", allowed)
                self.assertIn("Write(./**)", allowed)
                self.assertNotIn("Edit", allowed.split(","))
                self.assertNotIn("Write", allowed.split(","))
                agents = json.loads(command[command.index("--agents") + 1])
                self.assertNotIn("Write", agents["jam_implementer"]["tools"])
                self.assertEqual(kwargs["environment"]["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"], "1")
                self.assertIn("run_in_background=false", kwargs["prompt"])
                events = successful_events()
                kwargs["events_path"].write_text("\n".join(map(json.dumps, events)))
                for event in events:
                    kwargs["on_event"](event)

            with patch.object(Adapter, "inspect", return_value={"supported": True, "executable": "claude"}), \
                 patch("jam.harnesses.claude._assert_unmanaged_host"), \
                 patch("jam.harnesses.claude.process.signed_in_environment", return_value={}), \
                 patch("jam.harnesses.claude.subprocess.run", return_value=type("Auth", (), {"stdout": json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"})})()), \
                 patch("jam.harnesses.claude.process.run_jsonl", side_effect=run):
                output = Adapter().run(request)
            evidence = [json.loads(line) for line in request.events_path.read_text().splitlines()]
            verify_contributions(evidence, thread_id=output.session_id, turn_id=None,
                                 final_text=output.final_text, strategy="duo_independent")
            self.assertTrue(request.events_path.with_suffix(".native.jsonl").exists())
            child_model = next(item for item in output.model_events if item["role"] == "critic")
            self.assertIsNone(child_model["requested_model"])
            self.assertEqual(child_model["expected_model"], "claude-test")

    def test_acknowledgement_without_child_result_is_not_contribution(self):
        collector = ClaudeEvents(ROLES, False)
        for event in successful_events():
            if event.get("parent_tool_use_id"):
                continue
            collector.observe(event)
        with self.assertRaises(CollaborationError):
            verify(collector)

    def test_api_credentials_do_not_start_an_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            request = HarnessRequest(campaign={"workspace": directory}, episode={}, prompt="Investigate",
                events_path=Path(directory) / "events.jsonl", stderr_path=Path(directory) / "stderr",
                timeout_seconds=20)
            with patch.object(Adapter, "inspect", return_value={"supported": True, "executable": "claude"}), \
                 patch("jam.harnesses.claude._assert_unmanaged_host"), \
                 patch("jam.harnesses.claude.subprocess.run", return_value=type("Auth", (), {"stdout": json.dumps({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"})})()), \
                 patch("jam.harnesses.claude.process.run_jsonl") as launch:
                with self.assertRaisesRegex(HarnessError, "subscription"):
                    Adapter().run(request)
                launch.assert_not_called()

    def test_managed_policy_files_are_rejected_before_inference(self):
        with patch("jam.harnesses.claude.sys.platform", "linux"), \
             patch("jam.harnesses.claude.platform.release", return_value="native"), \
             patch("jam.harnesses.claude.Path.stat", return_value=object()):
            with self.assertRaisesRegex(HarnessError, "managed policy files"):
                _assert_unmanaged_host()

    def test_unknown_platform_policy_discovery_is_rejected(self):
        with patch("jam.harnesses.claude.sys.platform", "linux"), \
             patch("jam.harnesses.claude.platform.release", return_value="microsoft-standard-WSL2"):
            with self.assertRaisesRegex(HarnessError, "policy discovery"):
                _assert_unmanaged_host()

    def test_organization_account_does_not_start_an_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            request = HarnessRequest(campaign={"workspace": directory}, episode={}, prompt="Investigate",
                events_path=Path(directory) / "events.jsonl", stderr_path=Path(directory) / "stderr",
                timeout_seconds=20)
            with patch.object(Adapter, "inspect", return_value={"supported": True, "executable": "claude"}), \
                 patch("jam.harnesses.claude._assert_unmanaged_host"), \
                 patch("jam.harnesses.claude.subprocess.run", return_value=type("Auth", (), {"stdout": json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "team"})})()), \
                 patch("jam.harnesses.claude.process.run_jsonl") as launch:
                with self.assertRaisesRegex(HarnessError, "Pro/Max"):
                    Adapter().run(request)
                launch.assert_not_called()

    def test_failed_child_does_not_count(self):
        events = successful_events()
        events[2] = result("a", error=True)
        collector = ClaudeEvents(ROLES, False)
        for event in events:
            collector.observe(event)
        with self.assertRaises(CollaborationError):
            verify(collector)

    def test_background_completion_requires_correlated_native_notification(self):
        events = successful_events()
        events[0]["message"]["content"][0]["input"]["run_in_background"] = True
        collector = ClaudeEvents(ROLES, False)
        for event in events[:-1]:
            collector.observe(event)
        collector.observe({"type": "system", "subtype": "task_started", "task_id": "task-a", "tool_use_id": "a"})
        collector.observe({"type": "system", "subtype": "task_notification", "task_id": "task-a", "status": "completed"})
        collector.observe(events[-1])
        verify(collector)

    def test_serial_duo_is_rejected(self):
        events = successful_events()
        events[0] = assistant([spawn("a", "jam_explorer")])
        events.insert(3, assistant([spawn("b", "jam_critic")]))
        collector = ClaudeEvents(ROLES, False)
        for event in events:
            collector.observe(event)
        with self.assertRaisesRegex(CollaborationError, "before starting"):
            verify(collector)

    def test_parent_prose_and_malformed_structured_handoff_are_rejected(self):
        collector = ClaudeEvents(ROLES, False)
        with self.assertRaisesRegex(HarnessError, "structured"):
            collector.observe({"type": "result", "subtype": "success", "session_id": "session",
                               "result": json.dumps(PAYLOAD)})

    def test_exact_model_mismatch_is_rejected(self):
        collector = ClaudeEvents({"parent": {"model": "claude-exact"}}, True)
        with self.assertRaisesRegex(HarnessError, "mismatch"):
            collector.observe(assistant([]))

    def test_inherited_child_model_mismatch_is_rejected(self):
        collector = ClaudeEvents({**ROLES, "parent": {"model": "claude-test"}}, True)
        collector.observe(assistant([spawn("a", "jam_explorer")]))
        with self.assertRaisesRegex(HarnessError, "mismatch for explorer"):
            collector.observe(assistant([{"type": "text", "text": "Findings"}], "a", model="claude-other"))

    def test_inherited_child_without_observed_identity_is_rejected(self):
        collector = ClaudeEvents({**ROLES, "parent": {"model": "claude-test"}}, True)
        events = successful_events()
        events[1]["message"].pop("model")
        for event in events:
            collector.observe(event)
        with self.assertRaisesRegex(HarnessError, "observed model for child explorer"):
            collector.finish()

    def test_resumed_child_cannot_masquerade_as_second_contributor(self):
        block = spawn("a", "jam_explorer")
        block["input"]["resume"] = "existing-agent"
        with self.assertRaisesRegex(HarnessError, "resumed"):
            ClaudeEvents(ROLES, False).observe(assistant([block]))


if __name__ == "__main__":
    unittest.main()
