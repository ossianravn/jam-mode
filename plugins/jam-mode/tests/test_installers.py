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
WINDOWS_INSTALLER = PLUGIN_ROOT / "scripts" / "install-windows.ps1"


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

    @unittest.skipUnless(os.name != "nt", "WSL installer test")
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
                    if args[:2] == ["plugin", "--help"]:
                        print("Commands:\\n  marketplace\\n  add\\n  remove\\n  help")
                        raise SystemExit(0)
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
                "jam-mode-local",
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
                ["plugin", "remove", "jam-mode", "-m", "jam-mode-local"],
                calls,
            )
            self.assertIn(
                ["plugin", "marketplace", "remove", "jam-mode-local"],
                calls,
            )

    @unittest.skipUnless(os.name == "nt", "Windows installer test")
    def test_windows_launcher_preserves_non_ascii_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            fake_codex_py = fake_bin / "fake_codex.py"
            fake_codex_py.write_text(
                textwrap.dedent(
                    """\
                    import json
                    import os
                    import sys

                    args = sys.argv[1:]
                    with open(os.environ["CODEX_FAKE_LOG"], "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(args) + "\\n")
                    if args[:2] == ["plugin", "--help"]:
                        print("Commands:\\n  marketplace\\n  help")
                        raise SystemExit(0)
                    if args[:3] == ["plugin", "marketplace", "add"]:
                        print("Added marketplace jam-mode-local")
                        raise SystemExit(0)
                    raise SystemExit(2)
                    """
                ),
                encoding="utf-8",
            )
            fake_codex_cmd = fake_bin / "codex.cmd"
            fake_codex_cmd.write_text(
                f'@"{sys.executable}" "%~dp0fake_codex.py" %*\n',
                encoding="utf-8",
            )
            destination = root / "markedsplads-æøå-安装"
            bin_dir = root / "værktøjer-工具"
            codex_home = root / "codex-home"
            log = root / "codex.log"
            env = os.environ.copy()
            env.update(
                {
                    "CODEX_HOME": str(codex_home),
                    "CODEX_FAKE_LOG": str(log),
                    "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )

            nested_destination = MARKETPLACE_ROOT / f".installer-nested-{os.getpid()}"
            blocked = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-File",
                    str(WINDOWS_INSTALLER),
                    "-Destination",
                    str(nested_destination),
                    "-BinDirectory",
                    str(bin_dir),
                ],
                cwd=MARKETPLACE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("must not be inside", blocked.stdout + blocked.stderr)
            self.assertFalse(nested_destination.exists())

            installed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-File",
                    str(WINDOWS_INSTALLER),
                    "-Destination",
                    str(destination),
                    "-BinDirectory",
                    str(bin_dir),
                ],
                cwd=MARKETPLACE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            launcher = (bin_dir / "jam.cmd").read_text(encoding="utf-8")
            self.assertIn(str(destination / "plugins" / "jam-mode"), launcher)
            self.assertIn('set "PYTHONUTF8=1"', launcher)
            self.assertNotIn("?", launcher)
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertIn(["plugin", "marketplace", "add", str(destination)], calls)
            self.assertFalse(any(call[:2] == ["plugin", "add"] for call in calls))
            self.assertFalse(any(call[:3] == ["plugin", "marketplace", "upgrade"] for call in calls))

            plugin_root = destination / "plugins" / "jam-mode"
            locker = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=plugin_root,
            )
            try:
                locked_upgrade = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-File",
                        str(WINDOWS_INSTALLER),
                        "-Destination",
                        str(destination),
                        "-BinDirectory",
                        str(bin_dir),
                    ],
                    cwd=MARKETPLACE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    check=False,
                )
            finally:
                locker.terminate()
                locker.wait(timeout=10)
            message = locked_upgrade.stdout + locked_upgrade.stderr
            self.assertNotEqual(locked_upgrade.returncode, 0)
            self.assertIn("existing installation was restored", message)
            self.assertTrue((plugin_root / ".codex-plugin" / "plugin.json").exists())
            self.assertFalse(any(root.glob("installed-marketplace.stage.*")))
            self.assertFalse(any(root.glob("installed-marketplace.old.*")))


if __name__ == "__main__":
    unittest.main()
