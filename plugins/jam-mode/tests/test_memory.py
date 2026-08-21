from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.context import collect_memories


class MemoryBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex_home = self.root / "codex-home"
        self.jam_home = self.root / "jam-home"
        self.env = patch.dict(
            os.environ,
            {"CODEX_HOME": str(self.codex_home), "JAM_HOME": str(self.jam_home)},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_memory_inventory_filters_common_secrets_and_symlinks(self) -> None:
        memories = self.codex_home / "memories"
        memories.mkdir(parents=True)
        safe = memories / "configuration-parser-notes.md"
        safe.write_text("The parser must retain the legacy key aliases.", encoding="utf-8")
        secret = memories / "auth.json"
        secret.write_text('{"token":"do-not-read"}', encoding="utf-8")
        alias = memories / "innocent.json"
        try:
            alias.symlink_to(secret)
        except OSError:
            alias = None

        campaign = {
            "objective": "Implement a configuration parser.",
            "memory_paths": [],
        }
        result = collect_memories(campaign, "Preserve legacy parser aliases")
        paths = {item["path"] for item in result["inventory"]}
        self.assertIn(str(safe.resolve()), paths)
        self.assertNotIn(str(secret.resolve()), paths)
        if alias is not None:
            self.assertNotIn(str(alias.resolve()), paths)
        excerpts = "\n".join(item["excerpt"] for item in result["relevant_excerpts"])
        self.assertIn("legacy key aliases", excerpts)
        self.assertNotIn("do-not-read", excerpts)

    def test_memory_symlink_cannot_escape_configured_root(self) -> None:
        memories = self.codex_home / "memories"
        memories.mkdir(parents=True)
        outside = self.root / "private-notes.md"
        outside.write_text("outside-root-secret", encoding="utf-8")
        alias = memories / "apparently-safe.md"
        try:
            alias.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"File symlinks are unavailable: {exc}")

        result = collect_memories(
            {"objective": "Read safe memories", "memory_paths": []},
            "Inspect notes",
        )

        paths = {item["path"] for item in result["inventory"]}
        excerpts = "\n".join(
            item["excerpt"] for item in result["relevant_excerpts"]
        )
        self.assertNotIn(str(outside.resolve()), paths)
        self.assertNotIn("outside-root-secret", excerpts)


if __name__ == "__main__":
    unittest.main()
