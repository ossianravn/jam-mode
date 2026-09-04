from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.controller import run_campaign
from jam.store import Store


FAKE_HANDOFF = {
    "report_markdown": "# Integration result\n\nThe bounded fake episode completed.",
    "handoff": {
        "status": "complete",
        "summary": "The integration objective is complete.",
        "progress_score": 1.0,
        "task_profile": "general",
        "profile_reason": "A deterministic protocol exercise needed no specialized profile.",
        "strategy_used": "solo",
        "strategy_reason": "A deterministic bounded check was sufficient.",
        "completed_actions": ["Ran the fake integration check."],
        "decisions": [],
        "state_updates": [
            {
                "id": "CHECK-1",
                "kind": "quality_check",
                "statement": "The fake App Server lifecycle completed.",
                "status": "validated",
                "evidence_refs": ["turn/completed"],
                "confidence": "high",
            }
        ],
        "deliverables": [],
        "validation": [
            {
                "check": "Fake App Server protocol lifecycle",
                "result": "passed",
                "evidence_refs": ["turn/completed"],
            }
        ],
        "blockers": [],
        "risks": [],
        "artifacts": [],
        "open_items": [],
        "next_options": [],
        "recommended_next_option": None,
        "needs_user_input": False,
        "user_question": None,
        "completion_assessment": {
            "goal_reached": True,
            "progress_plateau": False,
            "reason": "The test objective was satisfied.",
        },
        "boundary_flags": [],
    },
}


