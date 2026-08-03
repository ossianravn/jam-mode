from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_ROOT = PLUGIN_ROOT.parents[1]
INSTALLER = PLUGIN_ROOT / "scripts" / "install-wsl.sh"
UNINSTALLER = PLUGIN_ROOT / "scripts" / "uninstall-wsl.sh"


class InstallerTests(unittest.TestCase):
    def test_companion_launcher_wins_over_scripts_directory_with_pythonpath(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(PLUGIN_ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "jam.py"), "--help"],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("JAM Mode campaign controller", result.stdout)

    def test_wsl_installer_and_uninstaller_with_fake_codex(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            log = root / "codex.log"
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys
                    with open(os.environ["CODEX_FAKE_LOG"], "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(sys.argv[1:]) + "\\n")
                    args = sys.argv[1:]
                    if args[:3] == ["plugin", "marketplace", "add"]:
                        print(json.dumps({"marketplaceName": "jam-mode-local-test"}))
                        raise SystemExit(0)
                    if args[:2] == ["app-server", "--help"]:
                        print("fake app-server")
                        raise SystemExit(0)
                    if args and args[0] == "plugin":
                        print("{}")
                        raise SystemExit(0)
                    raise SystemExit(2)
                    """
                ),
                encoding="utf-8",
            )
            fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

            home = root / "home"
            codex_home = root / "codex-home"
            destination = root / "installed-marketplace"
            bin_dir = root / "bin"
            home.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "CODEX_HOME": str(codex_home),
                    "JAM_MARKETPLACE_HOME": str(destination),
                    "JAM_BIN_DIR": str(bin_dir),
                    "CODEX_FAKE_LOG": str(log),
                    "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            installed = subprocess.run(
                ["bash", str(INSTALLER)],
                cwd=MARKETPLACE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            plugin = destination / "plugins" / "jam-mode"
            self.assertTrue((plugin / ".codex-plugin" / "plugin.json").exists())
            self.assertEqual(
                (destination / ".jam-marketplace-name").read_text(encoding="utf-8").strip(),
                "jam-mode-local-test",
            )
            config = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
            launcher = Path(config["mcpServers"]["jam_mode"]["args"][0])
            self.assertTrue(launcher.is_absolute())
            self.assertEqual(launcher, plugin / "mcp" / "jam_mcp.py")
            jam_command = bin_dir / "jam"
            self.assertTrue(jam_command.exists())
            self.assertTrue(jam_command.stat().st_mode & stat.S_IXUSR)
            agents_dir = codex_home / "agents"
            managed_agents = sorted(agents_dir.glob("jam_*.toml"))
            self.assertEqual(len(managed_agents), 9)
            self.assertTrue(all("# JAM_MODE_MANAGED=1" in item.read_text(encoding="utf-8") for item in managed_agents))
            self.assertTrue((codex_home / "jam-mode" / "config.toml").exists())

            listing = subprocess.run(
                [str(jam_command), "--json", "list"],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual(json.loads(listing.stdout)["campaigns"], [])

            removed = subprocess.run(
                ["bash", str(UNINSTALLER)],
                cwd=MARKETPLACE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            self.assertFalse(destination.exists())
            self.assertFalse(jam_command.exists())
            self.assertFalse(any((codex_home / "agents").glob("jam_*.toml")))
            self.assertTrue((codex_home / "jam-mode" / "config.toml").exists())
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertIn(
                ["plugin", "remove", "jam-mode", "-m", "jam-mode-local-test", "--json"],
                calls,
            )
            self.assertIn(
                ["plugin", "marketplace", "remove", "jam-mode-local-test", "--json"],
                calls,
            )


if __name__ == "__main__":
    unittest.main()
