from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jam.controller import run_campaign
from jam.harnesses.routing import prepare_native_routing
from jam.harnesses.types import HarnessError, HarnessResult
from jam.memory import collect_memories
from jam.service import start_campaign
from jam.service_refresh import refresh_campaign_routing
from jam.store import Store, StoreError
from tests.collaboration_events import duo_events, final_event
from tests.test_controller_integration import FAKE_HANDOFF
from tests.test_store import campaign_config


class HarnessCampaignTests(unittest.TestCase):
    def test_native_memory_uses_explicit_sources_without_codex_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            codex = root / "codex"
            (codex / "memories").mkdir(parents=True)
            (codex / "memories" / "private.md").write_text("Codex history")
            explicit = root / "project.md"
            explicit.write_text("Explicit project context")
            with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
                memory = collect_memories({"harness": "claude-code", "memory_paths": [str(explicit)]}, "context")
            self.assertEqual([item["excerpt"] for item in memory["relevant_excerpts"]], ["Explicit project context"])

    def test_old_database_defaults_to_codex_and_harness_cannot_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Store(root / "jam.db")
            store.create_campaign(campaign_config(root, campaign_id="old", name="Old"))
            with store.connection() as connection:
                connection.execute("ALTER TABLE campaigns DROP COLUMN harness")
            migrated = Store(root / "jam.db")
            self.assertEqual(migrated.get_campaign("old")["harness"], "codex")
            with self.assertRaises((ValueError, StoreError)):
                migrated.update_campaign("old", harness="claude-code")

    def test_native_campaign_persists_refreshes_and_runs_through_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            adapter = Mock()
            adapter.inspect.return_value = {"available": True, "supported": True}
            text = json.dumps(FAKE_HANDOFF)

            def run(request):
                self.assertEqual(request.campaign["harness"], "claude-code")
                request.events_path.write_text("\n".join(json.dumps(e) for e in duo_events() + [final_event(text)]))
                return HarnessResult(session_id="thr_fake_001", turn_id="turn_fake_001",
                                     status="completed", final_text=text)

            adapter.run.side_effect = run
            with patch.dict(os.environ, {"JAM_HOME": str(root / "state"), "CODEX_HOME": str(root / "codex")}), \
                    patch("jam.harnesses.routing.get_adapter", return_value=adapter), \
                    patch("jam.harnesses.registry.get_adapter", return_value=adapter), \
                    patch("jam.service.spawn_controller", return_value=123), \
                    patch("jam.campaign_runner.ensure_managed_agents", side_effect=AssertionError("Codex configuration leaked")):
                created = start_campaign(objective="Test native adapter", workspace=folder, harness="claude-code",
                                         model="claude-opus-4-6", max_episodes=1)
                identifier = created["campaign"]["id"]
                store = Store()
                store.transition_campaign(identifier, "paused")
                refreshed = refresh_campaign_routing(identifier)
                self.assertEqual(refreshed["campaign"]["harness"], "claude-code")
                self.assertEqual(refreshed["resolved"]["parent"]["model"], "claude-opus-4-6")
                store.transition_campaign(identifier, "queued")
                self.assertEqual(run_campaign(identifier), 0)
                self.assertEqual(store.get_campaign(identifier)["status"], "completed")
                self.assertEqual(adapter.run.call_count, 1)

    def test_unsupported_native_adapter_refuses_before_campaign_creation(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"JAM_HOME": folder}), \
                patch("jam.harnesses.routing.get_adapter") as get_adapter:
            get_adapter.return_value.inspect.return_value = {
                "available": True, "supported": False, "limitations": ["Unsupported installed version"]}
            with self.assertRaisesRegex(HarnessError, "Unsupported installed version"):
                start_campaign(objective="Task", workspace=folder, harness="copilot")
            self.assertEqual(Store().list_campaigns(), [])

    def test_native_routing_rejects_codex_presets(self):
        with patch("jam.harnesses.routing.get_adapter") as get_adapter:
            get_adapter.return_value.inspect.return_value = {"available": True, "supported": True}
            with self.assertRaisesRegex(HarnessError, "Codex presets"):
                prepare_native_routing(harness="claude-code", model_policy="balanced")
