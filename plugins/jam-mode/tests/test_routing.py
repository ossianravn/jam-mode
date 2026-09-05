from __future__ import annotations

import unittest

from jam.cli_output import _parse_assignments
from jam.routing import (
    RoutingError,
    build_requested_routing,
    default_routing_config,
    merge_routing_config,
    resolve_routing,
)


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
        self.assertEqual(requested["parent"]["model"], "gpt-6-astra")
        self.assertEqual(requested["roles"]["explorer"]["model"], "gpt-6-astra")
        self.assertEqual(requested["roles"]["implementer"]["model"], "gpt-6-astra")
        self.assertEqual(requested["roles"]["reviewer"]["model"], "gpt-6-astra")
        self.assertEqual(requested["roles"]["reviewer"]["agent"], "jam_reviewer")
        self.assertEqual(requested["strategy_routes"]["builder_reviewer"], ["implementer", "reviewer"])

    def test_presets_require_gpt6_without_implicit_fallback(self) -> None:
        self.assertEqual(default_routing_config()["validation"], "strict")
        for policy in ("economy", "balanced", "quality"):
            with self.subTest(policy=policy):
                requested = build_requested_routing(policy=policy)
                self.assertEqual(requested["validation"], "strict")
                roster = [requested["parent"], *requested["roles"].values()]
                self.assertEqual({role["model"] for role in roster}, {"gpt-6-astra"})
                with self.assertRaises(RoutingError):
                    resolve_routing(requested, catalog_entries=[
                        model_entry("gpt-5.6-sol", ["low", "medium", "high", "max"])
                    ])
                resolved = resolve_routing(requested, catalog_entries=[
                    model_entry("gpt-6-astra", ["low", "medium", "high", "max"])
                ])
                self.assertEqual(resolved["warnings"], [])

    def test_parent_overrides_require_dedicated_channel(self) -> None:
        with self.assertRaisesRegex(RoutingError, "dedicated 'model' argument"):
            build_requested_routing(role_models={"parent": "wrong-channel"})
        with self.assertRaisesRegex(RoutingError, "dedicated 'effort' argument"):
            merge_routing_config(
                {},
                role_efforts={"parent": "high"},
            )

        with self.assertRaisesRegex(ValueError, "use --model"):
            _parse_assignments(
                ["parent=wrong-channel"],
                label="--role-model",
            )
        with self.assertRaisesRegex(ValueError, "use --effort"):
            _parse_assignments(
                ["parent=high"],
                label="--role-effort",
            )

        requested = build_requested_routing(
            policy="inherit",
            parent_model="parent-model",
            parent_effort="high",
            role_models={"reviewer": "review-model"},
            role_efforts={"reviewer": "medium"},
        )
        self.assertEqual(requested["parent"]["model"], "parent-model")
        self.assertEqual(requested["parent"]["effort"], "high")
        self.assertEqual(requested["roles"]["reviewer"]["model"], "review-model")
        self.assertEqual(requested["roles"]["reviewer"]["effort"], "medium")

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

if __name__ == "__main__":
    unittest.main()
