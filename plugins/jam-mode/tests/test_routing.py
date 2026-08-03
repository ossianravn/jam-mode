from __future__ import annotations

import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.routing import (
    CHILD_ROLES,
    MANAGED_AGENT_MARKER,
    RoutingError,
    build_requested_routing,
    ensure_managed_agents,
    inspect_managed_agents,
    load_routing_config,
    remove_managed_agents,
    resolve_routing,
    save_routing_config,
)
from jam.service import configure_model_routing, refresh_campaign_routing
from jam.store import Store


def model_entry(model_id: str, efforts: list[str], default: str = "medium") -> dict:
    return {
        "id": model_id,
        "model": model_id,
        "displayName": model_id,
        "defaultReasoningEffort": default,
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort} for effort in efforts
        ],
        "hidden": False,
    }


class RoutingTests(unittest.TestCase):
    def test_balanced_policy_routes_named_roles(self) -> None:
        requested = build_requested_routing(policy="balanced", validation="off")
        self.assertEqual(requested["parent"]["model"], "gpt-5.6-sol")
        self.assertEqual(requested["roles"]["explorer"]["model"], "gpt-5.6-luna")
        self.assertEqual(requested["roles"]["implementer"]["model"], "gpt-5.6-terra")
        self.assertEqual(requested["roles"]["reviewer"]["model"], "gpt-5.6-sol")
        self.assertEqual(requested["roles"]["reviewer"]["agent"], "jam_reviewer")
        self.assertEqual(requested["strategy_routes"]["builder_reviewer"], ["implementer", "reviewer"])

    def test_strict_and_fallback_effort_validation(self) -> None:
        requested = build_requested_routing(
            policy="inherit",
            validation="strict",
            parent_model="model-a",
            parent_effort="max",
        )
        catalog = [model_entry("model-a", ["low", "medium", "high", "xhigh"], "high")]
        with self.assertRaisesRegex(RoutingError, "supported efforts"):
            resolve_routing(requested, catalog_entries=catalog)

        requested["validation"] = "fallback"
        resolved = resolve_routing(requested, catalog_entries=catalog)
        self.assertEqual(resolved["parent"]["model"], "model-a")
        self.assertEqual(resolved["parent"]["effort"], "xhigh")
        self.assertTrue(any("unsupported" in item for item in resolved["warnings"]))

    def test_inherited_model_effort_is_validated_against_catalog_default(self) -> None:
        requested = build_requested_routing(
            policy="inherit",
            validation="fallback",
            parent_effort="max",
            role_efforts={"reviewer": "max"},
        )
        default_model = model_entry(
            "default-model", ["low", "medium", "high"], "medium"
        )
        default_model["isDefault"] = True
        resolved = resolve_routing(requested, catalog_entries=[default_model])
        self.assertIsNone(resolved["parent"]["model"])
        self.assertEqual(resolved["parent"]["effort"], "high")
        self.assertEqual(
            resolved["parent"]["validated_against_model"], "default-model"
        )
        self.assertIsNone(resolved["roles"]["reviewer"]["model"])
        self.assertEqual(resolved["roles"]["reviewer"]["effort"], "high")
        self.assertEqual(
            resolved["roles"]["reviewer"]["validated_against_model"],
            "default-model",
        )

    def test_unavailable_models_fall_back_by_role(self) -> None:
        requested = build_requested_routing(policy="balanced", validation="fallback")
        catalog = [
            model_entry("gpt-5.6-terra", ["low", "medium", "high"], "medium"),
            model_entry("gpt-5.6-luna", ["low", "medium"], "medium"),
        ]
        resolved = resolve_routing(requested, catalog_entries=catalog)
        self.assertEqual(resolved["parent"]["model"], "gpt-5.6-terra")
        self.assertEqual(resolved["roles"]["reviewer"]["model"], "gpt-5.6-terra")
        self.assertTrue(any("unavailable" in item for item in resolved["warnings"]))

    def test_child_ultra_is_blocked_by_default(self) -> None:
        requested = build_requested_routing(
            policy="inherit",
            validation="fallback",
            role_models={"reviewer": "model-a"},
            role_efforts={"reviewer": "ultra"},
            allow_child_ultra=False,
        )
        catalog = [model_entry("model-a", ["high", "xhigh", "max", "ultra"], "high")]
        resolved = resolve_routing(requested, catalog_entries=catalog)
        self.assertEqual(resolved["roles"]["reviewer"]["effort"], "max")
        self.assertTrue(any("Ultra is disabled" in item for item in resolved["warnings"]))

        strict = build_requested_routing(
            policy="inherit",
            validation="strict",
            role_models={"reviewer": "model-a"},
            role_efforts={"reviewer": "ultra"},
            allow_child_ultra=False,
        )
        with self.assertRaisesRegex(RoutingError, "Ultra is disabled"):
            resolve_routing(strict, catalog_entries=catalog)


    def test_hidden_exact_model_is_allowed_with_warning(self) -> None:
        requested = build_requested_routing(
            policy="inherit",
            validation="strict",
            parent_model="hidden-model",
            parent_effort="high",
        )
        hidden = model_entry("hidden-model", ["medium", "high"], "medium")
        hidden["hidden"] = True
        resolved = resolve_routing(requested, catalog_entries=[hidden])
        self.assertEqual(resolved["parent"]["model"], "hidden-model")
        self.assertTrue(any("hidden" in item for item in resolved["warnings"]))

    def test_parent_ultra_requires_separate_opt_in(self) -> None:
        catalog = [model_entry("model-a", ["high", "max", "ultra"], "high")]
        blocked = build_requested_routing(
            policy="inherit",
            validation="fallback",
            parent_model="model-a",
            parent_effort="ultra",
            allow_parent_ultra=False,
        )
        resolved = resolve_routing(blocked, catalog_entries=catalog)
        self.assertEqual(resolved["parent"]["effort"], "max")
        self.assertTrue(any("Ultra is disabled" in item for item in resolved["warnings"]))

        allowed = build_requested_routing(
            policy="inherit",
            validation="strict",
            parent_model="model-a",
            parent_effort="ultra",
            allow_parent_ultra=True,
        )
        resolved = resolve_routing(allowed, catalog_entries=catalog)
        self.assertEqual(resolved["parent"]["effort"], "ultra")


    def test_ultra_child_agent_gets_bounded_nested_delegation_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex"
            workspace = root / "workspace"
            workspace.mkdir()
            requested = build_requested_routing(
                policy="inherit",
                validation="off",
                role_models={"reviewer": "model-a"},
                role_efforts={"reviewer": "ultra"},
                allow_child_ultra=True,
            )
            resolved = resolve_routing(requested, catalog_entries=[])
            paths = ensure_managed_agents(
                resolved, codex_home=codex_home, workspace=workspace
            )
            parsed = tomllib.loads(
                Path(paths["reviewer"]).read_text(encoding="utf-8")
            )
            instructions = parsed["developer_instructions"]
            self.assertIn("Ultra nested delegation is explicitly enabled", instructions)
            self.assertIn("most one read-only helper", instructions)
            self.assertNotIn("Do not spawn additional agents.", instructions)
            explorer = tomllib.loads(
                Path(paths["explorer"]).read_text(encoding="utf-8")
            )
            self.assertIn(
                "Do not spawn additional agents.",
                explorer["developer_instructions"],
            )

    def test_managed_agents_are_safe_and_removable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex"
            workspace = root / "workspace"
            workspace.mkdir()
            resolved = resolve_routing(
                build_requested_routing(policy="balanced", validation="off"),
                catalog_entries=[],
            )
            paths = ensure_managed_agents(
                resolved, codex_home=codex_home, workspace=workspace
            )
            self.assertEqual(set(paths), set(CHILD_ROLES))
            reviewer = Path(paths["reviewer"])
            text = reviewer.read_text(encoding="utf-8")
            self.assertIn(MANAGED_AGENT_MARKER, text)
            self.assertIn('name = "jam_reviewer"', text)
            self.assertIn('model = "gpt-5.6-sol"', text)
            self.assertIn('model_reasoning_effort = "high"', text)
            self.assertIn('sandbox_mode = "read-only"', text)
            parsed = tomllib.loads(text)
            self.assertEqual(parsed["name"], "jam_reviewer")
            self.assertEqual(parsed["model"], "gpt-5.6-sol")
            self.assertEqual(parsed["model_reasoning_effort"], "high")
            self.assertIn("Do not edit files", parsed["developer_instructions"])
            self.assertTrue(inspect_managed_agents(codex_home)["ok"])

            removed = remove_managed_agents(codex_home)
            self.assertEqual(len(removed), len(CHILD_ROLES))
            self.assertFalse(reviewer.exists())

    def test_non_jam_and_project_agent_collisions_are_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex"
            agents = codex_home / "agents"
            agents.mkdir(parents=True)
            collision = agents / "jam_reviewer.toml"
            collision.write_text('name = "mine"\n', encoding="utf-8")
            resolved = resolve_routing(
                build_requested_routing(policy="inherit", validation="off"),
                catalog_entries=[],
            )
            with self.assertRaisesRegex(RoutingError, "Refusing to overwrite"):
                ensure_managed_agents(resolved, codex_home=codex_home)
            self.assertEqual(collision.read_text(encoding="utf-8"), 'name = "mine"\n')

            collision.unlink()
            workspace = root / "workspace"
            project_agents = workspace / ".codex" / "agents"
            project_agents.mkdir(parents=True)
            (project_agents / "jam_explorer.toml").write_text(
                'name = "project_override"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(RoutingError, "Project-scoped custom agents"):
                ensure_managed_agents(
                    resolved, codex_home=codex_home, workspace=workspace
                )

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
                campaign = store.update_campaign(
                    campaign["id"], status="paused", enabled=False
                )

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
                    configured["campaign"]["model"], "gpt-5.6-sol"
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
                    "gpt-5.6-sol",
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
