from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.routing import (
    CHILD_ROLES,
    build_requested_routing,
    load_routing_config,
    resolve_routing,
    save_routing_config,
)
from jam.service import configure_model_routing, refresh_campaign_routing
from jam.store import Store


class RoutingServiceTests(unittest.TestCase):
    def test_paused_campaign_routing_can_be_reconfigured_and_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex"
            jam_home = root / "jam"
            workspace = root / "workspace"
            workspace.mkdir()
            with patch.dict(
                os.environ,
                {"CODEX_HOME": str(codex_home), "JAM_HOME": str(jam_home)},
                clear=False,
            ):
                requested = build_requested_routing(
                    policy="inherit", validation="off"
                )
                resolved = resolve_routing(requested, catalog_entries=[])
                store = Store()
                campaign = store.create_campaign(
                    {
                        "id": "routing-campaign",
                        "name": "Routing campaign",
                        "objective": "Exercise campaign routing updates.",
                        "task_profile": "adaptive",
                        "workspace": str(workspace),
                        "operating_boundaries": {"resources": [str(workspace)]},
                        "success_criteria": "Routing is persisted.",
                        "model_policy": "inherit",
                        "model_validation": "off",
                        "requested_routing": requested,
                        "resolved_routing": resolved,
                        "sandbox": "read-only",
                        "allow_network": False,
                        "max_episodes": 3,
                        "max_elapsed_minutes": 30,
                        "continuation_threshold": 0.55,
                        "max_low_progress": 2,
                        "max_subagents": 2,
                    }
                )
                campaign = store.transition_campaign(campaign["id"], "paused")

                configured = configure_model_routing(
                    campaign["id"],
                    model_policy="balanced",
                    role_models={"explorer": "custom-luna"},
                    role_efforts={"explorer": "medium"},
                    validate=False,
                )
                self.assertEqual(configured["scope"], "campaign")
                self.assertEqual(
                    configured["campaign"]["resolved_routing"]["roles"]["explorer"]["model"],
                    "custom-luna",
                )
                self.assertEqual(
                    configured["campaign"]["model"], "gpt-6-astra"
                )

                refreshed = refresh_campaign_routing(
                    campaign["id"], validate=False
                )
                self.assertEqual(refreshed["scope"], "campaign")
                self.assertEqual(
                    refreshed["campaign"]["resolved_routing"]["roles"]["explorer"]["model"],
                    "custom-luna",
                )
                self.assertTrue(
                    (codex_home / "agents" / "jam_explorer.toml").exists()
                )

                quality = configure_model_routing(
                    campaign["id"],
                    model_policy="quality",
                    validate=False,
                )
                # Changing a policy must replace preset-derived values while
                # retaining genuine campaign overrides.
                self.assertEqual(
                    quality["campaign"]["resolved_routing"]["parent"]["effort"],
                    "max",
                )
                self.assertEqual(
                    quality["campaign"]["resolved_routing"]["roles"]["implementer"]["model"],
                    "gpt-6-astra",
                )
                self.assertEqual(
                    quality["campaign"]["resolved_routing"]["roles"]["explorer"]["model"],
                    "custom-luna",
                )

    def test_config_round_trip_and_global_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex"
            jam_home = root / "jam"
            with patch.dict(
                os.environ,
                {"CODEX_HOME": str(codex_home), "JAM_HOME": str(jam_home)},
                clear=False,
            ):
                saved = save_routing_config(
                    {
                        "policy": "custom",
                        "validation": "off",
                        "allow_child_ultra": False,
                        "allow_parent_ultra": True,
                        "parent": {"model": "parent-model", "effort": "xhigh"},
                        "roles": {"explorer": {"model": "fast-model", "effort": "low"}},
                    }
                )
                loaded = load_routing_config(create=False)
                self.assertEqual(loaded, saved)
                result = configure_model_routing(
                    model_policy="balanced",
                    role_models={"explorer": "custom-luna"},
                    role_efforts={"explorer": "medium"},
                    validate=False,
                )
                self.assertEqual(result["config"]["policy"], "balanced")
                self.assertEqual(result["resolved"]["roles"]["explorer"]["model"], "custom-luna")
                self.assertEqual(len(result["managed_agents"]), len(CHILD_ROLES))
                self.assertTrue((codex_home / "agents" / "jam_explorer.toml").exists())


if __name__ == "__main__":
    unittest.main()
