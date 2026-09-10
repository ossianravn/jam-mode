from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows installer")
class WindowsInstallerCacheTests(unittest.TestCase):
    def test_reinstall_versions_windows_configuration_and_cached_server_starts(self):
        plugin = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source_plugin = source / "plugins" / "jam-mode"
            shutil.copytree(plugin, source_plugin, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(plugin.parents[1] / ".agents", source / ".agents")
            original = json.loads((source_plugin / ".codex-plugin/plugin.json").read_text())["version"]
            destination = root / "windows install"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            # Model the host's version-keyed cache: an existing version is reused.
            (fake_bin / "codex.py").write_text(textwrap.dedent('''\
                import json, os, shutil, sys
                from pathlib import Path
                args = sys.argv[1:]
                if args == ["plugin", "--help"]:
                    print("Commands:\\n  add  Install a plugin")
                elif args[:3] == ["plugin", "marketplace", "add"]:
                    pass
                elif args[:2] == ["plugin", "add"]:
                    source = Path(os.environ["TEST_DESTINATION"]) / "plugins/jam-mode"
                    version = json.loads((source / ".codex-plugin/plugin.json").read_text())["version"]
                    cache = Path(os.environ["CODEX_HOME"]) / "cache" / version
                    if not cache.exists():
                        shutil.copytree(source, cache)
                else:
                    raise SystemExit(2)
            '''), encoding="utf-8")
            (fake_bin / "codex.cmd").write_text(
                f'@"{sys.executable}" "%~dp0codex.py" %*\n', encoding="utf-8")
            home = root / "home"
            env = dict(os.environ, CODEX_HOME=str(home), TEST_DESTINATION=str(destination),
                       PYTHONDONTWRITEBYTECODE="1", PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
            versions = []
            for _ in range(2):
                installed = subprocess.run(
                    ["powershell", "-NoProfile", "-File", str(source_plugin / "scripts/install-windows.ps1"),
                     "-Destination", str(destination), "-BinDirectory", str(root / "launchers")],
                    cwd=source, env=env, capture_output=True, text=True, timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
                manifest = json.loads((destination / "plugins/jam-mode/.codex-plugin/plugin.json").read_text())
                version = manifest["version"]
                self.assertNotEqual(version, original)
                self.assertEqual(version.split("+", 1)[0], original.split("+", 1)[0])
                versions.append(version)
                config = json.loads((home / "cache" / version / ".mcp.json").read_text())["mcpServers"]["jam_mode"]
                self.assertTrue(Path(config["command"]).is_absolute())
                requests = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-06-18", "capabilities": {}}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                ]
                server = subprocess.run(
                    [config["command"], *config["args"]], cwd=config["cwd"], env=env,
                    input="".join(json.dumps(r) + "\n" for r in requests),
                    capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(server.returncode, 0, server.stderr)
                response = json.loads(server.stdout.splitlines()[-1])
                self.assertIn("jam_start_campaign", {t["name"] for t in response["result"]["tools"]})
            self.assertNotEqual(*versions)
