from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.service import _boundary_value, configure_model_routing, start_campaign
from jam.store import Store, StoreError


class ServiceProfileTests(unittest.TestCase):
    def test_conservative_boundaries_are_inferred_for_local_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td).resolve()
            boundaries = _boundary_value(
                None,
                workspace=workspace,
                sandbox="workspace-write",
                allow_network=False,
            )
            self.assertEqual(boundaries["source"], "conservative_default")
            self.assertIn(str(workspace), boundaries["resources"])
            self.assertTrue(
                any("modify files" in item.lower() for item in boundaries["allowed_actions"])
            )
            self.assertTrue(
                any("network access" in item.lower() for item in boundaries["approval_required_for"])
            )

    def test_network_requires_explicit_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "required when network access is enabled"):
                _boundary_value(
                    None,
                    workspace=Path(td),
                    sandbox="read-only",
                    allow_network=True,
                )

    def test_start_campaign_persists_profile_and_task_neutral_charter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            codex_home = root / "codex"
            jam_home = root / "jam"
            with patch.dict(
                os.environ,
                {"CODEX_HOME": str(codex_home), "JAM_HOME": str(jam_home)},
                clear=False,
            ), patch("jam.service.spawn_controller", return_value=4242), patch(
                "jam.routing_installed.fetch_installed_model_catalog",
                return_value=[{
                    "id": "gpt-6-astra",
                    "defaultReasoningEffort": "medium",
                    "supportedReasoningEfforts": ["low", "medium", "high", "max"],
                }],
            ):
                result = start_campaign(
                    objective="Draft and verify a migration guide.",
                    workspace=str(workspace),
                    task_profile="documentation",
                    operating_boundaries={
                        "resources": [str(workspace)],
                        "allowed_actions": ["read repository", "write documentation"],
                        "excluded_actions": ["modify application code", "publish externally"],
                    },
                    sandbox="workspace-write",
                    max_episodes=4,
                )

            campaign = result["campaign"]
            self.assertEqual(result["controller_pid"], 4242)
            self.assertEqual(campaign["task_profile"], "documentation")
            self.assertIn("write documentation", campaign["operating_boundaries"]["allowed_actions"])
            charter_path = jam_home / "campaigns" / campaign["id"] / "charter.json"
            charter = json.loads(charter_path.read_text(encoding="utf-8"))
            self.assertEqual(charter["schema_version"], 3)
            self.assertEqual(charter["task_profile"], "documentation")
            self.assertIn("operating_boundaries", charter)
            self.assertNotIn("authorized_scope", charter)
            self.assertIn("model_routing", charter)
            self.assertEqual(charter["model_routing"]["resolved"]["policy"], "balanced")
            self.assertIn("reviewer", charter["model_routing"]["managed_agents"])


    def test_paused_campaign_routing_can_change_but_live_campaign_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            codex_home = root / "codex"
            jam_home = root / "jam"
            with patch.dict(
                os.environ,
                {"CODEX_HOME": str(codex_home), "JAM_HOME": str(jam_home)},
                clear=False,
            ):
                store = Store()
                campaign = store.create_campaign(
                    {
                        "id": "routing-update-campaign",
                        "name": "Routing update",
                        "objective": "Exercise paused campaign routing.",
                        "task_profile": "adaptive",
                        "workspace": str(workspace),
                        "operating_boundaries": {"resources": [str(workspace)]},
                        "sandbox": "read-only",
                    }
                )
                campaign = store.transition_campaign(campaign["id"], "paused")
                result = configure_model_routing(
                    campaign["id"],
                    model_policy="custom",
                    model_validation="off",
                    model="parent-model",
                    effort="high",
                    role_models={"reviewer": "review-model"},
                    role_efforts={"reviewer": "xhigh"},
                    validate=False,
                )
                self.assertEqual(result["scope"], "campaign")
                self.assertEqual(result["campaign"]["model"], "parent-model")
                self.assertEqual(
                    result["campaign"]["resolved_routing"]["roles"]["reviewer"]["model"],
                    "review-model",
                )
                store.transition_campaign(campaign["id"], "queued")
                with self.assertRaisesRegex(StoreError, "Pause the campaign"):
                    configure_model_routing(
                        campaign["id"],
                        role_efforts={"reviewer": "high"},
                        validate=False,
                    )

                store.transition_campaign(campaign["id"], "paused")
                other = store.create_campaign(
                    {
                        "id": "other-live-campaign",
                        "name": "Other live campaign",
                        "objective": "Keep the shared agent roster stable.",
                        "task_profile": "adaptive",
                        "workspace": str(workspace),
                        "operating_boundaries": {"resources": [str(workspace)]},
                        "sandbox": "read-only",
                    }
                )
                self.assertTrue(other["enabled"])
                with self.assertRaisesRegex(StoreError, "shared by the single live campaign"):
                    configure_model_routing(
                        campaign["id"],
                        role_efforts={"reviewer": "high"},
                        validate=False,
                    )

    def test_invalid_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "task_profile must be one of"):
                start_campaign(
                    objective="Do a task.",
                    workspace=td,
                    task_profile="telepathy",
                    operating_boundaries={"resources": [td]},
                )


if __name__ == "__main__":
    unittest.main()
