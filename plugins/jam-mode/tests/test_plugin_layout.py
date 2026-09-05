from __future__ import annotations

import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_ROOT = PLUGIN_ROOT.parents[1]


class PluginLayoutTests(unittest.TestCase):
    def test_manifest_marketplace_and_mcp_paths(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "jam-mode")
        self.assertRegex(manifest["version"], r"^0\.3\.2(?:\+codex\.[a-z0-9-]+)?$")
        self.assertEqual(manifest["author"]["name"], manifest["interface"]["developerName"])
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
            "capabilities",
        ):
            self.assertTrue(manifest["interface"].get(field), field)
        prompts = manifest["interface"].get("defaultPrompt", [])
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in prompts))
        self.assertTrue((PLUGIN_ROOT / manifest["skills"]).is_dir())
        self.assertTrue((PLUGIN_ROOT / manifest["mcpServers"]).is_file())

        marketplace = json.loads(
            (MARKETPLACE_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "jam-mode")
        source = (MARKETPLACE_ROOT / entry["source"]["path"]).resolve()
        self.assertEqual(source, PLUGIN_ROOT.resolve())

        mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertNotIn("mcp_servers", mcp)
        self.assertIn("jam_mode", mcp["mcpServers"])
        self.assertTrue((PLUGIN_ROOT / "mcp" / "jam_mcp.py").is_file())
        self.assertTrue((PLUGIN_ROOT / "scripts" / "validate_plugin.py").is_file())
        references = PLUGIN_ROOT / "skills" / "jam-mode" / "references"
        self.assertTrue((references / "task-profiles.md").is_file())
        self.assertTrue((references / "operating-boundaries.md").is_file())
        self.assertTrue((references / "model-routing.md").is_file())


if __name__ == "__main__":
    unittest.main()