class ControllerIntegrationTests(unittest.TestCase):
    def test_full_episode_through_fake_app_server(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex-home"
            jam_home = root / "jam-home"
            workspace = root / "workspace"
            fake_bin = root / "bin"
            workspace.mkdir()
            fake_bin.mkdir()
            fake_codex = fake_bin / ("fake_codex.py" if os.name == "nt" else "codex")
            payload_literal = repr(json.dumps(FAKE_HANDOFF))
            fake_codex.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import json
                    import sys

                    FINAL_TEXT = {payload_literal}

                    if len(sys.argv) >= 3 and sys.argv[1:3] == ["app-server", "--help"]:
                        print("fake app-server")
                        raise SystemExit(0)
                    if len(sys.argv) < 2 or sys.argv[1] != "app-server":
                        raise SystemExit(2)

                    def send(message):
                        print(json.dumps(message, separators=(",", ":")), flush=True)

                    for raw in sys.stdin:
                        message = json.loads(raw)
                        method = message.get("method")
                        request_id = message.get("id")
                        if method == "initialize":
                            capabilities = (message.get("params") or {{}}).get("capabilities") or {{}}
                            if capabilities.get("experimentalApi") is not True:
                                send({{
                                    "id": request_id,
                                    "error": {{"code": -32600, "message": "experimentalApi is required"}},
                                }})
                            else:
                                send({{"id": request_id, "result": {{"serverInfo": {{"name": "fake"}}}}}})
                        elif method in ("initialized", "notifications/initialized"):
                            pass
                        elif method == "thread/start":
                            permissions = (message.get("params") or {{}}).get("permissions")
                            if permissions not in {{":read-only", ":workspace"}}:
                                send({{
                                    "id": request_id,
                                    "error": {{
                                        "code": -32600,
                                        "message": f"invalid permissions profile: {{permissions}}",
                                    }},
                                }})
                            else:
                                send({{"id": request_id, "result": {{"thread": {{"id": "thr_fake_001"}}}}}})
                        elif method == "thread/name/set":
                            send({{"id": request_id, "result": {{}}}})
                        elif method == "turn/start":
                            permissions = (message.get("params") or {{}}).get("permissions")
                            if permissions != ":read-only":
                                send({{
                                    "id": request_id,
                                    "error": {{
                                        "code": -32600,
                                        "message": f"invalid turn permissions profile: {{permissions}}",
                                    }},
                                }})
                                continue
                            send({{"id": request_id, "result": {{"turn": {{"id": "turn_fake_001", "status": "inProgress"}}}}}})
                            send({{
                                "method": "item/started",
                                "params": {{
                                    "threadId": "thr_fake_001",
                                    "turnId": "turn_fake_001",
                                    "item": {{
                                        "id": "collab_fake_001",
                                        "type": "collabToolCall",
                                        "agentName": "jam_reviewer",
                                        "prompt": "Use jam_reviewer to independently validate the bounded result."
                                    }}
                                }}
                            }})
                            send({{
                                "method": "item/completed",
                                "params": {{
                                    "threadId": "thr_fake_001",
                                    "turnId": "turn_fake_001",
                                    "item": {{
                                        "id": "collab_fake_001",
                                        "type": "collabToolCall",
                                        "agentName": "jam_reviewer",
                                        "prompt": "Use jam_reviewer to independently validate the bounded result.",
                                        "status": "completed"
                                    }}
                                }}
                            }})
                            send({{
                                "method": "model/rerouted",
                                "params": {{
                                    "threadId": "thr_fake_001",
                                    "turnId": "turn_fake_001",
                                    "fromModel": "gpt-5.6-sol",
                                    "toModel": "gpt-5.6-terra",
                                    "reason": "fake-test"
                                }}
                            }})
                            send({{
                                "method": "thread/tokenUsage/updated",
                                "params": {{
                                    "threadId": "thr_fake_001",
                                    "tokenUsage": {{"inputTokens": 123, "outputTokens": 45}}
                                }}
                            }})
                            send({{
                                "method": "item/completed",
                                "params": {{
                                    "threadId": "thr_fake_001",
                                    "turnId": "turn_fake_001",
                                    "item": {{
                                        "type": "agentMessage",
                                        "phase": "final_answer",
                                        "text": FINAL_TEXT
                                    }}
                                }}
                            }})
                            send({{
                                "method": "turn/completed",
                                "params": {{
                                    "threadId": "thr_fake_001",
                                    "turn": {{"id": "turn_fake_001", "status": "completed"}}
                                }}
                            }})
                        else:
                            if request_id is not None:
                                send({{"id": request_id, "error": {{"code": -32601, "message": method or "unknown"}}}})
                    """
                ),
                encoding="utf-8",
            )
            if os.name == "nt":
                (fake_bin / "codex.cmd").write_text(
                    f'@"{sys.executable}" "%~dp0fake_codex.py" %*\n',
                    encoding="utf-8",
                )
            else:
                fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

            env = {
                "CODEX_HOME": str(codex_home),
                "JAM_HOME": str(jam_home),
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                store = Store()
                campaign = store.create_campaign(
                    {
                        "id": "integration-campaign",
                        "name": "Integration campaign",
                        "objective": "Complete the fake bounded integration episode.",
                        "task_profile": "adaptive",
                        "workspace": str(workspace),
                        "operating_boundaries": {
                            "resources": ["temporary workspace"],
                            "excluded_actions": ["network", "production"],
                        },
                        "success_criteria": "The fake episode returns a valid complete handoff.",
                        "sandbox": "read-only",
                        "allow_network": False,
                        "max_episodes": 3,
                        "max_elapsed_minutes": 30,
                        "continuation_threshold": 0.55,
                        "max_low_progress": 2,
                        "max_subagents": 2,
                    }
                )
                result = run_campaign(campaign["id"])
                self.assertEqual(result, 0)

                completed = Store().get_campaign(campaign["id"])
                self.assertEqual(completed["status"], "completed")
                self.assertFalse(completed["enabled"])
                self.assertEqual(completed["episode_count"], 1)
                self.assertEqual(completed["last_thread_id"], "thr_fake_001")

                episode = Store().last_episode(campaign["id"])
                assert episode is not None
                self.assertEqual(episode["status"], "completed")
                self.assertEqual(episode["turn_status"], "completed")
                self.assertEqual(episode["handoff"]["status"], "complete")
                self.assertEqual(episode["task_profile_used"], "general")
                self.assertEqual(len(episode["agent_activity"]), 1)
                self.assertEqual(episode["agent_activity"][0]["agent_name"], "jam_reviewer")
                self.assertEqual(episode["agent_activity"][0]["event"], "completed")
                self.assertEqual(episode["model_events"][0]["method"], "model/rerouted")
                self.assertEqual(
                    episode["token_usage"]["tokenUsage"]["inputTokens"], 123
                )
                for key in ("prompt_path", "events_path", "final_path", "handoff_path"):
                    self.assertTrue(Path(episode[key]).exists(), key)
                episode_dir = Path(episode["prompt_path"]).parent
                for artifact in ("routing.json", "agent-activity.json", "model-events.json", "token-usage.json"):
                    self.assertTrue((episode_dir / artifact).exists(), artifact)
                self.assertEqual(
                    json.loads((episode_dir / "agent-activity.json").read_text(encoding="utf-8"))[0]["agent_name"],
                    "jam_reviewer",
                )
                self.assertEqual(
                    json.loads((episode_dir / "model-events.json").read_text(encoding="utf-8"))[0]["toModel"],
                    "gpt-5.6-terra",
                )
                self.assertEqual(
                    json.loads((episode_dir / "token-usage.json").read_text(encoding="utf-8"))["tokenUsage"]["outputTokens"],
                    45,
                )
                context_path = Path(episode["prompt_path"]).with_name("context.json")
                stderr_path = Path(episode["prompt_path"]).with_name("app-server.stderr.log")
                self.assertTrue(context_path.exists())
                self.assertTrue(stderr_path.exists())
                self.assertIn("Integration result", Path(episode["final_path"]).read_text(encoding="utf-8"))
                self.assertIn("OPERATING BOUNDARIES", Path(episode["prompt_path"]).read_text(encoding="utf-8"))
                self.assertIn("turn/completed", Path(episode["events_path"]).read_text(encoding="utf-8"))
                summary = jam_home / "campaigns" / campaign["id"] / "campaign.md"
                self.assertTrue(summary.exists())
                self.assertIn("thr_fake_001", summary.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
