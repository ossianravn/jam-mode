from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from jam.routing import (
    CHILD_ROLES,
    MANAGED_AGENT_MARKER,
    RoutingError,
    build_requested_routing,
    ensure_managed_agents,
    inspect_managed_agents,
    remove_managed_agents,
    resolve_routing,
)


class RoutingAgentTests(unittest.TestCase):
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
            self.assertIn('model = "gpt-6-astra"', text)
            self.assertIn('model_reasoning_effort = "high"', text)
            self.assertIn('sandbox_mode = "read-only"', text)
            parsed = tomllib.loads(text)
            self.assertEqual(parsed["name"], "jam_reviewer")
            self.assertEqual(parsed["model"], "gpt-6-astra")
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
            self.assertEqual(list(agents.glob("jam_*.toml")), [collision])
            self.assertFalse(
                (codex_home / "jam-mode" / "agents-manifest.json").exists()
            )

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


if __name__ == "__main__":
    unittest.main()
