from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.cli import main
from jam.service import resume_campaign
from jam.store import Store, StoreError


class ResumptionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {
            "JAM_HOME": str(self.root / "jam"), "CODEX_HOME": str(self.root / "codex"),
            "JAM_CHILD_SESSION": "0",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = Store()

    def legacy_campaign(self, identifier):
        campaign = self.store.create_campaign({
            "id": identifier, "name": identifier, "objective": "Finish existing work",
            "workspace": str(self.workspace), "max_subagents": 1,
            "max_episodes": 7, "model_validation": "off",
        })
        episode = self.store.create_episode(identifier, objective="Previous work", strategy_hint="solo")
        self.store.finish_episode(episode["id"], status="completed", turn_status="completed",
                                  final_text="Preserve the previous result", handoff={"summary": "Existing work"})
        return self.store.transition_campaign(campaign["id"], "paused")

    def test_cli_and_mcp_upgrade_existing_campaign_preserving_history_and_charter(self):
        for entry in ("cli", "mcp"):
            with self.subTest(entry=entry):
                before = self.legacy_campaign(entry)
                episode = self.store.last_episode(entry)
                with patch("jam.service_campaigns.spawn_controller", return_value=123) as spawn:
                    if entry == "cli":
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(main(["resume", entry, "--max-subagents", "2"]), 0)
                    else:
                        path = Path(__file__).resolve().parents[1] / "mcp" / "jam_mcp.py"
                        spec = importlib.util.spec_from_file_location("jam_resume_test_mcp", path)
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        tool = next(t for t in module.TOOLS if t["name"] == "jam_resume_campaign")
                        self.assertEqual(tool["inputSchema"]["properties"]["max_subagents"]["minimum"], 2)
                        payload, _ = module._invoke("jam_resume_campaign", {"campaign_id": entry, "max_subagents": 2})
                        self.assertEqual(payload["campaign"]["id"], entry)
                    spawn.assert_called_once_with(entry)
                after = self.store.get_campaign(entry)
                self.assertEqual(after["max_subagents"], 2)
                self.assertEqual(after["status"], "queued")
                for field in ("id", "objective", "episode_count", "max_episodes", "started_at"):
                    self.assertEqual(after[field], before[field], field)
                self.assertEqual(self.store.last_episode(entry), episode)
                charter = json.loads((self.root / "jam" / "campaigns" / entry / "charter.json").read_text())
                self.assertEqual(charter["policy"]["max_subagents"], 2)
                self.store.transition_campaign(entry, "paused")

    def test_invalid_or_live_resume_does_not_change_state_or_launch(self):
        before = self.legacy_campaign("blocked")
        with patch("jam.service_campaigns.spawn_controller") as spawn, patch("jam.service_campaigns.refresh_campaign_routing") as refresh:
            for limit in (None, 1, 17):
                with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "Duo requires"):
                    resume_campaign("blocked", max_subagents=limit, guidance="Do not persist invalid input")
                self.assertEqual(self.store.get_campaign("blocked"), before)
            before = self.store.transition_campaign("blocked", "queued")
            with self.assertRaises(StoreError):
                resume_campaign("blocked", max_subagents=2, guidance="Do not change live work")
            self.assertEqual(self.store.get_campaign("blocked"), before)
            spawn.assert_not_called()
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
